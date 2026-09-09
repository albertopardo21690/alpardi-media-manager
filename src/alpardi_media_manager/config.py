"""Resolución mínima de configuración para los comandos de solo lectura de esta fase.

No es el sistema de configuración final (eso vendrá con config/config.yaml real + credential_ref
completo) -- de momento solo resuelve lo necesario para que `doctor` funcione de verdad contra el
Plex y el NAS reales, reutilizando el token ya existente sin duplicarlo.

Vive en la raíz del paquete (no en `cli/`) porque tanto la CLI como el servidor MCP lo necesitan
por igual -- son capas hermanas, ninguna debe depender de la otra (ver ARCHITECTURE.md)."""
from __future__ import annotations

import os
from pathlib import Path

DEFAULT_PLEX_TOKEN_FILE = Path("/root/.config/alpardios/plex.env")
DEFAULT_PLEX_BASE_URL = "http://100.75.202.28:32400"
DEFAULT_NAS_SSH_HOST = "NASAlpardimedia"


def leer_plex_token(ruta: Path = DEFAULT_PLEX_TOKEN_FILE) -> str:
    """Lee PLEX_TOKEN=... del fichero ya existente. Nunca se imprime el valor devuelto -- solo
    se usa para construir una petición HTTP."""
    if not ruta.exists():
        return ""
    for linea in ruta.read_text().splitlines():
        if linea.startswith("PLEX_TOKEN="):
            return linea.split("=", 1)[1].strip()
    return ""


def plex_base_url() -> str:
    return os.environ.get("ALPARDI_MEDIA_PLEX_BASE_URL", DEFAULT_PLEX_BASE_URL)


def nas_ssh_host() -> str:
    return os.environ.get("ALPARDI_MEDIA_NAS_SSH_HOST", DEFAULT_NAS_SSH_HOST)
