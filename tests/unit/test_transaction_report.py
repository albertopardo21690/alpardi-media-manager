import uuid
from pathlib import Path

from alpardi_media_manager.planning.plan import RenameOperation, generar_plan_renombrado
from alpardi_media_manager.reports.transaction_report import (
    resultado_aplicacion_a_markdown,
    resultado_reversion_a_markdown,
)
from alpardi_media_manager.transactions.engine import aplicar_plan, revertir_transaccion


def _op(source: str, destino: str, size: int = 1000) -> RenameOperation:
    return RenameOperation(item_id=uuid.uuid4(), source_path=source, destination_path=destino, size_bytes=size)


def test_aplicacion_rechazada_no_confunde_con_una_aplicada(tmp_path: Path):
    (tmp_path / "a.mkv").write_bytes(b"x")
    plan = generar_plan_renombrado([_op("a.mkv", "b.mkv")], inventory_hash="h", authorized_root=tmp_path)

    resultado = aplicar_plan(plan, tmp_path, "frase incorrecta", inventory_hash_actual="h")
    md = resultado_aplicacion_a_markdown(resultado)

    assert "NO aplicado" in md
    assert "no coincide" in md.lower() or resultado.motivo_rechazo in md


def test_aplicacion_completa_muestra_conteos_y_detalle(tmp_path: Path):
    (tmp_path / "a.mkv").write_bytes(b"contenido a")
    (tmp_path / "b.mkv").write_bytes(b"contenido b")
    plan = generar_plan_renombrado(
        [_op("a.mkv", "A2.mkv"), _op("b.mkv", "B2.mkv")], inventory_hash="h", authorized_root=tmp_path,
    )
    resultado = aplicar_plan(plan, tmp_path, plan.frase_autorizacion_esperada(), inventory_hash_actual="h")

    md = resultado_aplicacion_a_markdown(resultado)

    assert resultado.transaction_id in md
    assert "aplicada" in md
    assert "A2.mkv" in md
    assert "B2.mkv" in md
    assert "Siguiente decisión segura" in md
    assert resultado.journal_path is not None
    assert resultado.journal_path in md


def test_reversion_no_encontrada(tmp_path: Path):
    from alpardi_media_manager.transactions.engine import RollbackResult
    resultado = RollbackResult(transaction_id="tx_no_existe", encontrada=False)
    md = resultado_reversion_a_markdown(resultado)
    assert "no encontrada" in md.lower()
    assert "tx_no_existe" in md


def test_reversion_completa_real(tmp_path: Path):
    (tmp_path / "a.mkv").write_bytes(b"contenido original")
    plan = generar_plan_renombrado([_op("a.mkv", "b.mkv")], inventory_hash="h", authorized_root=tmp_path)
    aplicado = aplicar_plan(plan, tmp_path, plan.frase_autorizacion_esperada(), inventory_hash_actual="h")

    resultado = revertir_transaccion(aplicado.transaction_id, tmp_path)  # type: ignore[arg-type]
    md = resultado_reversion_a_markdown(resultado)

    assert "✅" in md
    assert "b.mkv" in md  # aparece como "origen" de la reversión (destino de la aplicación)
    assert "a.mkv" in md
    assert "Atención" not in md  # no debe aparecer el aviso si la reversión fue completa


def test_reversion_parcial_incluye_aviso(tmp_path: Path):
    (tmp_path / "a.mkv").write_bytes(b"contenido a")
    (tmp_path / "b.mkv").write_bytes(b"contenido b")
    plan = generar_plan_renombrado(
        [_op("a.mkv", "A2.mkv"), _op("b.mkv", "B2.mkv")], inventory_hash="h", authorized_root=tmp_path,
    )
    aplicado = aplicar_plan(plan, tmp_path, plan.frase_autorizacion_esperada(), inventory_hash_actual="h")
    (tmp_path / "B2.mkv").unlink()  # provoca un error de reversión real en una de las dos

    resultado = revertir_transaccion(aplicado.transaction_id, tmp_path)  # type: ignore[arg-type]
    md = resultado_reversion_a_markdown(resultado)

    assert "⚠️" in md
    assert "Atención" in md
