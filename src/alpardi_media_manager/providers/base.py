"""Interfaz común que todo adaptador de proveedor debe implementar.

Los adaptadores son de LECTURA por defecto -- ninguno escribe NFO, nombres, arte ni datos de Plex
directamente. El flujo obligatorio (ver encargo) es:

    consulta autorizada -> respuesta del proveedor -> validación -> normalización
    -> candidatos con procedencia -> revisión/política -> plan inmutable
    -> autorización -> materialización local -> refresco y verificación Plex

Ningún adaptador debe fingir una capacidad que no tiene -- `capabilities` es la fuente de verdad
que el resto del sistema consulta antes de llamar a un método.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from alpardi_media_manager.providers.models import (
    Capability,
    ExternalId,
    ProviderHealth,
    ProviderRecord,
    ProviderRef,
    SearchCandidate,
)


@dataclass(frozen=True)
class SearchQuery:
    title: str
    entity_type: str                 # movie | tv | music_artist | ...
    year: int | None = None
    language: str | None = None
    region: str | None = None


@dataclass(frozen=True)
class FetchRequest:
    include: frozenset[str] = frozenset()  # p.ej. {"external_ids", "images", "credits"}


class ProviderAdapter(Protocol):
    name: str
    capabilities: frozenset[Capability]

    async def search(self, query: SearchQuery) -> list[SearchCandidate]: ...

    async def get(self, ref: ProviderRef, request: FetchRequest) -> ProviderRecord: ...

    async def find_by_external_id(self, external_id: ExternalId) -> list[SearchCandidate]: ...

    async def healthcheck(self) -> ProviderHealth: ...


def requiere_capacidad(adapter: ProviderAdapter, capacidad: Capability) -> None:
    """Guarda explícita: nunca llamar a un método que el adaptador no declara soportar.
    Lanza ValueError en vez de dejar que el adaptador finja o falle de forma confusa."""
    if capacidad not in adapter.capabilities:
        raise ValueError(
            f"El proveedor '{adapter.name}' no declara la capacidad '{capacidad.value}'"
        )
