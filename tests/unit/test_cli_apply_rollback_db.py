"""Fase 8: `apply`/`rollback` ganan un `--db` OPCIONAL (default `None`, no toca SQLite en
absoluto). Este fichero cubre:

- El flujo real de extremo a extremo CON `--db`: `catalog sync` -> `plan rename` -> `apply --db`
  -> `catalog list` muestra `current_path`/`item_state` ya reconciliados; luego `rollback --db`
  revierte ambos.
- Regresión explícita SIN `--db`: el comportamiento (salida, journal, ficheros movidos) es
  idéntico al de antes de la Fase 8.
- La decisión de diseño de que un fallo de reconciliación NUNCA oculta ni invalida un
  apply/rollback ya ocurrido de verdad en disco (ver docstring de `_reconciliar_tras_apply` en
  `cli/main.py`).
- La validación de entrada de `rollback --db` sin `--library-id`.
"""
import json
from pathlib import Path

import pytest

from alpardi_media_manager.cli.main import (
    cmd_apply,
    cmd_catalog_list,
    cmd_catalog_sync,
    cmd_plan_rename,
    cmd_rollback,
    main,
)


def _crear_pelicula(tmp_path: Path) -> None:
    (tmp_path / "7 minutos (2009).mkv").write_bytes(b"contenido real de la pelicula")


