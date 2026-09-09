"""Asociación de sidecars a un archivo de vídeo: NFO, subtítulos externos, imágenes locales.

Solo lectura -- detecta qué existe, no crea ni modifica nada. Convenciones verificadas en
docs/PLEX_RULES.md / docs/SOURCES.md.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

SUFIJOS_SUBTITULO = {".srt", ".smi", ".ssa", ".ass", ".vtt"}
NOMBRES_ARTE_PELICULA = {"poster.jpg", "poster.png", "background.jpg", "fanart.jpg", "clearlogo.png", "square.jpg"}
NOMBRES_ARTE_SERIE = {"poster.jpg", "banner.jpg", "clearlogo.png"}


@dataclass(frozen=True)
class Sidecars:
    video_path: Path
    nfo_path: Path | None = None
    subtitles: tuple[Path, ...] = field(default_factory=tuple)
    local_art: tuple[Path, ...] = field(default_factory=tuple)


def _basename_sin_extension(path: Path) -> str:
    return path.name[: -len(path.suffix)] if path.suffix else path.name


def encontrar_sidecars(video_path: Path) -> Sidecars:
    """Busca sidecars en el mismo directorio que `video_path`. No sigue enlaces simbólicos hacia
    fuera del directorio -- todo lo que se busca vive ya al lado del vídeo.

    Si la carpeta ya no existe (p.ej. el archivo se borró entre el escaneo y este análisis --
    una condición de carrera real, no hipotética, en un árbol que otra sesión puede tocar a la
    vez), se devuelve un Sidecars vacío en vez de dejar que iterdir() lance una excepción sin
    controlar."""
    carpeta = video_path.parent
    if not carpeta.is_dir():
        return Sidecars(video_path=video_path)
    base = _basename_sin_extension(video_path)

    nfo_candidato = carpeta / f"{base}.nfo"
    nfo = nfo_candidato if nfo_candidato.is_file() else None

    subtitulos = tuple(
        sorted(
            p for p in carpeta.iterdir()
            if p.is_file() and p.suffix.lower() in SUFIJOS_SUBTITULO and p.name.startswith(base)
        )
    )

    arte = tuple(
        sorted(
            carpeta / nombre
            for nombre in NOMBRES_ARTE_PELICULA
            if (carpeta / nombre).is_file()
        )
    )

    return Sidecars(video_path=video_path, nfo_path=nfo, subtitles=subtitulos, local_art=arte)
