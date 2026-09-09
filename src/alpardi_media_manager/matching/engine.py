"""Motor de coincidencias: decide si un elemento local coincide con un candidato de proveedor.

Orden de evidencias exacto del encargo:
    1. ID válido ya presente en nombre, NFO o Plex.
    2. NFO local coherente.
    3. Título, año y estructura episódica.
    4. Duración y datos técnicos como comprobación auxiliar.
    5. Resultado de proveedor oficial.

Reglas innegociables (todas con test explícito en tests/unit/test_matching_engine.py):
    - Un ID exacto de tipo incorrecto no se acepta.
    - Año desconocido no equivale a año coincidente.
    - No se convierte null/cadena vacía/dato ausente en el mismo estado.
    - No se sobrescribe un ID ya validado y bloqueado con un candidato "mejor".
    - La puntuación se calcula con evidencias registradas -- nunca una cifra inventada.
    - Si dos fuentes discrepan, el elemento queda needs_review, nunca se decide por mayoría.

Puramente de decisión -- no llama a ningún proveedor ni escribe nada. Los `SearchCandidate` de
entrada ya vienen resueltos por quien llame a este módulo (real o sintético para tests).
"""
from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path

from alpardi_media_manager.domain.models import InventoryItem
from alpardi_media_manager.domain.states import ItemState
from alpardi_media_manager.parsers.filename import parsear_nombre_pelicula
from alpardi_media_manager.providers.models import SearchCandidate


@dataclass(frozen=True)
class LocalEvidence:
    """Lo que ya se sabe del elemento ANTES de consultar cualquier proveedor -- del nombre de
    archivo, un NFO local, o un ID ya registrado en Plex."""

    parsed_title: str
    parsed_year: int | None = None
    entity_type: str = "movie"
    external_id_namespace: str | None = None  # ya presente en nombre/NFO/Plex
    external_id_value: str | None = None
    locked: bool = False  # ID validado y bloqueado manualmente -- nunca se reconsidera


@dataclass(frozen=True)
class MatchDecision:
    state: ItemState  # solo MATCHED o NEEDS_REVIEW -- este módulo nunca decide otro estado
    candidate: SearchCandidate | None
    score: float
    reasons: tuple[str, ...] = field(default_factory=tuple)


def _normalizar(texto: str) -> str:
    sin_acentos = "".join(
        c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn"
    )
    return sin_acentos.strip().lower()


def _similitud_titulo(a: str, b: str) -> float:
    return SequenceMatcher(None, _normalizar(a), _normalizar(b)).ratio()


def _candidato_tiene_id(candidato: SearchCandidate, namespace: str, valor: str) -> bool:
    return any(
        eid.namespace == namespace and eid.value == valor
        for eid in candidato.external_ids
    )


