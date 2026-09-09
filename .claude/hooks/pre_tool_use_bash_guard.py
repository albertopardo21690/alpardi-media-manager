#!/usr/bin/env python3
"""Hook PreToolUse (matcher: Bash) -- bloquea rm/mv/cp/rsync --delete/find -delete SIEMPRE que se
invoquen a través de la herramienta Bash, sin excepción de ruta.

Por qué es incondicional y no intenta comprobar si la ruta está "dentro de una raíz multimedia":
la CLI real de este proyecto (`alpardi-media apply`/`rollback`) NUNCA necesita invocar estos
verbos por shell -- el motor transaccional (`transactions/engine.py`) mueve/copia/borra usando
llamadas de Python directas (`os.link`, `shutil.copy2`, etc.), nunca un subproceso `rm`/`mv`/`cp`.
Por tanto, bloquear estos verbos sin excepción en Bash no le quita a la CLI real ninguna
capacidad -- solo cierra la vía de bypass (Claude ejecutando el verbo directamente en vez de pasar
por el plan+autorización). Si Alberto necesita borrar/mover algo fuera de este proyecto, lo hace
en su propia terminal -- este hook solo gobierna lo que la propia Claude ejecuta con su Bash tool.

Límite conocido y documentado con honestidad (no oculto): esto es un análisis léxico best-effort,
no un parser de shell completo ni un sandbox -- variantes exóticas (alias, binarios renombrados,
`python3 -c "import os; os.remove(...)"`, etc.) no se detectan aquí. Es una capa de defensa más,
no la única (ver también pre_tool_use_media_write_guard.py y el propio motor transaccional, que
revalida sus propias precondiciones justo antes de escribir).

Diseño deliberado: se tokeniza el comando ENTERO de una sola vez (no se intenta primero dividirlo
en "comandos simples" por `;`/`&&`/`|`) y se busca cada verbo peligroso como TOKEN EXACTO en
cualquier posición del resultado, sin exigir que sea el primer token de un sub-comando. Una
versión anterior sí intentaba dividir por `;` antes de tokenizar, y por eso rompía con
`find ... -exec rm {} \\;`: el `;` de escape de find se confundía con un separador de comandos y
partía la cadena justo entre `-exec` y `rm`. Comprobar por "¿aparece este token en algún sitio?"
en vez de "¿aparece en posición de comando?" es deliberadamente más permisivo en la detección (más
falsos positivos posibles, p.ej. `echo rm` bloquearía) a cambio de ser mucho más difícil de romper
con la sintaxis real de shell -- el sesgo correcto para un guardarraíl de seguridad."""
from __future__ import annotations

import json
import re
import shlex
import sys

_VERBOS_SIEMPRE_BLOQUEADOS = {"rm", "mv", "cp"}


def _nombre_base(token: str) -> str:
    """`/bin/rm` y `rm` deben detectarse igual -- solo el nombre del ejecutable importa."""
    return token.rsplit("/", 1)[-1]


def _tokens_planos(command: str) -> list[str]:
    """Aplana `$(...)` y `` `...` `` quitando solo los delimitadores de sustitución de comandos
    (para que su contenido también se escanee) y tokeniza el resultado UNA sola vez con shlex --
    ver el razonamiento completo en el docstring del módulo."""
    aplanado = re.sub(r"\$\(|`|\)", " ", command)
    return [_nombre_base(t) for t in shlex.split(aplanado)]


def _motivo_bloqueo(tokens: list[str]) -> str | None:
    for verbo in _VERBOS_SIEMPRE_BLOQUEADOS:
        if verbo in tokens:
            return f"'{verbo}' está bloqueado -- usa 'alpardi-media plan'/'apply'/'rollback' para cualquier operación real"
    if "rsync" in tokens and "--delete" in tokens:
        return "'rsync --delete' está bloqueado -- usa el motor transaccional, nunca borrado directo"
    if "find" in tokens and "-delete" in tokens:
        return "'find -delete' está bloqueado -- usa el motor transaccional, nunca borrado directo"
    if "find" in tokens and "-exec" in tokens and "rm" in tokens:
        return "'find -exec rm' está bloqueado -- usa el motor transaccional, nunca borrado directo"
    return None


def main() -> int:
    try:
        entrada = json.load(sys.stdin)
    except json.JSONDecodeError:
        return 0  # no es JSON válido -- no es esta herramienta la que debe decidir nada aquí

    command = entrada.get("tool_input", {}).get("command")
    if not isinstance(command, str) or not command.strip():
        return 0

    try:
        tokens = _tokens_planos(command)
    except ValueError:
        # El comando no se pudo tokenizar de forma fiable (comillas sin cerrar, etc.) --
        # ante la duda, se bloquea: más seguro que dejar pasar algo que no se pudo analizar.
        print(
            "Bloqueado: no se pudo analizar este comando con seguridad (comillas/estructura "
            "compleja). Si de verdad hace falta, divídelo en pasos más simples o pide a Alberto "
            "que lo ejecute él mismo.",
            file=sys.stderr,
        )
        return 2

    motivo = _motivo_bloqueo(tokens)
    if motivo:
        print(f"Bloqueado: {motivo}", file=sys.stderr)
        return 2

    return 0


if __name__ == "__main__":
    sys.exit(main())
