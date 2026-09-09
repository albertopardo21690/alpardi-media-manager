#!/usr/bin/env python3
"""Hook PreToolUse (matcher: Write|Edit) -- bloquea que las herramientas Write/Edit de Claude
Code toquen directamente un archivo con extensión multimedia (vídeo, audio, imagen o subtítulo),
sin importar la ruta.

Por qué por extensión y no por "raíz multimedia": todavía no existe ningún registro real de
raíces de biblioteca autorizadas (Fase 5 -- piloto real -- sigue pendiente), así que comprobar
"¿está esta ruta dentro de una raíz multimedia configurada?" no tiene ninguna configuración real
contra la que comprobar hoy y sería, en la práctica, un no-op. La invariante real que SÍ puede
imponerse hoy, con o sin piloto: las herramientas Write/Edit de Claude Code son para código y
texto -- el contenido real de un archivo multimedia (o su renombrado/movimiento) es SIEMPRE
responsabilidad exclusiva del motor transaccional (transactions/engine.py), nunca de una edición
de texto. Esto se cumple sin necesitar saber dónde vive la biblioteca real de Alberto.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_EXTENSIONES_PROTEGIDAS = {
    # Vídeo
    ".mkv", ".mp4", ".avi", ".mov", ".m4v", ".ts", ".wmv", ".flv", ".webm", ".mpg", ".mpeg", ".vob", ".iso",
    # Audio
    ".mp3", ".flac", ".wav", ".m4a", ".aac", ".ogg", ".wma", ".ape",
    # Imagen / arte local
    ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tiff", ".webp",
    # Subtítulos
    ".srt", ".ass", ".ssa", ".sub", ".idx", ".vtt",
}


def main() -> int:
    try:
        entrada = json.load(sys.stdin)
    except json.JSONDecodeError:
        return 0

    file_path = entrada.get("tool_input", {}).get("file_path")
    if not isinstance(file_path, str) or not file_path.strip():
        return 0

    extension = Path(file_path).suffix.lower()
    if extension in _EXTENSIONES_PROTEGIDAS:
        print(
            f"Bloqueado: '{file_path}' tiene extensión multimedia protegida ({extension}). "
            "Write/Edit son para código y texto -- cualquier operación real sobre un archivo "
            "multimedia (renombrar, mover, generar NFO/arte) pasa siempre por el motor "
            "transaccional (alpardi-media plan/apply), nunca por una edición de texto directa.",
            file=sys.stderr,
        )
        return 2

    return 0


if __name__ == "__main__":
    sys.exit(main())
