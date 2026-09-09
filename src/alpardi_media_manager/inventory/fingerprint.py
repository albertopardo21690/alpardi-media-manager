"""Cálculo de huellas de archivo. Solo lectura -- nunca modifica el archivo original.

Dos niveles, tal como exige el encargo ("Inventario técnico y calidad"):
- rápido: metadatos de contenedor (tamaño, mtime) + una muestra corta del contenido -- barato,
  se calcula en cada escaneo.
- profundo: hash sha256 completo del archivo -- caro, solo bajo petición explícita.
"""
from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

from alpardi_media_manager.domain.models import Fingerprint

_MUESTRA_RAPIDA_BYTES = 65536  # primeros 64KiB -- suficiente para distinguir sin leer todo el archivo


def calcular_fingerprint_rapido(path: Path) -> Fingerprint:
    stat = path.stat()
    with open(path, "rb") as f:
        muestra = f.read(_MUESTRA_RAPIDA_BYTES)
    hasher = hashlib.sha256()
    hasher.update(str(stat.st_size).encode())
    hasher.update(muestra)
    return Fingerprint(
        size_bytes=stat.st_size,
        mtime=datetime.fromtimestamp(stat.st_mtime, tz=UTC),
        quick=hasher.hexdigest(),
    )


def calcular_hash_completo(path: Path) -> str:
    """Nivel profundo -- caro, nunca se llama desde un escaneo normal (ver encargo)."""
    hasher = hashlib.sha256()
    with open(path, "rb") as f:
        for bloque in iter(lambda: f.read(1024 * 1024), b""):
            hasher.update(bloque)
    return hasher.hexdigest()


def anadir_hash_completo(fp: Fingerprint, path: Path) -> Fingerprint:
    """Devuelve una copia de `fp` con full_sha256 relleno -- no muta el original (Fingerprint es
    inmutable por convención, aunque pydantic no lo fuerce salvo que se pase frozen=True)."""
    return fp.model_copy(update={
        "full_sha256": calcular_hash_completo(path),
        "full_sha256_computed_at": datetime.now(UTC),
    })
