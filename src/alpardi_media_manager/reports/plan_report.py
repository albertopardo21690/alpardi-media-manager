"""Informe de un `Plan` -- vista previa legible (Markdown) y máquina (JSON), tal como exige el
encargo antes de pedir la frase de autorización exacta. Puramente de lectura/formateo -- no toca
ningún archivo, no decide nada, solo describe lo que el plan YA contiene.
"""
from __future__ import annotations

import json
from collections import Counter

from alpardi_media_manager.planning.plan import Plan


def _formato_bytes(n: int) -> str:
    valor = float(n)
    for unidad in ("B", "KB", "MB", "GB", "TB"):
        if valor < 1024 or unidad == "TB":
            return f"{valor:.1f} {unidad}" if unidad != "B" else f"{int(valor)} B"
        valor /= 1024
    return f"{valor:.1f} TB"  # inalcanzable en la práctica, pero explícito en vez de un bucle infinito


def plan_a_markdown(plan: Plan) -> str:
    """Vista previa legible por un humano -- exactamente el contenido que el encargo pide mostrar
    antes de autorizar: número de elementos/operaciones, rutas origen->destino, conflictos por
    tipo, bytes totales, y cómo revertir si algo sale mal."""
    lineas = [f"# Plan {plan.plan_id}", ""]
    lineas.append(f"- **Operaciones:** {len(plan.operations)}")
    lineas.append(f"- **Bytes totales que se moverán/copiarán:** {_formato_bytes(plan.total_bytes)} ({plan.total_bytes} bytes)")
    lineas.append(f"- **Generado contra el inventario:** `{plan.inventory_hash}`")
    lineas.append(f"- **¿Seguro para aplicar?** {'✅ Sí, sin conflictos' if plan.is_safe_to_apply else '❌ No -- hay conflictos sin resolver, ver abajo'}")
    lineas.append("")

    if plan.conflicts:
        lineas.append(f"## Conflictos ({len(plan.conflicts)})")
        lineas.append("")
        conteo = Counter(c.kind for c in plan.conflicts)
        for tipo, n in sorted(conteo.items(), key=lambda kv: -kv[1]):
            lineas.append(f"- **{tipo}**: {n}")
        lineas.append("")
        lineas.append("| # operación | tipo | detalle |")
        lineas.append("|---|---|---|")
        for c in plan.conflicts:
            lineas.append(f"| {c.operation_index} | {c.kind} | {c.detail} |")
        lineas.append("")

    lineas.append("## Operaciones (origen → destino)")
    lineas.append("")
    lineas.append("| # | origen | destino | bytes |")
    lineas.append("|---|---|---|---|")
    for i, op in enumerate(plan.operations):
        lineas.append(f"| {i} | `{op.source_path}` | `{op.destination_path}` | {_formato_bytes(op.size_bytes)} |")
    lineas.append("")

    lineas.append("## Cómo autorizar")
    lineas.append("")
    lineas.append("Este plan solo se aplica con la frase EXACTA (letra por letra):")
    lineas.append("")
    lineas.append(f"    {plan.frase_autorizacion_esperada()}")
    lineas.append("")
    lineas.append(
        "Si el inventario cambia entre ahora y ese momento, este plan caduca automáticamente y "
        "hay que generar uno nuevo -- no se puede forzar con la frase antigua."
    )
    lineas.append("")
    lineas.append("## Cómo revertir tras aplicar")
    lineas.append("")
    lineas.append(
        "Cada operación aplicada queda registrada en un journal persistente. Para deshacer toda "
        "la transacción una vez aplicada, usar `revertir_transaccion(transaction_id, authorized_root)` "
        "con el `transaction_id` que devuelva la aplicación (no el `plan_id` de este documento)."
    )
    return "\n".join(lineas) + "\n"


def plan_a_json(plan: Plan) -> str:
    """Formato máquina, reproducible -- mismo contenido que la versión Markdown, sin prosa."""
    datos = {
        "plan_id": plan.plan_id,
        "created_at": plan.created_at.isoformat(),
        "inventory_hash": plan.inventory_hash,
        "total_operations": len(plan.operations),
        "total_bytes": plan.total_bytes,
        "is_safe_to_apply": plan.is_safe_to_apply,
        "authorization_phrase": plan.frase_autorizacion_esperada(),
        "operations": [
            {
                "index": i,
                "item_id": str(op.item_id),
                "source_path": op.source_path,
                "destination_path": op.destination_path,
                "size_bytes": op.size_bytes,
            }
            for i, op in enumerate(plan.operations)
        ],
        "conflicts": [
            {"operation_index": c.operation_index, "kind": c.kind, "detail": c.detail}
            for c in plan.conflicts
        ],
    }
    return json.dumps(datos, indent=2, ensure_ascii=False)
