"""Informe legible de lo que pasó de verdad al aplicar o revertir un plan -- el formato que exige
el encargo tras cada operación: qué se pidió, qué se verificó, qué cambió, qué no, conteos, y la
siguiente decisión segura. Puramente de lectura -- no repite ninguna operación, solo describe un
`TransactionResult`/`RollbackResult` ya devuelto por transactions/engine.py."""
from __future__ import annotations

from collections import Counter

from alpardi_media_manager.transactions.engine import RollbackResult, TransactionResult


def resultado_aplicacion_a_markdown(resultado: TransactionResult) -> str:
    if not resultado.autorizada:
        return (
            f"# Plan {resultado.plan_id} -- NO aplicado\n\n"
            f"**Motivo:** {resultado.motivo_rechazo}\n\n"
            "No se ha tocado ningún archivo. No se ha creado ningún journal.\n"
        )

    conteo = Counter(op.status.value for op in resultado.operations)
    lineas = [
        f"# Transacción {resultado.transaction_id}",
        "",
        f"- **Plan:** {resultado.plan_id}",
        f"- **Estado final:** {resultado.estado.value if resultado.estado else '(desconocido)'}",
        f"- **Journal:** `{resultado.journal_path}`",
        "",
        "## Conteo por estado",
        "",
    ]
    for estado, n in sorted(conteo.items(), key=lambda kv: -kv[1]):
        lineas.append(f"- **{estado}**: {n}")
    lineas.append("")

    lineas.append("## Detalle por operación")
    lineas.append("")
    lineas.append("| # | origen | destino | estado | detalle |")
    lineas.append("|---|---|---|---|---|")
    for op in resultado.operations:
        detalle = (op.detail or "").replace("|", "\\|")
        lineas.append(f"| {op.index} | `{op.source_path}` | `{op.destination_path}` | {op.status.value} | {detalle} |")
    lineas.append("")

    lineas.append("## Siguiente decisión segura")
    lineas.append("")
    if resultado.estado is not None and resultado.estado.value == "completada":
        lineas.append(
            "Todas las operaciones se aplicaron y verificaron (o quedaron en un estado que no "
            "implica pérdida de datos, como conflicto o revisión manual). No hace falta ninguna "
            "acción adicional salvo revisar manualmente las que quedaron en "
            "`requiere_revision_manual`, si las hay."
        )
    else:
        lineas.append(
            f"El plan se detuvo antes de terminar. Revisar el journal (`{resultado.journal_path}`) "
            "para decidir si se reintenta desde el punto de fallo con un plan nuevo, o si se "
            f"revierte lo ya aplicado con revertir_transaccion('{resultado.transaction_id}', ...)."
        )
    return "\n".join(lineas) + "\n"


def resultado_reversion_a_markdown(resultado: RollbackResult) -> str:
    if not resultado.encontrada:
        return (
            f"# Reversión de {resultado.transaction_id} -- transacción no encontrada\n\n"
            "No existe ningún journal con ese transaction_id bajo la raíz autorizada indicada.\n"
        )

    conteo = Counter(op.status.value for op in resultado.operations)
    lineas = [
        f"# Reversión de {resultado.transaction_id}",
        "",
        f"- **¿Reversión completa?** {'✅ Sí' if resultado.completa else '⚠️ No -- ver detalle abajo'}",
        f"- **Operaciones revertidas intentadas:** {len(resultado.operations)}",
        "",
        "## Conteo por estado",
        "",
    ]
    for estado, n in sorted(conteo.items(), key=lambda kv: -kv[1]):
        lineas.append(f"- **{estado}**: {n}")
    lineas.append("")

    lineas.append("## Detalle por operación")
    lineas.append("")
    lineas.append("| # | origen (destino de la aplicación) | destino (origen original) | estado | detalle |")
    lineas.append("|---|---|---|---|---|")
    for op in resultado.operations:
        detalle = (op.detail or "").replace("|", "\\|")
        lineas.append(f"| {op.index} | `{op.destination_path}` | `{op.source_path}` | {op.status.value} | {detalle} |")
    lineas.append("")

    if not resultado.completa:
        lineas.append(
            "**Atención:** una o más operaciones no se pudieron revertir automáticamente -- "
            "revisar cada una marcada `error_reversion` o `requiere_revision_manual` a mano antes "
            "de dar la reversión por terminada."
        )
    return "\n".join(lineas) + "\n"
