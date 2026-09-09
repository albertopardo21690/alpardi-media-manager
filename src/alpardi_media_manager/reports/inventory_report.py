"""Exporta un inventario de elementos en Markdown, JSON y CSV -- los tres formatos que exige el
encargo, reproducibles (misma entrada, misma salida byte a byte)."""
from __future__ import annotations

import csv
import io
import json

from alpardi_media_manager.domain.models import InventoryItem


def _fila(item: InventoryItem) -> dict[str, str]:
    return {
        "id": str(item.id),
        "library_id": item.library_id,
        "path": item.current_path,
        "content_type": item.content_type.value,
        "state": item.state.value,
        "size_bytes": str(item.fingerprint.size_bytes),
        "extension": item.extension,
    }


_COLUMNAS = ["id", "library_id", "path", "content_type", "state", "size_bytes", "extension"]


def inventario_a_markdown(items: list[InventoryItem]) -> str:
    lineas = [f"# Inventario ({len(items)} elementos)", ""]
    if not items:
        lineas.append("_Sin elementos._")
        return "\n".join(lineas) + "\n"
    lineas.append("| " + " | ".join(_COLUMNAS) + " |")
    lineas.append("|" + "---|" * len(_COLUMNAS))
    for item in items:
        fila = _fila(item)
        lineas.append("| " + " | ".join(fila[c] for c in _COLUMNAS) + " |")
    return "\n".join(lineas) + "\n"


def inventario_a_json(items: list[InventoryItem]) -> str:
    datos = {"total": len(items), "items": [_fila(item) for item in items]}
    return json.dumps(datos, indent=2, ensure_ascii=False)


def inventario_a_csv(items: list[InventoryItem]) -> str:
    buffer = io.StringIO()
    escritor = csv.DictWriter(buffer, fieldnames=_COLUMNAS)
    escritor.writeheader()
    for item in items:
        escritor.writerow(_fila(item))
    return buffer.getvalue()
