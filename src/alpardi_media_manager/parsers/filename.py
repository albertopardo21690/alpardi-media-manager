"""Interpretación de nombres de archivo/carpeta Plex-compatibles.

Solo lectura y solo interpretación -- nunca decide un ID de proveedor (eso es `matching/`), solo
extrae lo que el propio nombre ya dice de forma explícita. Patrones verificados contra
docs/PLEX_RULES.md / docs/SOURCES.md.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# Título (Año) {proveedor-id} {edition-Nombre} -- id y edition opcionales, en cualquier orden.
_RE_PELICULA = re.compile(
    r"^(?P<title>.+?)\s*\((?P<year>\d{4})\)"
    r"(?:\s*\{(?P<id_ns>tmdb|imdb)-(?P<id_val>[a-zA-Z0-9]+)\})?"
    r"(?:\s*\{edition-(?P<edition>[^}]+)\})?"
)

# Serie (Año) - sNNeMM[-eKK] - Título opcional  (año opcional, id opcional en el nombre de fichero)
_RE_EPISODIO = re.compile(
    r"^(?P<title>.+?)(?:\s*\((?P<year>\d{4})\))?"
    r"\s*-\s*s(?P<season>\d{1,4})e(?P<ep_start>\d{1,3})(?:-e(?P<ep_end>\d{1,3}))?"
    r"(?:\s*-\s*(?P<episode_title>.+))?$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class MovieNameInfo:
    title: str
    year: int
    external_id_namespace: str | None = None
    external_id_value: str | None = None
    edition: str | None = None


@dataclass(frozen=True)
class EpisodeNameInfo:
    show_title: str
    season: int
    episode_start: int
    episode_end: int | None
    year: int | None = None
    episode_title: str | None = None

    @property
    def is_multi_episode(self) -> bool:
        return self.episode_end is not None


def parsear_nombre_pelicula(nombre: str) -> MovieNameInfo | None:
    """`nombre` es el basename sin extensión, p.ej. "Blade Runner (1982) {tmdb-78} {edition-Final Cut}"."""
    m = _RE_PELICULA.match(nombre.strip())
    if not m:
        return None
    return MovieNameInfo(
        title=m.group("title").strip(),
        year=int(m.group("year")),
        external_id_namespace=m.group("id_ns"),
        external_id_value=m.group("id_val"),
        edition=m.group("edition"),
    )


def parsear_nombre_episodio(nombre: str) -> EpisodeNameInfo | None:
    """`nombre` es el basename sin extensión, p.ej. "Band of Brothers (2001) - s01e01 - Currahee"."""
    m = _RE_EPISODIO.match(nombre.strip())
    if not m:
        return None
    return EpisodeNameInfo(
        show_title=m.group("title").strip(),
        season=int(m.group("season")),
        episode_start=int(m.group("ep_start")),
        episode_end=int(m.group("ep_end")) if m.group("ep_end") else None,
        year=int(m.group("year")) if m.group("year") else None,
        episode_title=m.group("episode_title").strip() if m.group("episode_title") else None,
    )


def es_carpeta_temporada(nombre: str) -> int | None:
    """Devuelve el número de temporada si `nombre` es una carpeta 'Season NN' (o 'Season 00' /
    'Specials' -- caso especial: devuelve 0), None si no coincide. 'Season' debe ir literal,
    incluso en contenido en español -- confirmado en docs/SOURCES.md."""
    if nombre.strip().lower() == "specials":
        return 0
    m = re.match(r"^Season\s+(\d{1,4})$", nombre.strip())
    return int(m.group(1)) if m else None
