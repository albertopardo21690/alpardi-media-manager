"""Guarda de qué `ContentType` soporta HOY el pipeline de planning/matching.

Separado deliberadamente de `domain/models.py` para no mezclar modelos puros (sin reglas de
negocio) con una regla de "qué está implementado ahora mismo" que cambiará con el tiempo (más
`content_type` según se vayan conectando planning/matching a ellos). Vive en `domain/` -- la capa
más baja de docs/ARCHITECTURE.md -- porque tanto `cli/` como `mcp/` la necesitan y son capas
hermanas que no pueden importar una de la otra.

Este módulo es solo la guarda: no se conecta todavía a `cli/main.py` ni a `mcp/server.py` (eso
desbloquea los 4 puntos `content_type != "movie"` documentados en el plan de extensión a TV,
responsabilidad de un cambio posterior)."""
from __future__ import annotations

from alpardi_media_manager.domain.models import ContentType

CONTENT_TYPES_SOPORTADOS_PARA_PLAN_Y_MATCH: frozenset[ContentType] = frozenset({
    ContentType.MOVIE, ContentType.TV_EPISODE,
})


def verificar_content_type_soportado(content_type: ContentType) -> None:
    if content_type not in CONTENT_TYPES_SOPORTADOS_PARA_PLAN_Y_MATCH:
        raise ValueError(f"content_type '{content_type.value}' aún no soportado en plan/match")
