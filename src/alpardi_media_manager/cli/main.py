"""Punto de entrada de la CLI. Todos los comandos de consulta soportan salida humana y --json
(regla explícita del encargo). Los comandos con efectos (`apply`, `rollback`) solo mutan archivos
reales tras las comprobaciones del propio motor transaccional -- `apply` exige la frase de
autorización exacta letra por letra, nunca la interpreta ni la infiere."""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from alpardi_media_manager.backup.engine import crear_backup, verificar_backup
from alpardi_media_manager.config import leer_plex_token, nas_ssh_host, plex_base_url
from alpardi_media_manager.diagnostics.checks import CheckStatus, run_all_checks
from alpardi_media_manager.domain.models import ContentType
from alpardi_media_manager.inventory.scanner import escanear_directorio
from alpardi_media_manager.matching.engine import verificar_coincidencias_pelicula
from alpardi_media_manager.planning.plan import (
    calcular_inventory_hash,
    cargar_plan,
    generar_plan_renombrado,
    guardar_plan,
    proponer_operaciones_pelicula,
)
from alpardi_media_manager.plex.client import PlexClient
from alpardi_media_manager.providers.status import leer_estado_proveedores
from alpardi_media_manager.reports.inventory_report import (
    inventario_a_csv,
    inventario_a_json,
    inventario_a_markdown,
)
from alpardi_media_manager.reports.plan_report import plan_a_json, plan_a_markdown
from alpardi_media_manager.reports.transaction_report import (
    resultado_aplicacion_a_markdown,
    resultado_reversion_a_markdown,
)
from alpardi_media_manager.transactions.engine import (
    EstadoTransaccion,
    aplicar_plan,
    revertir_transaccion,
)

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


def cmd_plan_rename(root: str, library_id: str, content_type: str, salida: str | None, as_json: bool) -> int:
    if content_type != "movie":
        print(
            "✗ 'plan rename' de momento solo soporta --content-type movie "
            "(ver docs/ARCHITECTURE.md -- episodios necesita más diseño)",
            file=sys.stderr,
        )
        return 1

    ruta = Path(root)
    if not ruta.is_dir():
        print(f"✗ La raíz no existe o no es un directorio: {ruta}", file=sys.stderr)
        return 1

    items = escanear_directorio(ruta, library_id=library_id, content_type=ContentType.MOVIE)
    operaciones, saltados = proponer_operaciones_pelicula(items)
    inventory_hash = calcular_inventory_hash(items)
    plan = generar_plan_renombrado(operaciones, inventory_hash, authorized_root=ruta)

    if salida:
        guardar_plan(plan, Path(salida))

    if as_json:
        print(plan_a_json(plan))
    else:
        print(plan_a_markdown(plan))
        if saltados:
            print(f"\n({saltados} elemento(s) no se pudieron interpretar por el nombre -- revisar manualmente, no se han incluido en el plan)")
        if salida:
            print(f"\n✓ Plan guardado en {salida}")
    return 0


def cmd_apply(
    plan_path: str, root: str, library_id: str, content_type: str, autorizacion: str, as_json: bool,
) -> int:
    ruta_plan = Path(plan_path)
    if not ruta_plan.is_file():
        print(f"✗ No existe el fichero de plan: {plan_path}", file=sys.stderr)
        return 1
    try:
        tipo = ContentType(content_type)
    except ValueError:
        tipos_validos = ", ".join(t.value for t in ContentType)
        print(f"✗ content-type inválido: '{content_type}'. Válidos: {tipos_validos}", file=sys.stderr)
        return 1

    plan = cargar_plan(ruta_plan)
    ruta_root = Path(root)

    # Se vuelve a escanear AHORA MISMO -- el inventory_hash tiene que reflejar el estado real del
    # filesystem en el momento de aplicar, no el de cuando se generó el plan (regla del encargo:
    # "Si el inventario cambió, el plan expira").
    items_actuales = escanear_directorio(ruta_root, library_id=library_id, content_type=tipo)
    inventory_hash_actual = calcular_inventory_hash(items_actuales)

    resultado = aplicar_plan(plan, ruta_root, autorizacion, inventory_hash_actual)

    if as_json:
        print(json.dumps({
            "plan_id": resultado.plan_id,
            "autorizada": resultado.autorizada,
            "transaction_id": resultado.transaction_id,
            "estado": resultado.estado.value if resultado.estado else None,
            "motivo_rechazo": resultado.motivo_rechazo,
            "operations": [
                {"index": op.index, "status": op.status.value, "detail": op.detail}
                for op in resultado.operations
            ],
        }, indent=2, ensure_ascii=False))
    else:
        print(resultado_aplicacion_a_markdown(resultado))

    if not resultado.autorizada:
        return 1
    return 0 if resultado.estado == EstadoTransaccion.COMPLETADA else 1


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


