"""Máquina de estados de un elemento de inventario.

Estados exactos exigidos por el encargo (sección "Arquitectura mínima requerida"): discovered,
parsed, matched, needs_review, planned, applied, verified, failed, rolled_back.
"""
from __future__ import annotations

from enum import StrEnum


class ItemState(StrEnum):
    DISCOVERED = "discovered"
    PARSED = "parsed"
    MATCHED = "matched"
    NEEDS_REVIEW = "needs_review"
    PLANNED = "planned"
    APPLIED = "applied"
    VERIFIED = "verified"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"


# Transiciones permitidas. No es un requisito literal del encargo, pero sin esto cualquier código
# podría saltar de discovered a applied sin pasar por planned -- justo lo que las reglas de
# "ninguna mutación sin plan y autorización" prohíben. Se valida explícitamente, no se confía solo
# en la disciplina del código que la llama.
_TRANSICIONES: dict[ItemState, frozenset[ItemState]] = {
    ItemState.DISCOVERED: frozenset({ItemState.PARSED, ItemState.FAILED}),
    ItemState.PARSED: frozenset({ItemState.MATCHED, ItemState.NEEDS_REVIEW, ItemState.FAILED}),
    ItemState.MATCHED: frozenset({ItemState.PLANNED, ItemState.NEEDS_REVIEW, ItemState.FAILED}),
    ItemState.NEEDS_REVIEW: frozenset({ItemState.MATCHED, ItemState.PLANNED, ItemState.FAILED}),
    ItemState.PLANNED: frozenset({ItemState.APPLIED, ItemState.NEEDS_REVIEW, ItemState.FAILED}),
    ItemState.APPLIED: frozenset({ItemState.VERIFIED, ItemState.ROLLED_BACK, ItemState.FAILED}),
    ItemState.VERIFIED: frozenset(),  # terminal en el sentido de éxito
    ItemState.FAILED: frozenset({ItemState.PLANNED, ItemState.ROLLED_BACK}),  # reintentable
    ItemState.ROLLED_BACK: frozenset(),  # terminal
}


def transicion_permitida(origen: ItemState, destino: ItemState) -> bool:
    return destino in _TRANSICIONES.get(origen, frozenset())
