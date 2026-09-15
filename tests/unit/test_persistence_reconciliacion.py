"""Fase 8: `reconciliar_transaccion()`/`reconciliar_reversion()` -- probadas contra un `Journal`/
`RollbackResult` REALES, nunca fabricados a mano: biblioteca real en `tmp_path`, `catalog sync`
real, plan real (`proponer_operaciones_pelicula`), aplicación/reversión reales
(`aplicar_plan()`/`revertir_transaccion()`), y el `Journal` leído tal cual del disco con
`leer_journal()`. SQLite real en `tmp_path` en todos los tests, nunca `unittest.mock`."""
from datetime import UTC, datetime
from pathlib import Path

from alpardi_media_manager.domain.models import ContentType
from alpardi_media_manager.domain.states import ItemState
from alpardi_media_manager.inventory.scanner import escanear_directorio
from alpardi_media_manager.persistence.catalog import (
    listar_items,
    reconciliar_reversion,
    reconciliar_transaccion,
    sincronizar_biblioteca,
)
from alpardi_media_manager.persistence.db import abrir_conexion
from alpardi_media_manager.planning.plan import (
    calcular_inventory_hash,
    generar_plan_renombrado,
    proponer_operaciones_pelicula,
)
from alpardi_media_manager.transactions.engine import (
    aplicar_plan,
    leer_journal,
    revertir_transaccion,
)

_AHORA_SYNC = datetime(2026, 1, 1, tzinfo=UTC)
_AHORA_RECON = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
_AHORA_RECON_2 = datetime(2026, 1, 1, 13, 0, tzinfo=UTC)


def _biblioteca_con_una_pelicula(tmp_path: Path) -> Path:
    biblioteca = tmp_path / "biblioteca"
    biblioteca.mkdir()
    (biblioteca / "7 minutos (2009).mkv").write_bytes(b"contenido real de la pelicula")
    return biblioteca


# --- reconciliar_transaccion: caso feliz, aplicada de verdad --------------------------------------

def test_reconciliar_transaccion_actualiza_current_path_y_item_state_tras_un_apply_real(tmp_path: Path) -> None:
    biblioteca = _biblioteca_con_una_pelicula(tmp_path)
    conn = abrir_conexion(tmp_path / "catalogo.sqlite3")
    try:
        sincronizar_biblioteca(conn, biblioteca, "lib-recon", ContentType.MOVIE, ahora=_AHORA_SYNC)

        items = escanear_directorio(biblioteca, library_id="lib-recon", content_type=ContentType.MOVIE)
        operaciones, saltados = proponer_operaciones_pelicula(items)
        assert saltados == 0 and len(operaciones) == 1
        inventory_hash = calcular_inventory_hash(items)
        plan = generar_plan_renombrado(operaciones, inventory_hash, authorized_root=biblioteca)

        resultado = aplicar_plan(plan, biblioteca, plan.frase_autorizacion_esperada(), inventory_hash_actual=inventory_hash)
        assert resultado.autorizada and resultado.transaction_id is not None

        journal = leer_journal(biblioteca, resultado.transaction_id)
        assert journal is not None

        reconciliar_transaccion(conn, journal, "lib-recon", _AHORA_RECON)

        items_catalogo = listar_items(conn, library_id="lib-recon")
        assert len(items_catalogo) == 1
        item = items_catalogo[0]
        assert item.current_path == "7 minutos (2009)/7 minutos (2009).mkv"
        assert item.state == ItemState.APPLIED
        # El archivo real en disco confirma que no es una coincidencia -- es la misma ruta que
        # `aplicar_plan()` acaba de mover de verdad.
        assert (biblioteca / item.current_path).read_bytes() == b"contenido real de la pelicula"
    finally:
        conn.close()


def test_reconciliar_transaccion_es_idempotente_si_se_llama_dos_veces_con_el_mismo_journal(tmp_path: Path) -> None:
    biblioteca = _biblioteca_con_una_pelicula(tmp_path)
    conn = abrir_conexion(tmp_path / "catalogo.sqlite3")
    try:
        sincronizar_biblioteca(conn, biblioteca, "lib-idem", ContentType.MOVIE, ahora=_AHORA_SYNC)
        items = escanear_directorio(biblioteca, library_id="lib-idem", content_type=ContentType.MOVIE)
        operaciones, _ = proponer_operaciones_pelicula(items)
        inventory_hash = calcular_inventory_hash(items)
        plan = generar_plan_renombrado(operaciones, inventory_hash, authorized_root=biblioteca)
        resultado = aplicar_plan(plan, biblioteca, plan.frase_autorizacion_esperada(), inventory_hash_actual=inventory_hash)
        assert resultado.transaction_id is not None
        journal = leer_journal(biblioteca, resultado.transaction_id)
        assert journal is not None

        reconciliar_transaccion(conn, journal, "lib-idem", _AHORA_RECON)
        reconciliar_transaccion(conn, journal, "lib-idem", _AHORA_RECON_2)  # no debe lanzar ni duplicar

        items_catalogo = listar_items(conn, library_id="lib-idem")
        assert len(items_catalogo) == 1
        assert items_catalogo[0].current_path == "7 minutos (2009)/7 minutos (2009).mkv"
        assert items_catalogo[0].state == ItemState.APPLIED
    finally:
        conn.close()