def cmd_providers_status(config_path: str, as_json: bool) -> int:
    try:
        estado = leer_estado_proveedores(Path(config_path))
    except FileNotFoundError as e:
        print(f"✗ {e}", file=sys.stderr)
        return 1

    if as_json:
        print(json.dumps({
            "config_path": str(estado.config_path),
            "is_template": estado.is_template,
            "providers": [
                {"provider": p.provider, "enabled": p.enabled, "has_credential_ref": p.has_credential_ref}
                for p in estado.providers
            ],
        }, indent=2, ensure_ascii=False))
    else:
        if estado.is_template:
            print(f"⚠ Mostrando la PLANTILLA ({estado.config_path}), no una configuración real activa\n")
        for p in estado.providers:
            marca = "habilitado" if p.enabled else "deshabilitado"
            cred = "con credential_ref" if p.has_credential_ref else "sin credencial configurada"
            print(f"  - {p.provider}: {marca} ({cred})")
        habilitados = sum(1 for p in estado.providers if p.enabled)
        print(f"\n{habilitados}/{len(estado.providers)} proveedores habilitados.")
    return 0


def cmd_match_check(root: str, library_id: str, content_type: str, as_json: bool) -> int:
    if content_type != "movie":
        print("✗ 'match check' de momento solo soporta --content-type movie", file=sys.stderr)
        return 1

    ruta = Path(root)
    if not ruta.is_dir():
        print(f"✗ La raíz no existe o no es un directorio: {ruta}", file=sys.stderr)
        return 1

    items = escanear_directorio(ruta, library_id=library_id, content_type=ContentType.MOVIE)
    resultados = verificar_coincidencias_pelicula(items)

    if as_json:
        print(json.dumps({"total": len(resultados), "results": resultados}, indent=2, ensure_ascii=False))
    else:
        print(
            "⚠ 0 proveedores activos todavía: todo aparecerá como 'needs_review' o "
            "'sin_interpretar' hasta activar al menos uno (ver `providers status`).\n"
        )
        for r in resultados:
            razones = ", ".join(r["reasons"])  # type: ignore[arg-type]
            print(f"  - {r['path']}: {r['state']} ({razones})")
        revisar = sum(1 for r in resultados if r["state"] != "matched")
        print(f"\n{len(resultados)} elemento(s), {revisar} necesitan revisión.")
    return 0


def cmd_backup_create(raiz_proyecto: str, directorio_salida: str, as_json: bool) -> int:
    resultado = crear_backup(Path(raiz_proyecto), Path(directorio_salida), datetime.now(UTC))

    if as_json:
        print(json.dumps({
            "archive_path": str(resultado.archive_path),
            "sha256_path": str(resultado.sha256_path),
            "file_count": resultado.file_count,
            "total_bytes": resultado.total_bytes,
            "sha256": resultado.sha256,
        }, indent=2, ensure_ascii=False))
    else:
        print(f"✓ Backup creado: {resultado.archive_path}")
        print(f"  {resultado.file_count} archivo(s), {resultado.total_bytes} bytes, sha256={resultado.sha256}")
        if resultado.file_count == 0:
            print("  (0 archivos es normal si todavía no se ha aplicado ningún plan real -- ver docs/BACKUP_RESTORE.md)")
    return 0


