"""Modelos de dominio. Capa de solo datos -- sin I/O, sin llamadas a proveedores ni a Plex.

Cubre los campos mínimos que el encargo exige que la base de datos registre (sección
"Arquitectura mínima requerida"): identidad interna estable, biblioteca/raíz, ruta/tamaño/fechas/
extensión, device/inode, huella rápida y hash completo, tipo de contenido y relaciones
jerárquicas, más los estados de la máquina de states.py.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field, model_validator

from alpardi_media_manager.domain.states import ItemState


class ContentType(StrEnum):
    MOVIE = "movie"
    TV_SHOW = "tv_show"
    TV_SEASON = "tv_season"
    TV_EPISODE = "tv_episode"
    MUSIC_ARTIST = "music_artist"
    MUSIC_ALBUM = "music_album"
    MUSIC_TRACK = "music_track"
    PHOTO = "photo"
    OTHER_VIDEO = "other_video"
    EXTRA = "extra"  # tráiler, detrás de cámaras, etc. -- ver docs/PLEX_RULES.md


class RelationKind(StrEnum):
    """Cómo se relaciona un item con su padre en la jerarquía."""

    SEASON_OF_SHOW = "season_of_show"
    EPISODE_OF_SEASON = "episode_of_season"
    TRACK_OF_ALBUM = "track_of_album"
    ALBUM_OF_ARTIST = "album_of_artist"
    EXTRA_OF = "extra_of"          # tráiler/featurette de una película o serie
    VERSION_OF = "version_of"      # misma edición, distinta resolución/códec -- NO es una edición
    EDITION_OF = "edition_of"      # montaje/presentación realmente distinta -- nunca automático


class Fingerprint(BaseModel):
    """Huella técnica de un archivo. `quick` es barata (tamaño+mtime); `full_sha256` solo se
    calcula bajo petición (nivel "profundo" del encargo), nunca en cada escaneo por defecto."""

    size_bytes: int
    mtime: datetime
    quick: str                       # p.ej. sha256 de los primeros N bytes + size_bytes + mtime
    full_sha256: str | None = None
    full_sha256_computed_at: datetime | None = None


class DeviceInode(BaseModel):
    """Identificador de dispositivo/inodo, cuando sea fiable (no siempre lo es sobre red)."""

    device_id: int
    inode: int
    reliable: bool  # False si viene de un filesystem de red donde el inodo puede reciclarse


class InventoryItem(BaseModel):
    """Un archivo real dentro de una biblioteca autorizada. Identidad interna estable: `id` nunca
    cambia aunque el archivo se renombre o mueva -- eso es precisamente lo que permite planear un
    renombrado sin perder el hilo de qué elemento es cuál."""

    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    library_id: str
    authorized_root: str             # raíz de biblioteca autorizada bajo la que vive este archivo
    current_path: str                # ruta relativa a authorized_root, nunca absoluta guardada suelta
    extension: str
    content_type: ContentType
    state: ItemState = ItemState.DISCOVERED

    fingerprint: Fingerprint
    device_inode: DeviceInode | None = None

    parent_id: uuid.UUID | None = None
    relation_to_parent: RelationKind | None = None

    discovered_at: datetime
    updated_at: datetime

    @model_validator(mode="after")
    def _parent_id_y_relation_van_juntos(self) -> InventoryItem:
        # Evita un estado a medias: un padre sin decir la relación, o una relación sin padre.
        if (self.parent_id is None) != (self.relation_to_parent is None):
            raise ValueError(
                "parent_id y relation_to_parent deben ir ambos presentes o ambos ausentes"
            )
        return self


class Edition(BaseModel):
    """Montaje o presentación realmente distinta de una película/serie (p.ej. Director's Cut).
    Nunca se confunde con Version -- ver docs/PLEX_RULES.md."""

    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    parent_content_id: uuid.UUID  # la película/serie a la que pertenece
    name: str                      # va literal en {edition-Name}
    auto_detected: bool = False    # True solo si viene de evidencia real (NFO/proveedor), nunca inventado


class Version(BaseModel):
    """Misma edición, distinta resolución/códec/bitrate/contenedor. Se agrupan juntas, nunca se
    tratan como contenido distinto."""

    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    parent_content_id: uuid.UUID
    edition_id: uuid.UUID | None = None  # None = edición "por defecto" (sin {edition-...})
    technical_label: str                  # p.ej. "2160p HEVC HDR10"
