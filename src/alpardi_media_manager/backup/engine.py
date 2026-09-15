"""Copia de seguridad de los datos OPERATIVOS del propio proyecto -- planes, journals, informes,
configuración real (`config/*.yaml`, sin las plantillas `.example.yaml`) y, desde la Fase 8, un
snapshot consistente del catálogo SQLite (`persistence/`). NUNCA de la colección multimedia: eso
queda fuera a propósito, regla explícita de `docs/BACKUP_RESTORE.md` (mismo patrón de lista de
inclusión explícita, no de exclusión, que evitó una fuga real de ~63GB en el proyecto AlpardiOS el
2026-09-07).

Hoy `plans/`, `journals/` y `reports/` normalmente no existen todavía -- nadie ha aplicado un plan
real contra datos reales. Un backup con 0 archivos es un resultado válido y honesto, no un error.
Lo mismo vale para la base SQLite: si `data/alpardi_media_manager.sqlite3` todavía no existe (nadie
ha hecho `catalog sync` todavía), el backup se sigue creando igual, sin ella.
"""
from __future__ import annotations

import hashlib
import tarfile
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from alpardi_media_manager.persistence.db import checkpoint_para_backup

_DIRECTORIOS_INCLUIDOS = ("plans", "journals", "reports")
_CONFIG_INCLUIDO = "config"
_CONFIG_SUFIJO_EXCLUIDO = ".example.yaml"

# Misma ruta relativa que `config.py::DEFAULT_DATABASE_PATH` resuelve para la raíz real del
# proyecto -- aquí se mantiene independiente de `config.py` (relativa a `raiz_proyecto`, el mismo
# parámetro que ya usan `_DIRECTORIOS_INCLUIDOS`/`_CONFIG_INCLUIDO`) para no acoplar este módulo a
# la resolución de configuración por variable de entorno, que es un problema distinto.
_RUTA_RELATIVA_BASE_DE_DATOS = Path("data") / "alpardi_media_manager.sqlite3"


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


def _snapshot_base_de_datos(raiz_proyecto: Path, directorio_temporal: Path) -> Path | None:
    """Produce un snapshot consistente de un solo fichero de `data/alpardi_media_manager.sqlite3`
    dentro de `directorio_temporal`, o `None` si esa base todavía no existe -- caso válido, no un
    error (ver docstring del módulo). Reutiliza `persistence.db.checkpoint_para_backup()` (que ya
    hace `VACUUM INTO`, verificado real con SQLite 3.46.1) en vez de reimplementar la misma lógica.

    Nunca se empaqueta el `.sqlite3` vivo directamente: en modo WAL (activado por
    `persistence.db.abrir_conexion()` en cada conexión) el dato más reciente puede estar solo en el
    fichero `-wal`, todavía no volcado al fichero principal -- `VACUUM INTO` sí lee la vista
    consistente y fusionada (base + WAL) que SQLite expone, por eso el snapshot resultante nunca
    pierde escrituras confirmadas aunque no haya habido ningún checkpoint manual."""
    origen = raiz_proyecto / _RUTA_RELATIVA_BASE_DE_DATOS
    if not origen.exists():
        return None
    destino = directorio_temporal / _RUTA_RELATIVA_BASE_DE_DATOS.name
    checkpoint_para_backup(origen, destino)
    return destino


def crear_backup(raiz_proyecto: Path, directorio_salida: Path, ahora: datetime) -> ResultadoBackup:
    """Nunca incluye rutas fuera de `raiz_proyecto` -- `arcname` siempre se calcula relativo a
    ella (o, para la base SQLite, se fija explícitamente a `data/alpardi_media_manager.sqlite3`,
    nunca al nombre del fichero temporal del snapshot), así que el propio tar tampoco puede acabar
    conteniendo una ruta absoluta del sistema."""
    archivos = _listar_archivos_a_incluir(raiz_proyecto)
    directorio_salida.mkdir(parents=True, exist_ok=True)
    marca_tiempo = ahora.strftime("%Y%m%dT%H%M%SZ")
    ruta_archivo = directorio_salida / f"alpardimedia-backup-{marca_tiempo}.tar.gz"

    total_bytes = 0
    file_count = len(archivos)
    with (
        tempfile.TemporaryDirectory() as directorio_temporal_str,
        tarfile.open(ruta_archivo, "w:gz") as tar,
    ):
        for archivo in archivos:
            tar.add(archivo, arcname=str(archivo.relative_to(raiz_proyecto)))
            total_bytes += archivo.stat().st_size

        snapshot_bd = _snapshot_base_de_datos(raiz_proyecto, Path(directorio_temporal_str))
        if snapshot_bd is not None:
            tar.add(snapshot_bd, arcname=str(_RUTA_RELATIVA_BASE_DE_DATOS))
            total_bytes += snapshot_bd.stat().st_size
            file_count += 1

    sha256 = hashlib.sha256(ruta_archivo.read_bytes()).hexdigest()
    ruta_sha256 = ruta_archivo.with_suffix(ruta_archivo.suffix + ".sha256")
    ruta_sha256.write_text(f"{sha256}  {ruta_archivo.name}\n", encoding="utf-8")

    return ResultadoBackup(
        archive_path=ruta_archivo, sha256_path=ruta_sha256,
        file_count=file_count, total_bytes=total_bytes, sha256=sha256,
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
