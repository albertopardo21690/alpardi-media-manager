import json
import uuid
from pathlib import Path

from alpardi_media_manager.planning.plan import RenameOperation, generar_plan_renombrado
from alpardi_media_manager.reports.plan_report import plan_a_json, plan_a_markdown


def _op(source: str, destino: str, size: int = 1000) -> RenameOperation:
    return RenameOperation(item_id=uuid.uuid4(), source_path=source, destination_path=destino, size_bytes=size)


def test_markdown_incluye_datos_basicos(tmp_path: Path):
    plan = generar_plan_renombrado(
        [_op("a.mkv", "Pelicula (2020)/Pelicula (2020).mkv", size=1_500_000_000)],
        inventory_hash="h", authorized_root=tmp_path,
    )
    md = plan_a_markdown(plan)
    assert plan.plan_id in md
    assert "a.mkv" in md
    assert "Pelicula (2020)/Pelicula (2020).mkv" in md
    assert plan.frase_autorizacion_esperada() in md
    assert "1.4 GB" in md  # 1_500_000_000 bytes ~ 1.4 GiB


def test_markdown_plan_sin_conflictos_dice_seguro(tmp_path: Path):
    plan = generar_plan_renombrado([_op("a.mkv", "b.mkv")], inventory_hash="h", authorized_root=tmp_path)
    md = plan_a_markdown(plan)
    assert "✅" in md
    assert "Conflictos" not in md  # no se muestra la sección si no hay ninguno


def test_markdown_plan_con_conflictos_los_lista(tmp_path: Path):
    (tmp_path / "ya_existe.mkv").write_bytes(b"x")
    plan = generar_plan_renombrado([_op("a.mkv", "ya_existe.mkv")], inventory_hash="h", authorized_root=tmp_path)
    md = plan_a_markdown(plan)
    assert "❌" in md
    assert "destination_exists" in md


def test_json_es_valido_y_reproducible(tmp_path: Path):
    plan = generar_plan_renombrado(
        [_op("a.mkv", "b.mkv"), _op("c.mkv", "d.mkv")], inventory_hash="h", authorized_root=tmp_path,
    )
    j1 = plan_a_json(plan)
    j2 = plan_a_json(plan)
    assert j1 == j2  # misma entrada, misma salida byte a byte

    datos = json.loads(j1)
    assert datos["plan_id"] == plan.plan_id
    assert datos["total_operations"] == 2
    assert datos["authorization_phrase"] == plan.frase_autorizacion_esperada()
    assert len(datos["operations"]) == 2
    assert datos["operations"][0]["source_path"] == "a.mkv"


def test_formato_bytes_escalas():
    from alpardi_media_manager.reports.plan_report import _formato_bytes
    assert _formato_bytes(500) == "500 B"
    assert _formato_bytes(2048) == "2.0 KB"
    assert _formato_bytes(1_500_000_000) == "1.4 GB"
