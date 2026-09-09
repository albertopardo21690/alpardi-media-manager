"""Modelos normalizados comunes a todos los adaptadores de proveedores.

Ningún adaptador inventa su propio formato -- todos hablan estos mismos tipos. Ver
"Contrato común de proveedores" del encargo para la lista exacta de capacidades y modelos.
"""
from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel


class Capability(StrEnum):
    MOVIE_SEARCH = "movie_search"
    MOVIE_DETAILS = "movie_details"
    TV_SEARCH = "tv_search"
    TV_DETAILS = "tv_details"
    SEASON_DETAILS = "season_details"
    EPISODE_DETAILS = "episode_details"
    ALTERNATE_ORDERS = "alternate_orders"
    EXTERNAL_ID_LOOKUP = "external_id_lookup"
    TRANSLATIONS = "translations"
    CERTIFICATIONS = "certifications"
    CREDITS = "credits"
    RATINGS = "ratings"
    COLLECTIONS = "collections"
    IMAGES = "images"
    VIDEOS = "videos"
    SUBTITLES_SEARCH = "subtitles_search"
    SUBTITLES_DOWNLOAD = "subtitles_download"
    MUSIC_METADATA = "music_metadata"
    MUSIC_ARTWORK = "music_artwork"
    ANIME_METADATA = "anime_metadata"
    SPORTS_METADATA = "sports_metadata"
    USER_STATE_READ = "user_state_read"
    USER_STATE_WRITE = "user_state_write"
    CHANGES_FEED = "changes_feed"


class ExternalIdStatus(StrEnum):
    ACTIVE = "active"
    REDIRECTED = "redirected"
    CONFLICTING = "conflicting"
    UNVERIFIED = "unverified"


class ProviderRef(BaseModel):
    """Referencia inmutable a una entidad dentro de UN proveedor concreto. Nunca es la clave
    primaria de nuestra base -- la entidad canónica es siempre local (ver encargo, "Principio
    rector" de integración de fuentes externas)."""

    provider: str
    entity_type: str
    provider_id: str


class ExternalId(BaseModel):
    namespace: str                      # p.ej. "tmdb", "imdb", "tvdb"
    value: str
    canonical_url: str | None = None
    source: str
    validated_at: datetime
    status: ExternalIdStatus = ExternalIdStatus.UNVERIFIED


class SearchCandidate(BaseModel):
    provider: str
    title_localized: str
    title_original: str | None = None
    year_or_date: str | None = None
    entity_type: str
    external_ids: list[ExternalId] = []
    country: str | None = None
    duration_minutes: float | None = None
    summary: str | None = None
    # Evidencia registrada -- nunca una cifra inventada por el modelo (regla no negociable).
    evidence: dict[str, str] = {}
    score: float
    score_breakdown: dict[str, float] = {}


class FieldValue(BaseModel):
    value: str
    language: str | None = None
    region: str | None = None
    provider: str
    reference: str                       # URL o ID de la respuesta concreta de la que vino
    fetched_at: datetime
    confidence: float
    priority: int
    review_state: str = "unreviewed"     # unreviewed | accepted | rejected
    locked: bool = False                 # bloqueo manual -- nunca se sobrescribe si locked=True


class ProviderRecord(BaseModel):
    provider: str
    ref: ProviderRef
    fields: dict[str, FieldValue] = {}
    fetched_at: datetime
    expires_at: datetime | None = None
    schema_version: int
    license: str
    attribution: str


class AssetCandidate(BaseModel):
    plex_asset_type: str                 # poster | background | clearlogo | ...
    url: str
    language: str | None = None
    width: int | None = None
    height: int | None = None
    aspect_ratio: str | None = None
    size_bytes: int | None = None
    votes_or_preference: float | None = None
    license: str
    provider: str
    hash_after_download: str | None = None  # se rellena tras descargar, no antes


class SubtitleCandidate(BaseModel):
    language: str
    format: str
    forced: bool = False
    sdh: bool = False
    fps: float | None = None
    edition_or_release: str | None = None
    video_hash: str | None = None
    uploader: str | None = None
    score: float
    provider: str
    estimated_quota_cost: int = 1


class ProviderHealth(BaseModel):
    provider: str
    status: str                          # ok | degraded | down | disabled
    latency_ms: float | None = None
    authenticated: bool
    capabilities: frozenset[Capability]
    known_quota_remaining: int | None = None
    last_429_at: datetime | None = None
    circuit_open: bool = False
    message_redacted: str | None = None
