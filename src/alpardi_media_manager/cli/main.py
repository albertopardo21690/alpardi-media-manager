"""Punto de entrada de la CLI. Todos los comandos de consulta soportan salida humana y --json
(regla explícita del encargo). Los comandos con efectos (`apply`, `rollback`) solo mutan archivos
reales tras las comprobaciones del propio motor transaccional -- `apply` exige la frase de
autorización exacta letra por letra, nunca la interpreta ni la infiere."""
from __future__ import annotations

import argparse
import asyncio
import json
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path

from alpardi_media_manager.backup.engine import crear_backup, verificar_backup
from alpardi_media_manager.config import database_path, leer_plex_token, nas_ssh_host, plex_base_url
from alpardi_media_manager.diagnostics.checks import CheckStatus, run_all_checks
from alpardi_media_manager.domain.capabilities import verificar_content_type_soportado
from alpardi_media_manager.domain.models import ContentType
from alpardi_media_manager.domain.states import ItemState
from alpardi_media_manager.inventory.scanner import escanear_directorio
from alpardi_media_manager.matching.engine import (
    verificar_coincidencias_episodio,
    verificar_coincidencias_pelicula,
)
from alpardi_media_manager.persistence.catalog import (
    listar_items,
    reconciliar_reversion,
    reconciliar_transaccion,
    sincronizar_biblioteca,
)
from alpardi_media_manager.persistence.db import abrir_conexion, aplicar_migraciones
from alpardi_media_manager.planning.plan import (
    calcular_inventory_hash,
    cargar_plan,
    generar_plan_renombrado,
    guardar_plan,
    proponer_operaciones_episodio,
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
    RollbackResult,
    aplicar_plan,
    leer_journal,
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
    try:
        tipo = ContentType(content_type)
    except ValueError:
        tipos_validos = ", ".join(t.value for t in ContentType)
        print(f"✗ content-type inválido: '{content_type}'. Válidos: {tipos_validos}", file=sys.stderr)
        return 1
    try:
        verificar_content_type_soportado(tipo)
    except ValueError as e:
        print(f"✗ 'plan rename': {e}", file=sys.stderr)
        return 1

    ruta = Path(root)
    if not ruta.is_dir():
        print(f"✗ La raíz no existe o no es un directorio: {ruta}", file=sys.stderr)
        return 1

    items = escanear_directorio(ruta, library_id=library_id, content_type=tipo)
    if tipo == ContentType.MOVIE:
        operaciones, saltados = proponer_operaciones_pelicula(items)
    else:  # único otro valor posible tras verificar_content_type_soportado: TV_EPISODE
        operaciones, saltados = proponer_operaciones_episodio(items)
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


# Excepciones reales que puede lanzar el bloque de reconciliación best-effort: sqlite3.Error
# (conexión/consulta SQLite), OSError (I/O al abrir la base o leer el journal.json de disco) y
# ValueError (JSON de journal corrupto, o `actualizar_estado()` rechazando una transición -- ver
# docstring de `_reconciliar_tras_apply` sobre por qué esto NUNCA debe escalar como un fallo del
# comando). Listadas explícitamente en vez de `except Exception` -- capturar únicamente lo que de
# verdad puede pasar aquí, nunca un `except` ciego que también tragaría errores de programación
# reales (p.ej. un `NameError` por una variable mal escrita, que sí debe reventar el proceso).
_EXCEPCIONES_RECONCILIACION_BEST_EFFORT = (sqlite3.Error, OSError, ValueError)


def _reconciliar_tras_apply(
    db_path: str, ruta_root: Path, transaction_id: str, library_id: str,
) -> None:
    """Reconciliación best-effort del catálogo SQLite tras un `apply` real con `--db`.

    Decisión de diseño (Fase 8): en el momento en que esta función se llama, el motor
    transaccional YA ha movido los archivos reales -- `aplicar_plan()` ya devolvió su resultado y
    `cmd_apply()` ya lo imprimió. Un fallo aquí (SQLite bloqueada, permiso denegado, disco lleno,
    lo que sea) nunca debe ocultar ni invalidar ese resultado real ya consumado y ya comunicado:
    se captura cualquier excepción, se avisa FUERTE por stderr con el detalle real (nunca en
    silencio), y el código de salida del comando sigue dependiendo solo del resultado real de
    `aplicar_plan()` -- nunca de si el catálogo SQLite (una vista derivada, opcional) se pudo
    actualizar. Perder la mutación real de archivos ya aplicada, o esconder que ocurrió, sería
    mucho peor que dejar el catálogo temporalmente desincronizado (que además es recuperable con
    un futuro `catalog sync` + una reconciliación manual)."""
    try:
        journal = leer_journal(ruta_root, transaction_id)
        if journal is None:
            raise RuntimeError(
                f"no se encontró el journal persistido de la transacción {transaction_id}"
            )
        conn = abrir_conexion(_resolver_ruta_db(db_path))
        try:
            reconciliar_transaccion(conn, journal, library_id, datetime.now(UTC))
        finally:
            conn.close()
    except _EXCEPCIONES_RECONCILIACION_BEST_EFFORT as e:  # ver docstring -- nunca oculta el resultado real
        print(
            f"⚠ La transacción se aplicó en disco correctamente, pero no se pudo reconciliar el "
            f"catálogo SQLite ({db_path}): {e}",
            file=sys.stderr,
        )


def _reconciliar_tras_rollback(db_path: str, library_id: str, resultado: RollbackResult) -> None:
    """Simétrica a `_reconciliar_tras_apply()` -- misma decisión de diseño: un fallo aquí nunca
    debe ocultar que la reversión real de archivos ya ocurrió."""
    try:
        conn = abrir_conexion(_resolver_ruta_db(db_path))
        try:
            reconciliar_reversion(conn, resultado, library_id, datetime.now(UTC))
        finally:
            conn.close()
    except _EXCEPCIONES_RECONCILIACION_BEST_EFFORT as e:  # ver docstring de _reconciliar_tras_apply
        print(
            f"⚠ La reversión se aplicó en disco correctamente, pero no se pudo reconciliar el "
            f"catálogo SQLite ({db_path}): {e}",
            file=sys.stderr,
        )


def cmd_apply(
    plan_path: str, root: str, library_id: str, content_type: str, autorizacion: str, as_json: bool,
    db_path: str | None = None,
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

    # `--db` es opcional (default None): sin él, el comportamiento es exactamente el de antes de
    # la Fase 8, ningún test existente sin `--db` se ve afectado. Solo se reconcilia si de verdad
    # hubo una transacción real (autorizada) con id -- una autorización rechazada nunca creó
    # journal, no hay nada que reconciliar.
    if db_path is not None and resultado.autorizada and resultado.transaction_id is not None:
        _reconciliar_tras_apply(db_path, ruta_root, resultado.transaction_id, library_id)

    if not resultado.autorizada:
        return 1
    return 0 if resultado.estado == EstadoTransaccion.COMPLETADA else 1


def cmd_rollback(
    transaction_id: str, root: str, as_json: bool,
    db_path: str | None = None, library_id: str | None = None,
) -> int:
    # Validación de entrada pura, ANTES de tocar nada real -- a diferencia de un fallo de
    # reconciliación tras una reversión ya ocurrida (ver _reconciliar_tras_rollback), esto SÍ debe
    # bloquear el comando entero: sin library_id no hay forma de saber qué filas de `(library_id,
    # current_path)` reconciliar, y es un error detectable sin haber movido ni un solo archivo.
    if db_path is not None and library_id is None:
        print(
            "✗ 'rollback --db' requiere también '--library-id' para poder reconciliar el catálogo",
            file=sys.stderr,
        )
        return 1

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

    if db_path is not None and resultado.encontrada and library_id is not None:
        _reconciliar_tras_rollback(db_path, library_id, resultado)

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
    try:
        tipo = ContentType(content_type)
    except ValueError:
        tipos_validos = ", ".join(t.value for t in ContentType)
        print(f"✗ content-type inválido: '{content_type}'. Válidos: {tipos_validos}", file=sys.stderr)
        return 1
    try:
        verificar_content_type_soportado(tipo)
    except ValueError as e:
        print(f"✗ 'match check': {e}", file=sys.stderr)
        return 1

    ruta = Path(root)
    if not ruta.is_dir():
        print(f"✗ La raíz no existe o no es un directorio: {ruta}", file=sys.stderr)
        return 1

    items = escanear_directorio(ruta, library_id=library_id, content_type=tipo)
    if tipo == ContentType.MOVIE:
        resultados = verificar_coincidencias_pelicula(items)
    else:  # único otro valor posible tras verificar_content_type_soportado: TV_EPISODE
        resultados = verificar_coincidencias_episodio(items)

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


def _resolver_ruta_db(db_path: str | None) -> Path:
    return Path(db_path) if db_path else database_path()


def cmd_catalog_sync(root: str, library_id: str, content_type: str, db_path: str | None, as_json: bool) -> int:
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

    conn = abrir_conexion(_resolver_ruta_db(db_path))
    try:
        resultado = sincronizar_biblioteca(conn, ruta, library_id, tipo)
    finally:
        conn.close()

    if as_json:
        print(json.dumps({
            "library_id": library_id,
            "nuevos": resultado.nuevos,
            "actualizados": resultado.actualizados,
            "total": resultado.total,
        }, indent=2, ensure_ascii=False))
    else:
        print(
            f"✓ catalog sync ({library_id}): {resultado.total} elemento(s) -- "
            f"{resultado.nuevos} nuevo(s), {resultado.actualizados} actualizado(s)."
        )
    return 0


def cmd_catalog_list(
    library_id: str, content_type: str | None, state: str | None, db_path: str | None, as_json: bool,
) -> int:
    tipo = None
    if content_type is not None:
        try:
            tipo = ContentType(content_type)
        except ValueError:
            tipos_validos = ", ".join(t.value for t in ContentType)
            print(f"✗ content-type inválido: '{content_type}'. Válidos: {tipos_validos}", file=sys.stderr)
            return 1

    estado = None
    if state is not None:
        try:
            estado = ItemState(state)
        except ValueError:
            estados_validos = ", ".join(e.value for e in ItemState)
            print(f"✗ state inválido: '{state}'. Válidos: {estados_validos}", file=sys.stderr)
            return 1

    conn = abrir_conexion(_resolver_ruta_db(db_path))
    try:
        items = listar_items(conn, library_id=library_id, content_type=tipo, state=estado)
    finally:
        conn.close()

    if as_json:
        print(inventario_a_json(items))
    else:
        print(inventario_a_markdown(items))
    return 0


def cmd_catalog_migrate(db_path: str | None, as_json: bool) -> int:
    conn = abrir_conexion(_resolver_ruta_db(db_path), auto_migrar=False)
    try:
        aplicadas = aplicar_migraciones(conn)
    finally:
        conn.close()

    if as_json:
        print(json.dumps({"applied": aplicadas}, indent=2, ensure_ascii=False))
    elif aplicadas:
        print(f"✓ {len(aplicadas)} migración(es) aplicada(s): {', '.join(str(v) for v in aplicadas)}")
    else:
        print("✓ La base de datos ya estaba al día -- ninguna migración pendiente.")
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
    p_plan_rename = sub_plan.add_parser("rename", help="Propone un plan de renombrado (movie o tv_episode)")
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
    p_apply.add_argument("--db", default=None, dest="db_path", help="Opcional (Fase 8): tras aplicar con éxito, reconcilia current_path/item_state en esta base SQLite")

    p_rollback = sub.add_parser("rollback", help="Revierte una transacción ya aplicada")
    p_rollback.add_argument("--transaction", required=True, dest="transaction_id")
    p_rollback.add_argument("--root", required=True, help="authorized_root usado al aplicar")
    p_rollback.add_argument("--json", action="store_true", dest="as_json")
    p_rollback.add_argument("--db", default=None, dest="db_path", help="Opcional (Fase 8): tras revertir con éxito, reconcilia current_path/item_state en esta base SQLite")
    p_rollback.add_argument("--library-id", default=None, dest="library_id", help="Requerido junto con --db, para reconciliar el catálogo")

    p_providers = sub.add_parser("providers", help="Estado configurado de los proveedores (solo lectura, sin red)")
    sub_providers = p_providers.add_subparsers(dest="providers_command", required=True)
    p_providers_status = sub_providers.add_parser("status", help="Lista qué proveedores están habilitados/deshabilitados")
    p_providers_status.add_argument("--config", default="config/providers.yaml", dest="config_path")
    p_providers_status.add_argument("--json", action="store_true", dest="as_json")

    p_match = sub.add_parser("match", help="Coincidencias locales (sin llamar a ningún proveedor todavía)")
    sub_match = p_match.add_subparsers(dest="match_command", required=True)
    p_match_check = sub_match.add_parser("check", help="Evalúa el estado de coincidencia local de cada elemento (movie o tv_episode)")
    p_match_check.add_argument("root")
    p_match_check.add_argument("--library-id", required=True)
    p_match_check.add_argument("--content-type", required=True)
    p_match_check.add_argument("--json", action="store_true", dest="as_json")

    p_catalog = sub.add_parser("catalog", help="Catálogo SQLite persistente de inventario (Fase 5 -- no expuesto en mcp/server.py)")
    sub_catalog = p_catalog.add_subparsers(dest="catalog_command", required=True)
    p_catalog_sync = sub_catalog.add_parser("sync", help="Escanea una raíz y persiste el resultado en SQLite (upsert, nunca resetea item_state)")
    p_catalog_sync.add_argument("root")
    p_catalog_sync.add_argument("--library-id", required=True)
    p_catalog_sync.add_argument("--content-type", required=True)
    p_catalog_sync.add_argument("--db", default=None, dest="db_path", help="Ruta a la base SQLite (por defecto, config.database_path())")
    p_catalog_sync.add_argument("--json", action="store_true", dest="as_json")
    p_catalog_list = sub_catalog.add_parser("list", help="Lista items ya persistidos en SQLite (sin volver a escanear el filesystem)")
    p_catalog_list.add_argument("--library-id", required=True)
    p_catalog_list.add_argument("--content-type", default=None)
    p_catalog_list.add_argument("--state", default=None, help="discovered|parsed|matched|... (ver domain/states.py)")
    p_catalog_list.add_argument("--db", default=None, dest="db_path")
    p_catalog_list.add_argument("--json", action="store_true", dest="as_json")
    p_catalog_migrate = sub_catalog.add_parser("migrate", help="Aplica las migraciones de migrations/ pendientes sobre la base SQLite")
    p_catalog_migrate.add_argument("--db", default=None, dest="db_path")
    p_catalog_migrate.add_argument("--json", action="store_true", dest="as_json")

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
        return cmd_apply(args.plan_path, args.root, args.library_id, args.content_type, args.autorizacion, args.as_json, args.db_path)
    if args.command == "rollback":
        return cmd_rollback(args.transaction_id, args.root, args.as_json, args.db_path, args.library_id)
    if args.command == "providers" and args.providers_command == "status":
        return cmd_providers_status(args.config_path, args.as_json)
    if args.command == "match" and args.match_command == "check":
        return cmd_match_check(args.root, args.library_id, args.content_type, args.as_json)
    if args.command == "catalog" and args.catalog_command == "sync":
        return cmd_catalog_sync(args.root, args.library_id, args.content_type, args.db_path, args.as_json)
    if args.command == "catalog" and args.catalog_command == "list":
        return cmd_catalog_list(args.library_id, args.content_type, args.state, args.db_path, args.as_json)
    if args.command == "catalog" and args.catalog_command == "migrate":
        return cmd_catalog_migrate(args.db_path, args.as_json)
    if args.command == "backup" and args.backup_command == "create":
        return cmd_backup_create(args.raiz_proyecto, args.directorio_salida, args.as_json)
    if args.command == "backup" and args.backup_command == "verify":
        return cmd_backup_verify(args.archive, args.as_json)

    return 2  # inalcanzable con argparse subparsers required=True, pero explícito en vez de silencioso


if __name__ == "__main__":
    sys.exit(main())