def cmd_backup_verify(archive: str, as_json: bool) -> int:
    resultado = verificar_backup(Path(archive))

    if as_json:
        print(json.dumps({"ok": resultado.ok, "detail": resultado.detail}, indent=2, ensure_ascii=False))
    else:
        simbolo = "✓" if resultado.ok else "✗"
        print(f"{simbolo} {resultado.detail}")
    return 0 if resultado.ok else 1


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

    p_plan = sub.add_parser("plan", help="Genera un plan (nunca toca archivos)")
    sub_plan = p_plan.add_subparsers(dest="plan_command", required=True)
    p_plan_rename = sub_plan.add_parser("rename", help="Propone un plan de renombrado (solo movie por ahora)")
    p_plan_rename.add_argument("root")
    p_plan_rename.add_argument("--library-id", required=True)
    p_plan_rename.add_argument("--content-type", required=True)
    p_plan_rename.add_argument("-o", "--output", dest="salida", default=None, help="Guardar el plan en este fichero JSON")
    p_plan_rename.add_argument("--json", action="store_true", dest="as_json")

    p_apply = sub.add_parser("apply", help="Aplica un plan ya generado -- exige la frase de autorización exacta")
    p_apply.add_argument("--plan", required=True, dest="plan_path")
    p_apply.add_argument("--root", required=True)
    p_apply.add_argument("--library-id", required=True, help="El mismo usado al generar el plan")
    p_apply.add_argument("--content-type", required=True, help="El mismo usado al generar el plan")
    p_apply.add_argument("--authorize", required=True, dest="autorizacion", help='La frase EXACTA, p.ej. "AUTORIZO APLICAR PLAN plan_... SOBRE N ELEMENTOS"')
    p_apply.add_argument("--json", action="store_true", dest="as_json")

    p_rollback = sub.add_parser("rollback", help="Revierte una transacción ya aplicada")
    p_rollback.add_argument("--transaction", required=True, dest="transaction_id")
    p_rollback.add_argument("--root", required=True, help="authorized_root usado al aplicar")
    p_rollback.add_argument("--json", action="store_true", dest="as_json")

    p_providers = sub.add_parser("providers", help="Estado configurado de los proveedores (solo lectura, sin red)")
    sub_providers = p_providers.add_subparsers(dest="providers_command", required=True)
    p_providers_status = sub_providers.add_parser("status", help="Lista qué proveedores están habilitados/deshabilitados")
    p_providers_status.add_argument("--config", default="config/providers.yaml", dest="config_path")
    p_providers_status.add_argument("--json", action="store_true", dest="as_json")

    p_match = sub.add_parser("match", help="Coincidencias locales (sin llamar a ningún proveedor todavía)")
    sub_match = p_match.add_subparsers(dest="match_command", required=True)
    p_match_check = sub_match.add_parser("check", help="Evalúa el estado de coincidencia local de cada elemento (solo movie por ahora)")
    p_match_check.add_argument("root")
    p_match_check.add_argument("--library-id", required=True)
    p_match_check.add_argument("--content-type", required=True)
    p_match_check.add_argument("--json", action="store_true", dest="as_json")

    p_backup = sub.add_parser("backup", help="Copia de seguridad de plans/journals/reports/config -- nunca de los medios")
    sub_backup = p_backup.add_subparsers(dest="backup_command", required=True)
    p_backup_create = sub_backup.add_parser("create", help="Crea un backup con sha256")
    p_backup_create.add_argument("--root", default=".", dest="raiz_proyecto", help="Raíz del proyecto (por defecto, el directorio actual)")
    p_backup_create.add_argument("-o", "--output", default="backups", dest="directorio_salida")
    p_backup_create.add_argument("--json", action="store_true", dest="as_json")
    p_backup_verify = sub_backup.add_parser("verify", help="Recalcula el sha256 y extrae de verdad para confirmar integridad")
    p_backup_verify.add_argument("archive")
    p_backup_verify.add_argument("--json", action="store_true", dest="as_json")

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
    if args.command == "plan" and args.plan_command == "rename":
        return cmd_plan_rename(args.root, args.library_id, args.content_type, args.salida, args.as_json)
    if args.command == "apply":
        return cmd_apply(args.plan_path, args.root, args.library_id, args.content_type, args.autorizacion, args.as_json)
    if args.command == "rollback":
        return cmd_rollback(args.transaction_id, args.root, args.as_json)
    if args.command == "providers" and args.providers_command == "status":
        return cmd_providers_status(args.config_path, args.as_json)
    if args.command == "match" and args.match_command == "check":
        return cmd_match_check(args.root, args.library_id, args.content_type, args.as_json)
    if args.command == "backup" and args.backup_command == "create":
        return cmd_backup_create(args.raiz_proyecto, args.directorio_salida, args.as_json)
    if args.command == "backup" and args.backup_command == "verify":
        return cmd_backup_verify(args.archive, args.as_json)

    return 2  # inalcanzable con argparse subparsers required=True, pero explícito en vez de silencioso


if __name__ == "__main__":
    sys.exit(main())
