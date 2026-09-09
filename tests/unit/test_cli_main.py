import json
import uuid
from pathlib import Path

import pytest

from alpardi_media_manager.cli.main import (
    cmd_apply,
    cmd_export,
    cmd_inventory_scan,
    cmd_plan_rename,
    cmd_plex_inspect,
    cmd_rollback,
    main,
)
from alpardi_media_manager.planning.plan import RenameOperation, generar_plan_renombrado
from alpardi_media_manager.transactions.engine import aplicar_plan


def _op(source: str, destino: str, size: int = 1000) -> RenameOperation:
    return RenameOperation(item_id=uuid.uuid4(), source_path=source, destination_path=destino, size_bytes=size)


# --- inventory scan --------------------------------------------------------------------------

def test_inventory_scan_content_type_invalido(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    codigo = cmd_inventory_scan(str(tmp_path), "lib", "tipo_que_no_existe", as_json=False)
    assert codigo == 1
    assert "inválido" in capsys.readouterr().err


def test_inventory_scan_raiz_inexistente(capsys: pytest.CaptureFixture[str]):
    codigo = cmd_inventory_scan("/ruta/que/no/existe/de/verdad", "lib", "movie", as_json=False)
    assert codigo == 1
    assert "no existe" in capsys.readouterr().err


def test_inventory_scan_real_con_ficheros_sinteticos(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    d = tmp_path / "Pelicula (2020)"
    d.mkdir()
    (d / "Pelicula (2020).mkv").write_bytes(b"contenido de prueba")

    codigo = cmd_inventory_scan(str(tmp_path), "lib-movies", "movie", as_json=True)
    assert codigo == 0
    salida = json.loads(capsys.readouterr().out)
    assert salida["total"] == 1
    assert "Pelicula (2020)" in salida["items"][0]["path"]


# --- export ------------------------------------------------------------------------------------

def test_export_a_fichero(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    d = tmp_path / "biblioteca"
    d.mkdir()
    (d / "a.mkv").write_bytes(b"x")
    destino = tmp_path / "informe.csv"

    codigo = cmd_export(str(d), "lib", "movie", "csv", str(destino))
    assert codigo == 0
    assert destino.exists()
    assert "a.mkv" in destino.read_text(encoding="utf-8")
    assert "Exportado" in capsys.readouterr().out


def test_export_a_stdout_cuando_no_hay_output(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    (tmp_path / "a.mkv").write_bytes(b"x")
    codigo = cmd_export(str(tmp_path), "lib", "movie", "md", None)
    assert codigo == 0
    assert "a.mkv" in capsys.readouterr().out


# --- rollback ------------------------------------------------------------------------------------

def test_rollback_transaccion_inexistente(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    codigo = cmd_rollback("tx_no_existe", str(tmp_path), as_json=False)
    assert codigo == 1
    assert "no encontrada" in capsys.readouterr().out.lower()


def test_rollback_real_completo(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    (tmp_path / "a.mkv").write_bytes(b"contenido original")
    plan = generar_plan_renombrado([_op("a.mkv", "b.mkv")], inventory_hash="h", authorized_root=tmp_path)
    aplicado = aplicar_plan(plan, tmp_path, plan.frase_autorizacion_esperada(), inventory_hash_actual="h")
    assert aplicado.transaction_id is not None

    codigo = cmd_rollback(aplicado.transaction_id, str(tmp_path), as_json=True)
    assert codigo == 0
    salida = json.loads(capsys.readouterr().out)
    assert salida["completa"] is True
    assert (tmp_path / "a.mkv").read_bytes() == b"contenido original"


# --- plan rename / apply: el flujo real de dos procesos separados ------------------------------

def test_plan_rename_rechaza_content_type_no_movie(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    codigo = cmd_plan_rename(str(tmp_path), "lib", "tv_episode", None, as_json=False)
    assert codigo == 1
    assert "movie" in capsys.readouterr().err


def test_plan_rename_propone_nombre_canonico(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    (tmp_path / "7 minutos (2009).mkv").write_bytes(b"contenido de prueba")

    codigo = cmd_plan_rename(str(tmp_path), "lib-movies", "movie", None, as_json=True)
    assert codigo == 0
    plan_json = json.loads(capsys.readouterr().out)
    assert plan_json["total_operations"] == 1
    assert plan_json["operations"][0]["destination_path"] == "7 minutos (2009)/7 minutos (2009).mkv"


def test_plan_rename_salta_nombres_que_no_se_pueden_interpretar(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    (tmp_path / "sin_formato_reconocible.mkv").write_bytes(b"x")
    codigo = cmd_plan_rename(str(tmp_path), "lib", "movie", None, as_json=False)
    assert codigo == 0
    salida = capsys.readouterr().out
    assert "no se pudieron interpretar" in salida


def test_plan_rename_no_propone_nada_si_ya_esta_en_formato_canonico(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    d = tmp_path / "7 minutos (2009)"
    d.mkdir()
    (d / "7 minutos (2009).mkv").write_bytes(b"x")

    codigo = cmd_plan_rename(str(tmp_path), "lib", "movie", None, as_json=True)
    assert codigo == 0
    assert json.loads(capsys.readouterr().out)["total_operations"] == 0


def test_apply_end_to_end_dos_procesos_simulados(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    """El caso de uso real: `plan rename` guarda el plan en disco, y `apply` lo carga y lo aplica
    en una invocación completamente separada -- sin compartir ningún objeto Python en memoria,
    solo el fichero JSON, tal como pasaría entre dos ejecuciones reales de la CLI."""
    (tmp_path / "7 minutos (2009).mkv").write_bytes(b"contenido real de la pelicula")
    plan_json_path = tmp_path / "plan.json"

    codigo = cmd_plan_rename(str(tmp_path), "lib", "movie", str(plan_json_path), as_json=True)
    assert codigo == 0
    plan_datos = json.loads(capsys.readouterr().out)
    assert plan_json_path.exists()

    frase = f"AUTORIZO APLICAR PLAN {plan_datos['plan_id']} SOBRE {plan_datos['total_operations']} ELEMENTOS"
    codigo = cmd_apply(str(plan_json_path), str(tmp_path), "lib", "movie", frase, as_json=True)
    resultado = json.loads(capsys.readouterr().out)

    assert codigo == 0
    assert resultado["estado"] == "completada"
    destino = tmp_path / "7 minutos (2009)" / "7 minutos (2009).mkv"
    assert destino.read_bytes() == b"contenido real de la pelicula"
    assert not (tmp_path / "7 minutos (2009).mkv").exists()


def test_apply_rechaza_si_el_archivo_cambio_entre_plan_y_apply(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    """Regla del encargo: si el inventario cambió, el plan expira -- probado con el flujo real de
    dos invocaciones separadas de la CLI, no solo a nivel de planning/plan.py."""
    (tmp_path / "7 minutos (2009).mkv").write_bytes(b"contenido original")
    plan_json_path = tmp_path / "plan.json"
    cmd_plan_rename(str(tmp_path), "lib", "movie", str(plan_json_path), as_json=True)
    plan_datos = json.loads(capsys.readouterr().out)

    # El archivo cambia DESPUÉS de generar el plan, antes de aplicar.
    (tmp_path / "7 minutos (2009).mkv").write_bytes(b"contenido modificado, otro tamano")

    frase = f"AUTORIZO APLICAR PLAN {plan_datos['plan_id']} SOBRE {plan_datos['total_operations']} ELEMENTOS"
    codigo = cmd_apply(str(plan_json_path), str(tmp_path), "lib", "movie", frase, as_json=False)
    assert codigo == 1
    assert "expirado" in capsys.readouterr().out.lower()
    # No se ha tocado nada -- el archivo modificado sigue en su sitio, con el nombre original.
    assert (tmp_path / "7 minutos (2009).mkv").read_bytes() == b"contenido modificado, otro tamano"


def test_apply_fichero_de_plan_inexistente(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    codigo = cmd_apply(str(tmp_path / "no_existe.json"), str(tmp_path), "lib", "movie", "frase", as_json=False)
    assert codigo == 1
    assert "No existe" in capsys.readouterr().err


# --- plex inspect: solo el camino de error, sin red (el camino real está en integration/) ------

def test_plex_inspect_sin_token(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]):
    monkeypatch.setattr("alpardi_media_manager.cli.main.leer_plex_token", lambda: "")
    codigo = cmd_plex_inspect(as_json=False)
    assert codigo == 1
    assert "token" in capsys.readouterr().err.lower()


# --- main(): el parser conecta bien los subcomandos --------------------------------------------

def test_main_dispatch_inventory_scan(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    (tmp_path / "a.mkv").write_bytes(b"x")
    codigo = main(["inventory", "scan", str(tmp_path), "--library-id", "lib", "--content-type", "movie", "--json"])
    assert codigo == 0
    assert json.loads(capsys.readouterr().out)["total"] == 1


def test_main_dispatch_export(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    (tmp_path / "a.mkv").write_bytes(b"x")
    codigo = main(["export", str(tmp_path), "--library-id", "lib", "--content-type", "movie", "--format", "json"])
    assert codigo == 0
    assert json.loads(capsys.readouterr().out)["total"] == 1


def test_main_sin_subcomando_falla_con_argparse(capsys: pytest.CaptureFixture[str]):
    with pytest.raises(SystemExit):
        main([])
