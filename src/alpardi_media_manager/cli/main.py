"""Punto de entrada de la CLI. Todos los comandos de consulta soportan salida humana y --json
(regla explícita del encargo). Los comandos con efectos no existen todavía en esta fase --
`doctor` es puramente de solo lectura/diagnóstico."""
from __future__ import annotations

import argparse
import json
import sys

from alpardi_media_manager.cli.checks import CheckStatus, run_all_checks
from alpardi_media_manager.cli.config import leer_plex_token, nas_ssh_host, plex_base_url

_SIMBOLO = {CheckStatus.OK: "✓", CheckStatus.WARN: "⚠", CheckStatus.ERROR: "✗"}


def cmd_doctor(as_json: bool) -> int:
    resultados = run_all_checks(
        plex_base_url=plex_base_url(),
        plex_token=leer_plex_token(),
        nas_ssh_host=nas_ssh_host(),
    )

    if as_json:
        print(json.dumps(
            [{"name": r.name, "status": r.status.value, "detail": r.detail} for r in resultados],
            indent=2, ensure_ascii=False,
        ))
    else:
        print("alpardi-media doctor\n")
        for r in resultados:
            print(f"  {_SIMBOLO[r.status]}  {r.name:<12} {r.detail}")

    return 1 if any(r.status == CheckStatus.ERROR for r in resultados) else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="alpardi-media")
    sub = parser.add_subparsers(dest="command", required=True)

    p_doctor = sub.add_parser("doctor", help="Diagnóstico de entorno (solo lectura)")
    p_doctor.add_argument("--json", action="store_true", dest="as_json")

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "doctor":
        return cmd_doctor(args.as_json)
    return 2  # inalcanzable mientras solo exista "doctor", pero explícito en vez de silencioso


if __name__ == "__main__":
    sys.exit(main())
