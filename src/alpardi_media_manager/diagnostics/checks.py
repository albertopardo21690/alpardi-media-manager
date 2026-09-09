"""Comprobaciones individuales de `doctor`. Cada una es una función pura de I/O aislado, para que
se puedan probar con dobles de prueba en vez de necesitar el sistema real en cada test."""
from __future__ import annotations

import shutil
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

Runner = Callable[..., subprocess.CompletedProcess[str]]


class CheckStatus(StrEnum):
    OK = "ok"
    WARN = "warn"
    ERROR = "error"


@dataclass(frozen=True)
class CheckResult:
    name: str
    status: CheckStatus
    detail: str


def check_python_version() -> CheckResult:
    # pyproject.toml ya exige requires-python >=3.14,<3.15 -- si esto se ejecuta, ya se cumple.
    version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    return CheckResult("python", CheckStatus.OK, f"Python {version}")


def check_binary_present(nombre: str, comando: str | None = None) -> CheckResult:
    """Comprueba si un binario externo está en PATH -- ffprobe, mediainfo, etc."""
    ruta = shutil.which(comando or nombre)
    if ruta:
        return CheckResult(nombre, CheckStatus.OK, ruta)
    return CheckResult(nombre, CheckStatus.WARN, "no encontrado en PATH")


def check_plex_reachable(
    base_url: str,
    token: str,
    *,
    runner: Runner = subprocess.run,
    timeout_s: int = 10,
) -> CheckResult:
    """Solo lectura: pide la raíz de la API de Plex. `runner` es inyectable para tests --
    nunca se llama a la red real desde un test unitario."""
    if not token:
        return CheckResult("plex", CheckStatus.ERROR, "sin token configurado")
    try:
        r = runner(
            ["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}",
             f"{base_url}/?X-Plex-Token={token}"],
            capture_output=True, text=True, timeout=timeout_s,
        )
    except subprocess.TimeoutExpired:
        return CheckResult("plex", CheckStatus.ERROR, f"timeout tras {timeout_s}s")
    codigo = (r.stdout or "").strip()
    if codigo == "200":
        return CheckResult("plex", CheckStatus.OK, f"alcanzable en {base_url}")
    return CheckResult("plex", CheckStatus.ERROR, f"HTTP {codigo or 'sin respuesta'} desde {base_url}")


def check_nas_ssh_reachable(
    ssh_host: str,
    *,
    runner: Runner = subprocess.run,
    timeout_s: int = 10,
) -> CheckResult:
    """Solo lectura: un `echo` remoto por SSH, nada más -- nunca monta nada.

    `stdin=DEVNULL` es necesario: sin fijarlo, ssh hereda el stdin del proceso Python y puede
    quedarse esperando una entrada interactiva que nunca llega, agotando el timeout aunque el NAS
    responda al instante (bug real encontrado al ejecutar el test de integración: `ssh` a mano
    tardaba <1s, pero vía subprocess.run sin stdin fijado, siempre agotaba el timeout)."""
    try:
        r = runner(
            ["ssh", "-o", f"ConnectTimeout={timeout_s}", "-o", "BatchMode=yes", ssh_host, "echo ok"],
            capture_output=True, text=True, timeout=timeout_s + 5, stdin=subprocess.DEVNULL,
        )
    except subprocess.TimeoutExpired:
        return CheckResult("nas_ssh", CheckStatus.ERROR, f"timeout tras {timeout_s}s")
    if r.returncode == 0 and "ok" in (r.stdout or ""):
        return CheckResult("nas_ssh", CheckStatus.OK, f"SSH a {ssh_host} funciona")
    return CheckResult("nas_ssh", CheckStatus.ERROR, f"SSH a {ssh_host} falló: {(r.stderr or '').strip()[:200]}")


def run_all_checks(*, plex_base_url: str, plex_token: str, nas_ssh_host: str) -> list[CheckResult]:
    return [
        check_python_version(),
        check_binary_present("ffprobe"),
        check_binary_present("ffmpeg"),
        check_binary_present("mediainfo"),
        check_plex_reachable(plex_base_url, plex_token),
        check_nas_ssh_reachable(nas_ssh_host),
    ]