def test_reconciliar_transaccion_ignora_items_nunca_sincronizados_en_el_catalogo(tmp_path: Path) -> None:
    biblioteca = _biblioteca_con_una_pelicula(tmp_path)
    conn = abrir_conexion(tmp_path / "catalogo.sqlite3")
    try:
        # Deliberadamente NUNCA se llama a sincronizar_biblioteca -- el catálogo está vacío.
        items = escanear_directorio(biblioteca, library_id="lib-sin-sync", content_type=ContentType.MOVIE)
        operaciones, _ = proponer_operaciones_pelicula(items)
        inventory_hash = calcular_inventory_hash(items)
        plan = generar_plan_renombrado(operaciones, inventory_hash, authorized_root=biblioteca)
        resultado = aplicar_plan(plan, biblioteca, plan.frase_autorizacion_esperada(), inventory_hash_actual=inventory_hash)
        assert resultado.transaction_id is not None
        journal = leer_journal(biblioteca, resultado.transaction_id)
        assert journal is not None

        reconciliar_transaccion(conn, journal, "lib-sin-sync", _AHORA_RECON)  # no debe lanzar

        assert listar_items(conn, library_id="lib-sin-sync") == []
        # El movimiento real en disco sí ocurrió -- solo el catálogo (opcional) se quedó atrás.
        assert (biblioteca / "7 minutos (2009)" / "7 minutos (2009).mkv").exists()
    finally:
        conn.close()


def test_reconciliar_transaccion_marca_failed_y_no_toca_current_path_si_nunca_se_movio(tmp_path: Path) -> None:
    """Condición de carrera real: el destino aparece DESPUÉS de generar el plan (no afecta al
    inventory_hash, que solo depende del ORIGEN) -- `aplicar_plan()` la detecta justo antes de
    mover con un `conflicto_destino` real, sin tocar el archivo original."""
    biblioteca = _biblioteca_con_una_pelicula(tmp_path)
    conn = abrir_conexion(tmp_path / "catalogo.sqlite3")
    try:
        sincronizar_biblioteca(conn, biblioteca, "lib-conflicto", ContentType.MOVIE, ahora=_AHORA_SYNC)
        items = escanear_directorio(biblioteca, library_id="lib-conflicto", content_type=ContentType.MOVIE)
        operaciones, _ = proponer_operaciones_pelicula(items)
        inventory_hash = calcular_inventory_hash(items)
        plan = generar_plan_renombrado(operaciones, inventory_hash, authorized_root=biblioteca)

        destino_dir = biblioteca / "7 minutos (2009)"
        destino_dir.mkdir()
        (destino_dir / "7 minutos (2009).mkv").write_bytes(b"ya habia algo aqui")

        resultado = aplicar_plan(plan, biblioteca, plan.frase_autorizacion_esperada(), inventory_hash_actual=inventory_hash)
        assert resultado.transaction_id is not None
        assert resultado.operations[0].status.value == "conflicto_destino"

        journal = leer_journal(biblioteca, resultado.transaction_id)
        assert journal is not None
        reconciliar_transaccion(conn, journal, "lib-conflicto", _AHORA_RECON)

        item = listar_items(conn, library_id="lib-conflicto")[0]
        assert item.current_path == "7 minutos (2009).mkv"  # nunca se tocó -- current_path intacto
        assert item.state == ItemState.FAILED
        # El original sigue existiendo real, sin tocar.
        assert (biblioteca / "7 minutos (2009).mkv").read_bytes() == b"contenido real de la pelicula"
    finally:
        conn.close()


# --- reconciliar_reversion: caso feliz, revertida de verdad ---------------------------------------

def test_reconciliar_reversion_devuelve_current_path_y_estado_tras_un_rollback_real(tmp_path: Path) -> None:
    biblioteca = _biblioteca_con_una_pelicula(tmp_path)
    conn = abrir_conexion(tmp_path / "catalogo.sqlite3")
    try:
        sincronizar_biblioteca(conn, biblioteca, "lib-rb", ContentType.MOVIE, ahora=_AHORA_SYNC)
        items = escanear_directorio(biblioteca, library_id="lib-rb", content_type=ContentType.MOVIE)
        operaciones, _ = proponer_operaciones_pelicula(items)
        inventory_hash = calcular_inventory_hash(items)
        plan = generar_plan_renombrado(operaciones, inventory_hash, authorized_root=biblioteca)
        resultado = aplicar_plan(plan, biblioteca, plan.frase_autorizacion_esperada(), inventory_hash_actual=inventory_hash)
        assert resultado.transaction_id is not None
        journal = leer_journal(biblioteca, resultado.transaction_id)
        assert journal is not None
        reconciliar_transaccion(conn, journal, "lib-rb", _AHORA_RECON)
        assert listar_items(conn, library_id="lib-rb")[0].state == ItemState.APPLIED

        resultado_rollback = revertir_transaccion(resultado.transaction_id, biblioteca)
        assert resultado_rollback.completa is True

        reconciliar_reversion(conn, resultado_rollback, "lib-rb", _AHORA_RECON_2)

        item = listar_items(conn, library_id="lib-rb")[0]
        assert item.current_path == "7 minutos (2009).mkv"
        assert item.state == ItemState.ROLLED_BACK
        assert (biblioteca / "7 minutos (2009).mkv").read_bytes() == b"contenido real de la pelicula"
    finally:
        conn.close()


