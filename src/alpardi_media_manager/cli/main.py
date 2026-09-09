"""Punto de entrada de la CLI. Todos los comandos de consulta soportan salida humana y --json
(regla explícita del encargo). Los comandos con efectos que ya existen (`rollback`) solo actúan
sobre transacciones YA aplicadas -- ningún comando de esta CLI puede iniciar una escritura nueva
sobre medios todavía (eso necesita primero `plan`+`apply`, pendientes de un formato de plan en
disco reproducible, ver docs/ARCHITECTURE.md)."""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from alpardi_media_manager.cli.checks import CheckStatus, run_all_checks
from alpardi_media_manager.cli.config import leer_plex_token, nas_ssh_host, plex_base_url
from alpardi_media_manager.domain.models import ContentType
from alpardi_media_manager.inventory.scanner import escanear_directorio
from alpardi_media_manager.plex.client import PlexClient
from alpardi_media_manager.reports.inventory_report import (
    inventario_a_csv,
    inventario_a_json,
    inventario_a_markdown,
)
from alpardi_media_manager.reports.transaction_report import resultado_reversion_a_markdown
from alpardi_media_manager.transactions.engine import revertir_transaccion

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


async def _plex_inspect_async() -> list[dict[str, str]]:
    token = leer_plex_token()
    if not token:
        raise RuntimeError("Sin token de Plex disponible (ver docs/SECURITY.md)")
    async with PlexClient(plex_base_url(), token) as cliente:
        bibliotecas = await cliente.listar_bibliotecas()
    return [
        {"key": b.key, "type": b.type, "title": b.title, "agent": b.agent, "scanner": b.scanner, "language": b.language}
        for b in bibliotecas
    ]


def cmd_plex_inspect(as_json: bool) -> int:
    try:
        filas = asyncio.run(_plex_inspect_async())
    except (RuntimeError, OSError) as e:
        print(f"✗ No se pudo consultar Plex: {e}", file=sys.stderr)
        return 1

    if as_json:
        print(json.dumps(filas, indent=2, ensure_ascii=False))
    else:
        print(f"{len(filas)} bibliotecas en Plex\n")
        for f in filas:
            print(f"  [{f['key']:>3}] {f['title']:<35} {f['type']:<8} agente={f['agent']}")
    return 0


def cmd_inventory_scan(root: str, library_id: str, content_type: str, as_json: bool) -> int:
    try:
        tipo = ContentType(content_type)
    except ValueError:
        tipos_validos = ", ".join(t.value for t in ContentType)
        print(f"✗ content-type inválido: '{content_type}'. Válidos: {tipos_validos}", file=sys.stderr)
        return 1

    ruta = Path(root)
    if not ruta.is_dir():
        print(f"✗ La raíz no existe o no es un directorio: {ruta}", file=sys.stderr)
        return 1

    items = escanear_directorio(ruta, library_id=library_id, content_type=tipo)

    if as_json:
        print(inventario_a_json(items))
    else:
        print(inventario_a_markdown(items))
    return 0


def cmd_export(root: str, library_id: str, content_type: str, formato: str, salida: str | None) -> int:
    try:
        tipo = ContentType(content_type)
    except ValueError:
        tipos_validos = ", ".join(t.value for t in ContentType)
        print(f"✗ content-type inválido: '{content_type}'. Válidos: {tipos_validos}", file=sys.stderr)
        return 1

    ruta = Path(root)
    if not ruta.is_dir():
        print(f"✗ La raíz no existe o no es un directorio: {ruta}", file=sys.stderr)
        return 1

    items = escanear_directorio(ruta, library_id=library_id, content_type=tipo)

    generadores = {"md": inventario_a_markdown, "json": inventario_a_json, "csv": inventario_a_csv}
    contenido = generadores[formato](items)

    if salida:
        Path(salida).write_text(contenido, encoding="utf-8")
        print(f"✓ Exportado a {salida} ({len(items)} elementos)")
    else:
        print(contenido)
    return 0


def cmd_rollback(transaction_id: str, root: str, as_json: bool) -> int:
    resultado = revertir_transaccion(transaction_id, Path(root))

    if as_json:
        print(json.dumps({
            "transaction_id": resultado.transaction_id,
            "encontrada": resultado.encontrada,
            "completa": resultado.completa,
            "operations": [
                {"index": op.index, "status": op.status.value, "detail": op.detail}
                for op in resultado.operations
            ],
        }, indent=2, ensure_ascii=False))
    else:
        print(resultado_reversion_a_markdown(resultado))

    if not resultado.encontrada:
        return 1
    return 0 if resultado.completa else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="alpardi-media")
    sub = parser.add_subparsers(dest="command", required=True)

    p_doctor = sub.add_parser("doctor", help="Diagnóstico de entorno (solo lectura)")
    p_doctor.add_argument("--json", action="store_true", dest="as_json")

    p_plex = sub.add_parser("plex", help="Operaciones de solo lectura sobre Plex")
    sub_plex = p_plex.add_subparsers(dest="plex_command", required=True)
    p_plex_inspect = sub_plex.add_parser("inspect", help="Lista las bibliotecas reales de Plex")
    p_plex_inspect.add_argument("--json", action="store_true", dest="as_json")

    p_inventory = sub.add_parser("inventory", help="Operaciones de inventario (solo lectura)")
    sub_inventory = p_inventory.add_subparsers(dest="inventory_command", required=True)
    p_scan = sub_inventory.add_parser("scan", help="Escanea una raíz de biblioteca (nunca escribe nada)")
    p_scan.add_argument("root", help="Ruta de la raíz de biblioteca a escanear")
    p_scan.add_argument("--library-id", required=True)
    p_scan.add_argument("--content-type", required=True, help="movie|tv_show|tv_episode|... (ver domain/models.py)")
    p_scan.add_argument("--json", action="store_true", dest="as_json")

    p_export = sub.add_parser("export", help="Escanea y exporta un inventario en md/json/csv")
    p_export.add_argument("root")
    p_export.add_argument("--library-id", required=True)
    p_export.add_argument("--content-type", required=True)
    p_export.add_argument("--format", required=True, choices=["md", "json", "csv"], dest="formato")
    p_export.add_argument("-o", "--output", dest="salida", default=None, help="Fichero de salida (por defecto, stdout)")

    p_rollback = sub.add_parser("rollback", help="Revierte una transacción ya aplicada")
    p_rollback.add_argument("--transaction", required=True, dest="transaction_id")
    p_rollback.add_argument("--root", required=True, help="authorized_root usado al aplicar")
    p_rollback.add_argument("--json", action="store_true", dest="as_json")

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.command == "doctor":
        return cmd_doctor(args.as_json)
    if args.command == "plex" and args.plex_command == "inspect":
        return cmd_plex_inspect(args.as_json)
    if args.command == "inventory" and args.inventory_command == "scan":
        return cmd_inventory_scan(args.root, args.library_id, args.content_type, args.as_json)
    if args.command == "export":
        return cmd_export(args.root, args.library_id, args.content_type, args.formato, args.salida)
    if args.command == "rollback":
        return cmd_rollback(args.transaction_id, args.root, args.as_json)

    return 2  # inalcanzable con argparse subparsers required=True, pero explícito en vez de silencioso


if __name__ == "__main__":
    sys.exit(main())
