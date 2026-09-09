"""Lectura de solo lectura del estado configurado de los proveedores (`config/providers.yaml`) --
nunca hace tráfico de red, nunca lee un secreto real (solo si existe una `credential_ref`, no su
valor). Sirve para que Alberto vea de un vistazo qué está habilitado sin leer el YAML a mano.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

NOMBRE_PLANTILLA = "providers.example.yaml"


@dataclass(frozen=True)
class EstadoProveedor:
    provider: str
    enabled: bool
    has_credential_ref: bool


@dataclass(frozen=True)
class EstadoProveedores:
    config_path: Path
    is_template: bool
    providers: tuple[EstadoProveedor, ...]


def _resolver_ruta_config(ruta_solicitada: Path) -> tuple[Path, bool]:
    """Si `ruta_solicitada` no existe, cae a la plantilla `providers.example.yaml` que vive en el
    mismo directorio -- nunca inventa datos, solo deja claro que lo mostrado no es la
    configuración real activa."""
    if ruta_solicitada.exists():
        return ruta_solicitada, False

    plantilla = ruta_solicitada.parent / NOMBRE_PLANTILLA
    if ruta_solicitada.name != NOMBRE_PLANTILLA and plantilla.exists():
        return plantilla, True

    return ruta_solicitada, False


def leer_estado_proveedores(ruta_solicitada: Path) -> EstadoProveedores:
    ruta, es_plantilla = _resolver_ruta_config(ruta_solicitada)
    if not ruta.exists():
        raise FileNotFoundError(f"No existe ni '{ruta_solicitada}' ni una plantilla junto a ella")

    datos: dict[str, Any] = yaml.safe_load(ruta.read_text(encoding="utf-8")) or {}
    bloque_proveedores: dict[str, Any] = datos.get("providers", {})

    proveedores = tuple(
        EstadoProveedor(
            provider=nombre,
            enabled=bool(cfg.get("enabled", False)),
            has_credential_ref=bool(cfg.get("credential_ref") or cfg.get("api_key_ref")),
        )
        for nombre, cfg in bloque_proveedores.items()
        if isinstance(cfg, dict)
    )
    return EstadoProveedores(config_path=ruta, is_template=es_plantilla, providers=proveedores)
