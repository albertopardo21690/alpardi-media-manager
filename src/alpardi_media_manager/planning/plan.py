"""Generación de planes inmutables. NUNCA toca un archivo real -- solo lee el filesystem para
detectar conflictos (si el destino ya existe), nunca escribe. Aplicar un plan es responsabilidad
exclusiva de `transactions/`, y solo tras la frase de autorización exacta.
"""
from __future__ import annotations

import hashlib
import re
import unicodedata
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

# Nombres reservados de Windows -- relevantes porque el ecosistema de Alberto incluye un PC
# Windows que accede a estas rutas por red (ver docs/DECISIONS.md).
_NOMBRES_RESERVADOS_WINDOWS = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}
_CARACTERES_INVALIDOS_WINDOWS = set('<>:"|?*') | {chr(i) for i in range(32)}
_LIMITE_COMPONENTE_BYTES = 255  # límite real de ext4/btrfs por componente de ruta


@dataclass(frozen=True)
class RenameOperation:
    item_id: uuid.UUID
    source_path: str  # relativo a authorized_root
    destination_path: str
    size_bytes: int


@dataclass(frozen=True)
class PlanConflict:
    operation_index: int
    kind: str  # destination_exists | case_collision | invalid_chars | path_too_long | reserved_name
    detail: str


@dataclass(frozen=True)
class Plan:
    plan_id: str
    created_at: datetime
    inventory_hash: str  # huella del inventario contra el que se generó -- si cambia, el plan expira
    operations: tuple[RenameOperation, ...]
    conflicts: tuple[PlanConflict, ...] = field(default_factory=tuple)

    @property
    def total_bytes(self) -> int:
        return sum(op.size_bytes for op in self.operations)

    @property
    def is_safe_to_apply(self) -> bool:
        return len(self.conflicts) == 0 and len(self.operations) > 0

    def frase_autorizacion_esperada(self) -> str:
        return f"AUTORIZO APLICAR PLAN {self.plan_id} SOBRE {len(self.operations)} ELEMENTOS"


def _componente_tiene_caracteres_invalidos(componente: str) -> bool:
    return any(c in _CARACTERES_INVALIDOS_WINDOWS for c in componente)


def _componente_es_nombre_reservado(componente: str) -> bool:
    base = componente.split(".")[0].upper()
    return base in _NOMBRES_RESERVADOS_WINDOWS


def _componente_demasiado_largo(componente: str) -> bool:
    return len(componente.encode("utf-8")) > _LIMITE_COMPONENTE_BYTES


def _detectar_conflictos_de_ruta(indice: int, destino: str) -> list[PlanConflict]:
    conflictos = []
    for componente in Path(destino).parts:
        if _componente_tiene_caracteres_invalidos(componente):
            conflictos.append(PlanConflict(indice, "invalid_chars", f"'{componente}' tiene caracteres no válidos"))
        if _componente_es_nombre_reservado(componente):
            conflictos.append(PlanConflict(indice, "reserved_name", f"'{componente}' es un nombre reservado de Windows"))
        if _componente_demasiado_largo(componente):
            conflictos.append(PlanConflict(indice, "path_too_long", f"'{componente}' supera {_LIMITE_COMPONENTE_BYTES} bytes"))
    return conflictos


def generar_plan_renombrado(
    operaciones: list[RenameOperation],
    inventory_hash: str,
    authorized_root: Path,
) -> Plan:
    """`authorized_root` se usa solo para comprobar si el destino YA existe (conflicto real) --
    no se escribe nada bajo ningún concepto."""
    conflictos: list[PlanConflict] = []
    destinos_normalizados: dict[str, int] = {}
    destinos_unicode_normalizados: dict[str, int] = {}

    for i, op in enumerate(operaciones):
        conflictos.extend(_detectar_conflictos_de_ruta(i, op.destination_path))

        if (authorized_root / op.destination_path).exists():
            conflictos.append(PlanConflict(i, "destination_exists", f"{op.destination_path} ya existe"))

        # Colisión de mayúsculas/minúsculas ENTRE operaciones del propio plan (dos destinos que
        # solo difieren en mayúsculas rompen un filesystem case-insensitive).
        clave = op.destination_path.lower()
        if clave in destinos_normalizados:
            conflictos.append(PlanConflict(
                i, "case_collision",
                f"'{op.destination_path}' colisiona con la operación #{destinos_normalizados[clave]}",
            ))
        else:
            destinos_normalizados[clave] = i

        # Colisión Unicode: dos rutas visualmente idénticas pero con normalización distinta
        # (NFC vs NFD -- diferencia real entre cómo macOS/algunos NAS y Linux codifican tildes)
        # deben tratarse como el mismo destino, no como dos destinos distintos.
        clave_nfc = unicodedata.normalize("NFC", op.destination_path).lower()
        if clave_nfc in destinos_unicode_normalizados and destinos_unicode_normalizados[clave_nfc] != i:
            conflictos.append(PlanConflict(
                i, "unicode_collision",
                f"'{op.destination_path}' normaliza igual que la operación #{destinos_unicode_normalizados[clave_nfc]} (NFC/NFD)",
            ))
        else:
            destinos_unicode_normalizados[clave_nfc] = i

    ahora = datetime.now(UTC)
    plan_id_base = f"plan_{ahora.strftime('%Y%m%d')}"
    huella = hashlib.sha256(
        (inventory_hash + "".join(op.source_path + op.destination_path for op in operaciones)).encode()
    ).hexdigest()[:8]

    return Plan(
        plan_id=f"{plan_id_base}_{huella}",
        created_at=ahora,
        inventory_hash=inventory_hash,
        operations=tuple(operaciones),
        conflicts=tuple(conflictos),
    )


_RE_AUTORIZACION = re.compile(r"^AUTORIZO APLICAR PLAN (\S+) SOBRE (\d+) ELEMENTOS$")


def verificar_frase_autorizacion(frase: str, plan: Plan, inventory_hash_actual: str) -> tuple[bool, str]:
    """Nunca basta con que el texto 'se parezca' -- debe coincidir EXACTAMENTE con el plan_id y
    el número real de elementos, y el inventario no debe haber cambiado desde que se generó el
    plan (si cambió, el plan expira -- regla explícita del encargo)."""
    m = _RE_AUTORIZACION.match(frase.strip())
    if not m:
        return False, "La frase no tiene el formato exacto 'AUTORIZO APLICAR PLAN <id> SOBRE <n> ELEMENTOS'"
    plan_id_frase, n_frase = m.group(1), int(m.group(2))
    if plan_id_frase != plan.plan_id:
        return False, f"El plan_id de la frase ({plan_id_frase}) no coincide con el plan real ({plan.plan_id})"
    if n_frase != len(plan.operations):
        return False, f"La frase dice {n_frase} elementos, el plan tiene {len(plan.operations)}"
    if inventory_hash_actual != plan.inventory_hash:
        return False, "El inventario ha cambiado desde que se generó este plan -- el plan ha expirado"
    if not plan.is_safe_to_apply:
        return False, f"El plan tiene {len(plan.conflicts)} conflicto(s) sin resolver -- no se puede aplicar"
    return True, "autorización válida"
