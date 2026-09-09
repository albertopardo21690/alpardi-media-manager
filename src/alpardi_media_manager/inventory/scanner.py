"""Escaneo de una raíz de biblioteca. Solo lectura -- nunca escribe, nunca sigue enlaces
simbólicos fuera de la raíz autorizada (regla de seguridad del encargo).
"""
from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

from alpardi_media_manager.domain.models import ContentType, InventoryItem
from alpardi_media_manager.inventory.fingerprint import calcular_fingerprint_rapido

EXTENSIONES_VIDEO = {
    ".mkv", ".mp4", ".avi", ".mov", ".m4v", ".ts", ".m2ts", ".wmv", ".mpg", ".mpeg",
}

# Carpetas que Plex excluye por convención -- no se inventarían nunca aunque contengan vídeo.
CARPETAS_EXCLUIDAS = {"@eaDir", "#recycle", ".plexignore", "extras"}


def _dentro_de_la_raiz(candidato: Path, raiz_real: Path) -> bool:
    """Comprueba, tras resolver symlinks, que `candidato` sigue dentro de `raiz_real` -- evita
    que un enlace simbólico haga "escapar" el escaneo de la raíz autorizada."""
    try:
        candidato.resolve().relative_to(raiz_real)
        return True
    except ValueError:
        return False


def _iterar_videos(raiz: Path) -> Iterator[Path]:
    raiz_real = raiz.resolve()
    for dirpath, dirnames, filenames in os.walk(raiz):
        dirnames[:] = [d for d in dirnames if d not in CARPETAS_EXCLUIDAS and not d.startswith(".")]
        for nombre in filenames:
            candidato = Path(dirpath) / nombre
            if candidato.suffix.lower() in EXTENSIONES_VIDEO and _dentro_de_la_raiz(candidato, raiz_real):
                yield candidato


def escanear_directorio(
    raiz: Path,
    library_id: str,
    content_type: ContentType,
) -> list[InventoryItem]:
    """Escaneo plano de solo lectura: un InventoryItem por vídeo encontrado bajo `raiz`, con su
    fingerprint rápido ya calculado. La clasificación fina (película vs episodio, relaciones
    jerárquicas) la añade `parsers/` en un paso posterior -- este módulo solo descubre y da fe de
    lo que hay en disco ahora mismo."""
    raiz = raiz.resolve()
    ahora = datetime.now(UTC)
    items = []
    for video_path in _iterar_videos(raiz):
        items.append(InventoryItem(
            library_id=library_id,
            authorized_root=str(raiz),
            current_path=str(video_path.relative_to(raiz)),
            extension=video_path.suffix.lower(),
            content_type=content_type,
            fingerprint=calcular_fingerprint_rapido(video_path),
            discovered_at=ahora,
            updated_at=ahora,
        ))
    return items