def _preparar_plan(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> tuple[Path, dict[str, object]]:
    if not (tmp_path / "7 minutos (2009).mkv").exists():
        _crear_pelicula(tmp_path)
    plan_json_path = tmp_path / "plan.json"
    codigo = cmd_plan_rename(str(tmp_path), "lib-e2e", "movie", str(plan_json_path), as_json=True)
    assert codigo == 0
    plan_datos = json.loads(capsys.readouterr().out)
    return plan_json_path, plan_datos


def _frase(plan_datos: dict[str, object]) -> str:
    return f"AUTORIZO APLICAR PLAN {plan_datos['plan_id']} SOBRE {plan_datos['total_operations']} ELEMENTOS"


# --- extremo a extremo real, CON --db --------------------------------------------------------

def test_apply_y_rollback_con_db_reconcilian_el_catalogo_de_extremo_a_extremo(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    ruta_db = str(tmp_path / "catalogo.sqlite3")
    _crear_pelicula(tmp_path)

    codigo = cmd_catalog_sync(str(tmp_path), "lib-e2e", "movie", ruta_db, as_json=True)
    assert codigo == 0
    capsys.readouterr()

    plan_json_path, plan_datos = _preparar_plan(tmp_path, capsys)

    codigo = cmd_apply(str(plan_json_path), str(tmp_path), "lib-e2e", "movie", _frase(plan_datos), True, ruta_db)
    assert codigo == 0
    resultado_apply = json.loads(capsys.readouterr().out)
    assert resultado_apply["estado"] == "completada"

    codigo = cmd_catalog_list("lib-e2e", None, None, ruta_db, as_json=True)
    assert codigo == 0
    catalogo = json.loads(capsys.readouterr().out)
    assert catalogo["total"] == 1
    assert catalogo["items"][0]["path"] == "7 minutos (2009)/7 minutos (2009).mkv"
    assert catalogo["items"][0]["state"] == "applied"

    transaction_id = resultado_apply["transaction_id"]
    assert isinstance(transaction_id, str)
    codigo = cmd_rollback(transaction_id, str(tmp_path), True, ruta_db, "lib-e2e")
    assert codigo == 0
    resultado_rollback = json.loads(capsys.readouterr().out)
    assert resultado_rollback["completa"] is True

    codigo = cmd_catalog_list("lib-e2e", None, None, ruta_db, as_json=True)
    assert codigo == 0
    catalogo_tras_rollback = json.loads(capsys.readouterr().out)
    assert catalogo_tras_rollback["items"][0]["path"] == "7 minutos (2009).mkv"
    assert catalogo_tras_rollback["items"][0]["state"] == "rolled_back"


def test_main_dispatch_apply_y_rollback_con_db_y_library_id(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Igual que el test anterior, pero pasando por `main()` -- confirma que el parser conecta
    bien los flags `--db`/`--library-id` nuevos."""
    ruta_db = str(tmp_path / "catalogo.sqlite3")
    _crear_pelicula(tmp_path)
    main(["catalog", "sync", str(tmp_path), "--library-id", "lib-cli", "--content-type", "movie", "--db", ruta_db, "--json"])
    capsys.readouterr()

    plan_json_path, plan_datos = _preparar_plan(tmp_path, capsys)

    codigo = main([
        "apply", "--plan", str(plan_json_path), "--root", str(tmp_path),
        "--library-id", "lib-cli", "--content-type", "movie",
        "--authorize", _frase(plan_datos), "--db", ruta_db, "--json",
    ])
    assert codigo == 0
    resultado_apply = json.loads(capsys.readouterr().out)

    codigo = main(["catalog", "list", "--library-id", "lib-cli", "--db", ruta_db, "--json"])
    assert codigo == 0
    assert json.loads(capsys.readouterr().out)["items"][0]["state"] == "applied"

    transaction_id = resultado_apply["transaction_id"]
    codigo = main([
        "rollback", "--transaction", transaction_id, "--root", str(tmp_path),
        "--db", ruta_db, "--library-id", "lib-cli", "--json",
    ])
    assert codigo == 0
    assert json.loads(capsys.readouterr().out)["completa"] is True

    codigo = main(["catalog", "list", "--library-id", "lib-cli", "--db", ruta_db, "--json"])
    assert codigo == 0
    assert json.loads(capsys.readouterr().out)["items"][0]["state"] == "rolled_back"


# --- regresión explícita SIN --db -------------------------------------------------------------

def test_apply_sin_db_se_comporta_exactamente_igual_que_antes_de_la_fase_8(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    plan_json_path, plan_datos = _preparar_plan(tmp_path, capsys)

    codigo = cmd_apply(str(plan_json_path), str(tmp_path), "lib", "movie", _frase(plan_datos), as_json=True)
    resultado = json.loads(capsys.readouterr().out)

    assert codigo == 0
    assert resultado["estado"] == "completada"
    destino = tmp_path / "7 minutos (2009)" / "7 minutos (2009).mkv"
    assert destino.read_bytes() == b"contenido real de la pelicula"
    assert not (tmp_path / "7 minutos (2009).mkv").exists()
    # Nunca se creó ningún fichero SQLite -- sin --db, no se toca en absoluto.
    assert not any(tmp_path.rglob("*.sqlite3"))


def test_rollback_sin_db_se_comporta_exactamente_igual_que_antes_de_la_fase_8(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    plan_json_path, plan_datos = _preparar_plan(tmp_path, capsys)
    codigo = cmd_apply(str(plan_json_path), str(tmp_path), "lib", "movie", _frase(plan_datos), as_json=True)
    assert codigo == 0
    resultado_apply = json.loads(capsys.readouterr().out)

    codigo = cmd_rollback(resultado_apply["transaction_id"], str(tmp_path), as_json=True)
    assert codigo == 0
    resultado_rollback = json.loads(capsys.readouterr().out)
    assert resultado_rollback["completa"] is True
    assert (tmp_path / "7 minutos (2009).mkv").read_bytes() == b"contenido real de la pelicula"
    assert not any(tmp_path.rglob("*.sqlite3"))


# --- validación de entrada: rollback --db sin --library-id --------------------------------------

def test_rollback_con_db_sin_library_id_falla_antes_de_tocar_nada(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    ruta_db = str(tmp_path / "catalogo.sqlite3")
    codigo = cmd_rollback("tx_no_existe_de_verdad", str(tmp_path), as_json=False, db_path=ruta_db)
    assert codigo == 1
    assert "--library-id" in capsys.readouterr().err
    # Ni siquiera se llegó a crear la carpeta de journals -- se rechazó antes de intentar nada.
    assert not (tmp_path / ".alpardimedia-journal").exists()
    assert not Path(ruta_db).exists()


# --- decisión de diseño: un fallo de reconciliación NUNCA oculta el resultado real ---------------

def test_apply_con_db_invalida_no_oculta_el_resultado_real_ya_aplicado(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    plan_json_path, plan_datos = _preparar_plan(tmp_path, capsys)

    # Una CARPETA real (no un fichero SQLite) en la ruta de --db -- sqlite3.connect() falla de
    # verdad al abrirla (sqlite3.OperationalError: unable to open database file), sin necesidad de
    # ningún mock.
    ruta_db_invalida = tmp_path / "esto_es_una_carpeta_no_una_bd"
    ruta_db_invalida.mkdir()

    codigo = cmd_apply(
        str(plan_json_path), str(tmp_path), "lib", "movie", _frase(plan_datos), True, str(ruta_db_invalida),
    )
    salida = capsys.readouterr()
    resultado = json.loads(salida.out)

    # El resultado real de la aplicación es idéntico a si no se hubiera pasado --db -- el fallo de
    # reconciliación NUNCA lo oculta ni cambia el código de salida.
    assert codigo == 0
    assert resultado["estado"] == "completada"
    destino = tmp_path / "7 minutos (2009)" / "7 minutos (2009).mkv"
    assert destino.read_bytes() == b"contenido real de la pelicula"
    assert not (tmp_path / "7 minutos (2009).mkv").exists()

    # Pero el fallo real de reconciliación SÍ se avisa fuerte por stderr, nunca en silencio.
    assert "reconciliar" in salida.err.lower()
    assert "catálogo sqlite" in salida.err.lower()


def test_rollback_con_db_invalida_no_oculta_el_resultado_real_ya_revertido(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    plan_json_path, plan_datos = _preparar_plan(tmp_path, capsys)
    codigo = cmd_apply(str(plan_json_path), str(tmp_path), "lib", "movie", _frase(plan_datos), as_json=True)
    assert codigo == 0
    resultado_apply = json.loads(capsys.readouterr().out)

    ruta_db_invalida = tmp_path / "esto_es_una_carpeta_no_una_bd"
    ruta_db_invalida.mkdir()

    codigo = cmd_rollback(
        resultado_apply["transaction_id"], str(tmp_path), True, str(ruta_db_invalida), "lib",
    )
    salida = capsys.readouterr()
    resultado_rollback = json.loads(salida.out)

    assert codigo == 0
    assert resultado_rollback["completa"] is True
    assert (tmp_path / "7 minutos (2009).mkv").read_bytes() == b"contenido real de la pelicula"
    assert "reconciliar" in salida.err.lower()
