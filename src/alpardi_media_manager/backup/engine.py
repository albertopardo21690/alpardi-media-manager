"""Copia de seguridad de los datos OPERATIVOS del propio proyecto -- planes, journals, informes y
configuración real (`config/*.yaml`, sin las plantillas `.example.yaml`). NUNCA de la colección
multimedia: eso queda fuera a propósito, regla explícita de `docs/BACKUP_RESTORE.md` (mismo
patrón de lista de inclusión explícita, no de exclusión, que evitó una fuga real de ~63GB en el
proyecto AlpardiOS el 2026-09-07).

Hoy `plans/`, `journals/` y `reports/` normalmente no existen todavía -- nadie ha aplicado un plan
real contra datos reales. Un backup con 0 archivos es un resultado válido y honesto, no un error.
"""
from __future__ import annotations

import hashlib
import tarfile
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

_DIRECTORIOS_INCLUIDOS = ("plans", "journals", "reports")
_CONFIG_INCLUIDO = "config"
_CONFIG_SUFIJO_EXCLUIDO = ".example.yaml"


@dataclass(frozen=True)
class ResultadoBackup:
    archive_path: Path
    sha256_path: Path
    file_count: int
    total_bytes: int
    sha256: str


@dataclass(frozen=True)
class ResultadoVerificacion:
    ok: bool
    detail: str


def _listar_archivos_a_incluir(raiz_proyecto: Path) -> list[Path]:
    archivos: list[Path] = []
    for nombre in _DIRECTORIOS_INCLUIDOS:
        carpeta = raiz_proyecto / nombre
        if carpeta.is_dir():
            archivos.extend(p for p in sorted(carpeta.rglob("*")) if p.is_file())

    carpeta_config = raiz_proyecto / _CONFIG_INCLUIDO
    if carpeta_config.is_dir():
        archivos.extend(
            p for p in sorted(carpeta_config.glob("*.yaml"))
            if p.is_file() and not p.name.endswith(_CONFIG_SUFIJO_EXCLUIDO)
        )
    return archivos


def crear_backup(raiz_proyecto: Path, directorio_salida: Path, ahora: datetime) -> ResultadoBackup:
    """Nunca incluye rutas fuera de `raiz_proyecto` -- `arcname` siempre se calcula relativo a
    ella, así que el propio tar tampoco puede acabar conteniendo una ruta absoluta del sistema."""
    archivos = _listar_archivos_a_incluir(raiz_proyecto)
    directorio_salida.mkdir(parents=True, exist_ok=True)
    marca_tiempo = ahora.strftime("%Y%m%dT%H%M%SZ")
    ruta_archivo = directorio_salida / f"alpardimedia-backup-{marca_tiempo}.tar.gz"

    total_bytes = 0
    with tarfile.open(ruta_archivo, "w:gz") as tar:
        for archivo in archivos:
            tar.add(archivo, arcname=str(archivo.relative_to(raiz_proyecto)))
            total_bytes += archivo.stat().st_size

    sha256 = hashlib.sha256(ruta_archivo.read_bytes()).hexdigest()
    ruta_sha256 = ruta_archivo.with_suffix(ruta_archivo.suffix + ".sha256")
    ruta_sha256.write_text(f"{sha256}  {ruta_archivo.name}\n", encoding="utf-8")

    return ResultadoBackup(
        archive_path=ruta_archivo, sha256_path=ruta_sha256,
        file_count=len(archivos), total_bytes=total_bytes, sha256=sha256,
    )


def verificar_backup(ruta_archivo: Path) -> ResultadoVerificacion:
    """Nunca basta con que el fichero exista -- regla explícita de BACKUP_RESTORE.md: se
    recalcula el hash real desde los bytes del disco y se extrae de verdad a una carpeta temporal
    para confirmar que el tar no está corrupto, no solo que tenga la extensión correcta."""
    if not ruta_archivo.exists():
        return ResultadoVerificacion(ok=False, detail=f"No existe el archivo: {ruta_archivo}")

    ruta_sha256 = ruta_archivo.with_suffix(ruta_archivo.suffix + ".sha256")
    if not ruta_sha256.exists():
        return ResultadoVerificacion(ok=False, detail=f"No existe el sha256 esperado: {ruta_sha256}")

    esperado = ruta_sha256.read_text(encoding="utf-8").split()[0]
    real = hashlib.sha256(ruta_archivo.read_bytes()).hexdigest()
    if real != esperado:
        return ResultadoVerificacion(ok=False, detail=f"sha256 no coincide: esperado {esperado}, real {real}")

    try:
        with tarfile.open(ruta_archivo, "r:gz") as tar, tempfile.TemporaryDirectory() as tmp:
            tar.extractall(tmp, filter="data")
    except tarfile.TarError as exc:
        return ResultadoVerificacion(ok=False, detail=f"El tar está corrupto: {exc}")

    return ResultadoVerificacion(ok=True, detail="sha256 coincide y el tar se extrae correctamente")