def test_reconciliar_reversion_encuentra_la_fila_por_source_path_si_el_apply_nunca_se_reconcilio(tmp_path: Path) -> None:
    """`apply` real hecho SIN `reconciliar_transaccion()` (equivalente a un `apply` sin `--db` en
    la CLI) -- el catálogo nunca llegó a registrar el movimiento, así que su `current_path` sigue
    siendo el original. `reconciliar_reversion()` debe encontrar la fila igualmente (por
    `source_path`, su segundo intento) y limitarse a corregir el estado."""
    biblioteca = _biblioteca_con_una_pelicula(tmp_path)
    conn = abrir_conexion(tmp_path / "catalogo.sqlite3")
    try:
        sincronizar_biblioteca(conn, biblioteca, "lib-rb2", ContentType.MOVIE, ahora=_AHORA_SYNC)
        items = escanear_directorio(biblioteca, library_id="lib-rb2", content_type=ContentType.MOVIE)
        operaciones, _ = proponer_operaciones_pelicula(items)
        inventory_hash = calcular_inventory_hash(items)
        plan = generar_plan_renombrado(operaciones, inventory_hash, authorized_root=biblioteca)
        resultado = aplicar_plan(plan, biblioteca, plan.frase_autorizacion_esperada(), inventory_hash_actual=inventory_hash)
        assert resultado.transaction_id is not None
        # (nunca se llama a reconciliar_transaccion aquí, a propósito)

        resultado_rollback = revertir_transaccion(resultado.transaction_id, biblioteca)
        assert resultado_rollback.completa is True

        reconciliar_reversion(conn, resultado_rollback, "lib-rb2", _AHORA_RECON_2)

        item = listar_items(conn, library_id="lib-rb2")[0]
        assert item.current_path == "7 minutos (2009).mkv"  # ya era correcto, no cambia
        assert item.state == ItemState.ROLLED_BACK
    finally:
        conn.close()


def test_reconciliar_reversion_marca_needs_review_si_la_reversion_real_fallo(tmp_path: Path) -> None:
    """El archivo aplicado desaparece de verdad (borrado fuera del motor transaccional) ANTES de
    intentar revertir -- `revertir_transaccion()` no puede recuperarlo y lo marca
    `error_reversion` de verdad. La reconciliación debe reflejar la ambigüedad, nunca inventar."""
    biblioteca = _biblioteca_con_una_pelicula(tmp_path)
    conn = abrir_conexion(tmp_path / "catalogo.sqlite3")
    try:
        sincronizar_biblioteca(conn, biblioteca, "lib-rb-error", ContentType.MOVIE, ahora=_AHORA_SYNC)
        items = escanear_directorio(biblioteca, library_id="lib-rb-error", content_type=ContentType.MOVIE)
        operaciones, _ = proponer_operaciones_pelicula(items)
        inventory_hash = calcular_inventory_hash(items)
        plan = generar_plan_renombrado(operaciones, inventory_hash, authorized_root=biblioteca)
        resultado = aplicar_plan(plan, biblioteca, plan.frase_autorizacion_esperada(), inventory_hash_actual=inventory_hash)
        assert resultado.transaction_id is not None
        journal = leer_journal(biblioteca, resultado.transaction_id)
        assert journal is not None
        reconciliar_transaccion(conn, journal, "lib-rb-error", _AHORA_RECON)

        destino_real = biblioteca / "7 minutos (2009)" / "7 minutos (2009).mkv"
        destino_real.unlink()

        resultado_rollback = revertir_transaccion(resultado.transaction_id, biblioteca)
        assert resultado_rollback.completa is False
        assert resultado_rollback.operations[0].status.value == "error_reversion"

        reconciliar_reversion(conn, resultado_rollback, "lib-rb-error", _AHORA_RECON_2)

        item = listar_items(conn, library_id="lib-rb-error")[0]
        # Ambiguo -- el catálogo no sabe si el archivo está en destino o en ningún sitio, así que
        # nunca inventa una ruta: se queda con la última conocida.
        assert item.current_path == "7 minutos (2009)/7 minutos (2009).mkv"
        assert item.state == ItemState.NEEDS_REVIEW
    finally:
        conn.close()
