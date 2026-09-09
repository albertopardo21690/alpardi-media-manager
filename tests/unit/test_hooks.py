"""Prueba de regresión de los hooks PreToolUse -- los invoca EXACTAMENTE como lo haría Claude
Code de verdad (JSON por stdin, veredicto por código de salida), no simula su lógica interna.
Esto es lo que evitó que un bug real (`find -exec rm {} \\;` no se bloqueaba por una división
ingenua del comando antes de tokenizar) pasara desapercibido -- ver el docstring del propio hook.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

_HOOKS_DIR = Path(__file__).resolve().parents[2] / ".claude" / "hooks"
_BASH_GUARD = _HOOKS_DIR / "pre_tool_use_bash_guard.py"
_MEDIA_GUARD = _HOOKS_DIR / "pre_tool_use_media_write_guard.py"


def _ejecutar_hook(ruta: Path, payload: dict[str, object]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(ruta)],
        input=json.dumps(payload), capture_output=True, text=True, timeout=10, check=False,
    )


# --- guard de Bash ------------------------------------------------------------------------------

@pytest.mark.parametrize("command", [
    "rm /opt/alpardi-media-manager/foo.mkv",
    "/bin/mv a.txt b.txt",
    "cp origen.mkv destino.mkv",
    "rsync -av --delete /src/ /dst/",
    'find /tmp -name "*.tmp" -delete',
    'find /tmp -name "*.tmp" -exec rm {} \\;',  # terminador \; -- el caso real que se rompía
    "find /tmp -exec rm {} +",  # terminador + -- forma alternativa, sin backslash
    "cd /tmp && rm foo.txt",
    "echo $(rm -rf /tmp/x)",
])
def test_bash_guard_bloquea_comandos_peligrosos(command: str):
    r = _ejecutar_hook(_BASH_GUARD, {"tool_name": "Bash", "tool_input": {"command": command}})
    assert r.returncode == 2, f"debía bloquear '{command}', stderr={r.stderr!r}"
    assert r.stderr.strip()


@pytest.mark.parametrize("command", [
    "git status --short",
    "./.venv/bin/pytest -q",
    'echo "no uses rm nunca"',  # 'rm' solo aparece dentro de una cadena citada, no como token
    './.venv/bin/alpardi-media apply --plan p.json --root /x --library-id l --content-type movie --authorize "AUTORIZO..."',
])
def test_bash_guard_permite_comandos_normales(command: str):
    r = _ejecutar_hook(_BASH_GUARD, {"tool_name": "Bash", "tool_input": {"command": command}})
    assert r.returncode == 0, f"no debía bloquear '{command}', stderr={r.stderr!r}"


def test_bash_guard_json_invalido_no_bloquea():
    r = subprocess.run(
        [sys.executable, str(_BASH_GUARD)], input="no es json", capture_output=True, text=True, timeout=10, check=False,
    )
    assert r.returncode == 0


def test_bash_guard_sin_tool_input_command_no_bloquea():
    r = _ejecutar_hook(_BASH_GUARD, {"tool_name": "Read", "tool_input": {"file_path": "x.py"}})
    assert r.returncode == 0


# --- guard de escritura sobre extensiones multimedia --------------------------------------------

@pytest.mark.parametrize("file_path", [
    "/data/Peliculas/pelicula.mkv",
    "/data/subs/pelicula.es.srt",
    "/data/x.MP4",  # insensible a mayúsculas/minúsculas
])
def test_media_guard_bloquea_extensiones_protegidas(file_path: str):
    r = _ejecutar_hook(_MEDIA_GUARD, {"tool_name": "Write", "tool_input": {"file_path": file_path}})
    assert r.returncode == 2, f"debía bloquear '{file_path}', stderr={r.stderr!r}"
    assert r.stderr.strip()


@pytest.mark.parametrize("file_path", [
    "/opt/alpardi-media-manager/src/foo.py",
    "/opt/alpardi-media-manager/docs/ARCHITECTURE.md",
    "/opt/alpardi-media-manager/config/providers.yaml",
])
def test_media_guard_permite_codigo_y_texto(file_path: str):
    r = _ejecutar_hook(_MEDIA_GUARD, {"tool_name": "Edit", "tool_input": {"file_path": file_path}})
    assert r.returncode == 0, f"no debía bloquear '{file_path}', stderr={r.stderr!r}"


def test_media_guard_json_invalido_no_bloquea():
    r = subprocess.run(
        [sys.executable, str(_MEDIA_GUARD)], input="no es json", capture_output=True, text=True, timeout=10, check=False,
    )
    assert r.returncode == 0
