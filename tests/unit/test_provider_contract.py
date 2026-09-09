from datetime import UTC, datetime

import pytest

from alpardi_media_manager.providers.base import (
    FetchRequest,
    ProviderAdapter,
    SearchQuery,
    requiere_capacidad,
)
from alpardi_media_manager.providers.models import (
    Capability,
    ExternalId,
    ExternalIdStatus,
    ProviderHealth,
    ProviderRecord,
    ProviderRef,
    SearchCandidate,
)


class _AdaptadorFalso:
    """Doble de prueba mínimo -- solo declara movie_search, nada más."""

    name = "fake"
    capabilities = frozenset({Capability.MOVIE_SEARCH})

    async def search(self, query: SearchQuery) -> list[SearchCandidate]:
        return [
            SearchCandidate(
                provider=self.name, title_localized=query.title, entity_type="movie",
                score=1.0, evidence={"match": "exact_title"},
            )
        ]

    async def get(self, ref: ProviderRef, request: FetchRequest) -> ProviderRecord:
        return ProviderRecord(
            provider=self.name, ref=ref, fetched_at=datetime.now(UTC),
            schema_version=1, license="test", attribution="test",
        )

    async def find_by_external_id(self, external_id: ExternalId) -> list[SearchCandidate]:
        return []

    async def healthcheck(self) -> ProviderHealth:
        return ProviderHealth(
            provider=self.name, status="ok", authenticated=True, capabilities=self.capabilities,
        )


def test_requiere_capacidad_pasa_si_la_declara():
    adapter = _AdaptadorFalso()
    requiere_capacidad(adapter, Capability.MOVIE_SEARCH)  # no debe lanzar


def test_requiere_capacidad_falla_si_no_la_declara():
    """Un proveedor nunca debe poder 'fingir' una capacidad que no tiene -- regla explícita
    del encargo ('No obligues a un proveedor a fingir capacidades que no tiene')."""
    adapter = _AdaptadorFalso()
    with pytest.raises(ValueError, match="tv_search"):
        requiere_capacidad(adapter, Capability.TV_SEARCH)


@pytest.mark.asyncio
async def test_adaptador_falso_cumple_el_protocolo_completo():
    adapter: ProviderAdapter = _AdaptadorFalso()
    candidatos = await adapter.search(SearchQuery(title="Blade Runner", entity_type="movie"))
    assert len(candidatos) == 1
    assert candidatos[0].evidence  # nunca una puntuación sin evidencia registrada

    salud = await adapter.healthcheck()
    assert salud.status == "ok"


def test_external_id_por_defecto_no_verificado():
    """Nunca se asume 'active' sin verificación explícita -- por defecto 'unverified'."""
    eid = ExternalId(namespace="tmdb", value="78", source="test", validated_at=datetime.now(UTC))
    assert eid.status == ExternalIdStatus.UNVERIFIED
