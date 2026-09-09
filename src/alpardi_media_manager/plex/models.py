"""Modelos normalizados de lo que devuelve la API de Plex. Todos los campos que la API solo
incluye "cuando aplica" (visto, valorado, en una colección, con campos bloqueados...) son
opcionales aquí con su valor por defecto real -- verificado contra el servidor real de Alberto
(2026-09-09), nunca asumido de la documentación sin comprobar.
"""
from __future__ import annotations

from pydantic import BaseModel


class PlexLibraryLocation(BaseModel):
    id: int
    path: str


class PlexLibrary(BaseModel):
    key: str
    type: str
    title: str
    agent: str
    scanner: str
    language: str
    uuid: str
    updated_at: int
    created_at: int
    scanned_at: int
    locations: list[PlexLibraryLocation] = []


class PlexMediaPart(BaseModel):
    id: int
    file: str
    size: int
    container: str | None = None


class PlexItemSnapshot(BaseModel):
    """Instantánea de un elemento de Plex -- exactamente los campos que el encargo pide conservar
    antes de un lote: GUID/IDs, rutas, ratingKey, estado visto, progreso, valoración, fecha
    añadida, colecciones, campos bloqueados y recursos (rutas de archivo) que la API permite
    consultar."""

    rating_key: str
    key: str
    guid: str | None = None
    type: str
    title: str
    year: int | None = None
    added_at: int
    updated_at: int
    view_count: int = 0
    view_offset: int | None = None
    last_viewed_at: int | None = None
    user_rating: float | None = None
    collections: list[str] = []
    locked_fields: list[str] = []
    file_paths: list[str] = []
