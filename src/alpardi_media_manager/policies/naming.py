"""Genera nombres de carpeta/archivo propuestos a partir de `config/naming-policies.yaml`.

Puramente de solo lectura/generación de texto -- NUNCA toca un archivo real. El resultado de
este módulo es un `str` propuesto; aplicarlo de verdad es responsabilidad exclusiva de
`transactions/`, y solo tras un plan autorizado.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

RUTA_POLITICAS_DEFECTO = Path(__file__).parent.parent.parent.parent / "config" / "naming-policies.yaml"


def cargar_politicas(ruta: Path = RUTA_POLITICAS_DEFECTO) -> dict[str, Any]:
    with open(ruta, encoding="utf-8") as f:
        data: dict[str, Any] = yaml.safe_load(f)
    return data


def _plantilla(politicas: dict[str, Any], seccion: str, clave: str) -> str:
    """Extrae una plantilla del YAML ya tipada como str -- corta de raíz la propagación de `Any`
    que mypy (en modo strict) señala si se usa .format() directamente sobre un valor de dict[str, Any]."""
    return str(politicas[seccion][clave])


@dataclass(frozen=True)
class MovieNamingInput:
    title: str
    year: int
    external_id_namespace: str | None = None
    external_id_value: str | None = None
    edition: str | None = None
    technical_suffix: str | None = None  # p.ej. "2160p HEVC HDR10" -- ver Version en domain/models.py


@dataclass(frozen=True)
class EpisodeNamingInput:
    show_title: str
    year: int
    season: int
    episode_start: int
    episode_end: int | None = None
    episode_title: str | None = None
    external_id_namespace: str | None = None
    external_id_value: str | None = None


def _id_suffix(politicas: dict[str, Any], namespace: str | None, valor: str | None) -> str:
    if not namespace or not valor:
        return ""
    return _plantilla(politicas, "movies", "id_suffix_format").format(provider=namespace, id=valor)


def _edition_suffix(politicas: dict[str, Any], edicion: str | None) -> str:
    if not edicion:
        return ""
    return _plantilla(politicas, "movies", "edition_suffix_format").format(edition_name=edicion)


def proponer_carpeta_pelicula(entrada: MovieNamingInput, politicas: dict[str, Any] | None = None) -> str:
    politicas = politicas or cargar_politicas()
    id_suf = _id_suffix(politicas, entrada.external_id_namespace, entrada.external_id_value)
    ed_suf = _edition_suffix(politicas, entrada.edition)
    return _plantilla(politicas, "movies", "folder").format(
        title=entrada.title, year=entrada.year, id_suffix=id_suf + ed_suf,
    )


def proponer_archivo_pelicula(
    entrada: MovieNamingInput, extension: str, politicas: dict[str, Any] | None = None,
) -> str:
    politicas = politicas or cargar_politicas()
    id_suf = _id_suffix(politicas, entrada.external_id_namespace, entrada.external_id_value)
    ed_suf = _edition_suffix(politicas, entrada.edition)
    plantilla = _plantilla(politicas, "movies", "file")
    if entrada.technical_suffix:
        nombre = plantilla.format(
            title=entrada.title, year=entrada.year, id_suffix=id_suf + ed_suf,
            technical_suffix=entrada.technical_suffix,
        )
    else:
        # Sin sufijo técnico (versión única): quitar el " - {technical_suffix}" sobrante en vez
        # de dejar un guion colgando sin nada detrás.
        nombre = plantilla.replace(" - {technical_suffix}", "").format(
            title=entrada.title, year=entrada.year, id_suffix=id_suf + ed_suf,
        )
    return nombre + extension


def proponer_carpeta_temporada(temporada: int, politicas: dict[str, Any] | None = None) -> str:
    politicas = politicas or cargar_politicas()
    if temporada == 0:
        return _plantilla(politicas, "tv_shows", "specials_folder")
    return _plantilla(politicas, "tv_shows", "season_folder").format(season=temporada)


def proponer_archivo_episodio(
    entrada: EpisodeNamingInput, extension: str, politicas: dict[str, Any] | None = None,
) -> str:
    politicas = politicas or cargar_politicas()
    if entrada.episode_end is not None:
        nombre = _plantilla(politicas, "tv_shows", "multi_episode_file").format(
            title=entrada.show_title, year=entrada.year, season=entrada.season,
            episode_start=entrada.episode_start, episode_end=entrada.episode_end,
            optional_info=entrada.episode_title or "",
        )
    else:
        nombre = _plantilla(politicas, "tv_shows", "episode_file").format(
            title=entrada.show_title, year=entrada.year, season=entrada.season,
            episode=entrada.episode_start, episode_title=entrada.episode_title or "",
        )
    return nombre.rstrip(" -") + extension