def decidir_coincidencia(evidencia: LocalEvidence, candidatos: list[SearchCandidate]) -> MatchDecision:
    # --- Paso 1: ID ya validado y bloqueado -- nunca se reconsidera, ni con un candidato "mejor". ---
    if evidencia.locked and evidencia.external_id_namespace and evidencia.external_id_value:
        exacto = next(
            (c for c in candidatos if c.entity_type == evidencia.entity_type
             and _candidato_tiene_id(c, evidencia.external_id_namespace, evidencia.external_id_value)),
            None,
        )
        return MatchDecision(
            state=ItemState.MATCHED, candidate=exacto, score=1.0,
            reasons=("id_bloqueado_no_se_reconsidera",),
        )

    # --- Paso 1b: ID ya presente pero no bloqueado -- se valida contra los candidatos reales. ---
    if evidencia.external_id_namespace and evidencia.external_id_value:
        coincidencias_id = [
            c for c in candidatos
            if _candidato_tiene_id(c, evidencia.external_id_namespace, evidencia.external_id_value)
        ]
        # Un ID exacto de TIPO incorrecto no se acepta -- filtrar por entity_type también.
        coincidencias_id_tipo_correcto = [c for c in coincidencias_id if c.entity_type == evidencia.entity_type]
        if coincidencias_id_tipo_correcto:
            return MatchDecision(
                state=ItemState.MATCHED, candidate=coincidencias_id_tipo_correcto[0], score=1.0,
                reasons=("id_ya_presente_validado",),
            )
        if coincidencias_id:  # el ID existe pero para un tipo de entidad distinto -- no se acepta
            return MatchDecision(
                state=ItemState.NEEDS_REVIEW, candidate=None, score=0.0,
                reasons=("id_presente_pero_tipo_incorrecto",),
            )

    # --- Paso 3: título + año (paso 2, NFO, se trata igual que "evidencia local" aquí --
    # el NFO ya se habría convertido en parsed_title/parsed_year antes de llamar a este módulo). ---
    if evidencia.parsed_year is None:
        # Año desconocido no equivale a año coincidente -- nunca se decide un match automático
        # solo por título cuando no hay año que contrastar.
        return MatchDecision(
            state=ItemState.NEEDS_REVIEW, candidate=None, score=0.0,
            reasons=("sin_ano_local_no_se_puede_confirmar_automaticamente",),
        )

    candidatos_mismo_tipo = [c for c in candidatos if c.entity_type == evidencia.entity_type]
    con_ano_coincidente = [
        c for c in candidatos_mismo_tipo
        if c.year_or_date and c.year_or_date[:4] == str(evidencia.parsed_year)
    ]
    if not con_ano_coincidente:
        return MatchDecision(
            state=ItemState.NEEDS_REVIEW, candidate=None, score=0.0,
            reasons=("ningun_candidato_con_ano_coincidente",),
        )

    puntuados = sorted(
        (
            (c, _similitud_titulo(evidencia.parsed_title, c.title_localized))
            for c in con_ano_coincidente
        ),
        key=lambda par: par[1], reverse=True,
    )
    mejor_candidato, mejor_score = puntuados[0]

    UMBRAL_CONFIANZA = 0.9
    if mejor_score < UMBRAL_CONFIANZA:
        return MatchDecision(
            state=ItemState.NEEDS_REVIEW, candidate=mejor_candidato, score=mejor_score,
            reasons=("similitud_de_titulo_insuficiente",),
        )

    # Si dos fuentes discrepan (aquí: dos candidatos con año igual y score muy parecido), no se
    # decide por mayoría -- queda a revisión humana.
    if len(puntuados) > 1 and (mejor_score - puntuados[1][1]) < 0.05:
        return MatchDecision(
            state=ItemState.NEEDS_REVIEW, candidate=mejor_candidato, score=mejor_score,
            reasons=("varios_candidatos_ambiguos_incluido_ano",),
        )

    return MatchDecision(
        state=ItemState.MATCHED, candidate=mejor_candidato, score=mejor_score,
        reasons=("titulo_y_ano_coincidentes",),
    )


def verificar_coincidencias_pelicula(items: list[InventoryItem]) -> list[dict[str, object]]:
    """Sin ningún proveedor activo todavía (docs/DECISIONS.md #5), `candidatos` siempre es una
    lista vacía -- por diseño de `decidir_coincidencia`, esto significa que TODO acaba en
    needs_review. No es un error: es el reflejo honesto de que activar un proveedor es un paso
    previo real, no simulado.

    Vive aquí (no en cli/) para que tanto la CLI como el servidor MCP lo llamen desde la MISMA
    fuente real -- son capas hermanas, ninguna debe depender de la otra (ver ARCHITECTURE.md)."""
    resultados: list[dict[str, object]] = []
    for item in items:
        info = parsear_nombre_pelicula(Path(item.current_path).stem)
        if info is None:
            resultados.append({
                "path": item.current_path, "state": "sin_interpretar",
                "score": 0.0, "reasons": ["nombre_no_interpretable"],
            })
            continue
        evidencia = LocalEvidence(
            parsed_title=info.title, parsed_year=info.year, entity_type="movie",
            external_id_namespace=info.external_id_namespace, external_id_value=info.external_id_value,
        )
        decision = decidir_coincidencia(evidencia, [])
        resultados.append({
            "path": item.current_path, "state": decision.state.value,
            "score": decision.score, "reasons": list(decision.reasons),
        })
    return resultados
