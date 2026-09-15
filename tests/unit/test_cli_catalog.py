"""Subcomando `catalog sync|list|migrate` -- único punto de la CLI con permiso de escribir en el
catálogo SQLite (mismo principio que `apply`/`rollback` para archivos multimedia). No se expone en
mcp/server.py (fuera del alcance de este fichero, ver docs/ARCHITECTURE.md)."""
import json
from pathlib import Path

import pytest

from alpardi_media_manager.cli.main import (
    cmd_catalog_list,
    cmd_catalog_migrate,
    cmd_catalog_sync,
    cmd_inventory_scan,
    main,
)


def _ruta_db(tmp_path: Path) -> str:
    return str(tmp_path / "catalogo.sqlite3")


# --- catalog sync ----------------------------------------------------------------------------

def test_catalog_sync_content_type_invalido(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    codigo = cmd_catalog_sync(str(tmp_path), "lib", "tipo_que_no_existe", _ruta_db(tmp_path), as_json=False)
    assert codigo == 1
    assert "inválido" in capsys.readouterr().err


def test_catalog_sync_raiz_inexistente(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    codigo = cmd_catalog_sync(str(tmp_path / "no_existe"), "lib", "movie", _ruta_db(tmp_path), as_json=False)
    assert codigo == 1
    assert "no existe" in capsys.readouterr().err


def test_catalog_sync_real_con_ficheros_sinteticos(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    d = tmp_path / "biblioteca"
    d.mkdir()
    (d / "Pelicula (2020).mkv").write_bytes(b"contenido de prueba")
    ruta_db = _ruta_db(tmp_path)

    codigo = cmd_catalog_sync(str(d), "lib-movies", "movie", ruta_db, as_json=True)
    assert codigo == 0
    salida = json.loads(capsys.readouterr().out)
    assert salida == {"library_id": "lib-movies", "nuevos": 1, "actualizados": 0, "total": 1}
    assert Path(ruta_db).exists()


def test_catalog_sync_segunda_vez_sobre_el_mismo_fichero_cuenta_como_actualizado(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    d = tmp_path / "biblioteca"
    d.mkdir()
    (d / "Pelicula (2020).mkv").write_bytes(b"contenido de prueba")
    ruta_db = _ruta_db(tmp_path)

    cmd_catalog_sync(str(d), "lib-movies", "movie", ruta_db, as_json=True)
    capsys.readouterr()

    codigo = cmd_catalog_sync(str(d), "lib-movies", "movie", ruta_db, as_json=True)
    assert codigo == 0
    salida = json.loads(capsys.readouterr().out)
    assert salida == {"library_id": "lib-movies", "nuevos": 0, "actualizados": 1, "total": 1}


def test_catalog_sync_usa_database_path_por_defecto_cuando_no_se_pasa_db(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("alpardi_media_manager.cli.main.database_path", lambda: tmp_path / "por-defecto.sqlite3")
    d = tmp_path / "biblioteca"
    d.mkdir()
    (d / "a.mkv").write_bytes(b"x")

    codigo = cmd_catalog_sync(str(d), "lib", "movie", None, as_json=True)
    assert codigo == 0
    assert (tmp_path / "por-defecto.sqlite3").exists()


# --- catalog list ------------------------------------------------------------------------------

def test_catalog_list_content_type_invalido(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    codigo = cmd_catalog_list("lib", "tipo_que_no_existe", None, _ruta_db(tmp_path), as_json=False)
    assert codigo == 1
    assert "inválido" in capsys.readouterr().err


def test_catalog_list_state_invalido(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    codigo = cmd_catalog_list("lib", None, "estado_que_no_existe", _ruta_db(tmp_path), as_json=False)
    assert codigo == 1
    assert "inválido" in capsys.readouterr().err


def test_catalog_list_sin_datos_devuelve_lista_vacia(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    codigo = cmd_catalog_list("lib-vacia", None, None, _ruta_db(tmp_path), as_json=True)
    assert codigo == 0
    salida = json.loads(capsys.readouterr().out)
    assert salida == {"total": 0, "items": []}


def test_catalog_list_markdown_no_json(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    d = tmp_path / "biblioteca"
    d.mkdir()
    (d / "a.mkv").write_bytes(b"x")
    ruta_db = _ruta_db(tmp_path)
    cmd_catalog_sync(str(d), "lib", "movie", ruta_db, as_json=False)
    capsys.readouterr()

    codigo = cmd_catalog_list("lib", None, None, ruta_db, as_json=False)
    assert codigo == 0
    assert "a.mkv" in capsys.readouterr().out


# --- catalog migrate ---------------------------------------------------------------------------

def test_catalog_migrate_aplica_la_migracion_0001(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    ruta_db = _ruta_db(tmp_path)
    codigo = cmd_catalog_migrate(ruta_db, as_json=True)
    assert codigo == 0
    salida = json.loads(capsys.readouterr().out)
    assert salida == {"applied": [1]}


def test_catalog_migrate_segunda_vez_no_aplica_nada(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    ruta_db = _ruta_db(tmp_path)
    cmd_catalog_migrate(ruta_db, as_json=True)
    capsys.readouterr()

    codigo = cmd_catalog_migrate(ruta_db, as_json=True)
    assert codigo == 0
    salida = json.loads(capsys.readouterr().out)
    assert salida == {"applied": []}


def test_catalog_migrate_humano_no_json(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    ruta_db = _ruta_db(tmp_path)
    codigo = cmd_catalog_migrate(ruta_db, as_json=False)
    assert codigo == 0
    assert "aplicada" in capsys.readouterr().out.lower()

    codigo = cmd_catalog_migrate(ruta_db, as_json=False)
    assert codigo == 0
    assert "al día" in capsys.readouterr().out


# --- main(): el parser conecta bien los subcomandos ---------------------------------------------

def test_main_dispatch_catalog_sync_y_list(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    d = tmp_path / "biblioteca"
    d.mkdir()
    (d / "a.mkv").write_bytes(b"x")
    ruta_db = _ruta_db(tmp_path)

    codigo = main([
        "catalog", "sync", str(d), "--library-id", "lib", "--content-type", "movie",
        "--db", ruta_db, "--json",
    ])
    assert codigo == 0
    assert json.loads(capsys.readouterr().out)["total"] == 1

    codigo = main(["catalog", "list", "--library-id", "lib", "--db", ruta_db, "--json"])
    assert codigo == 0
    assert json.loads(capsys.readouterr().out)["total"] == 1


def test_main_dispatch_catalog_migrate(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    ruta_db = _ruta_db(tmp_path)
    codigo = main(["catalog", "migrate", "--db", ruta_db, "--json"])
    assert codigo == 0
    assert json.loads(capsys.readouterr().out) == {"applied": [1]}


# --- verificación end-to-end: `catalog sync` + `catalog list` reproduce EXACTAMENTE lo que
# `inventory scan` devuelve directamente sobre la misma raíz (requisito explícito de la Fase 5) --

def test_catalog_sync_y_list_reproduce_el_mismo_resultado_que_inventory_scan_directo(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    d = tmp_path / "biblioteca-prueba"
    (d / "Blade Runner (1982)").mkdir(parents=True)
    (d / "Blade Runner (1982)" / "Blade Runner (1982) {tmdb-78}.mkv").write_bytes(b"contenido pelicula uno" * 10)
    (d / "7 minutos (2009).mkv").write_bytes(b"contenido pelicula dos" * 5)
    (d / "nombre_sin_formato_reconocible.mkv").write_bytes(b"contenido tres")
    ruta_db = _ruta_db(tmp_path)

    codigo = cmd_inventory_scan(str(d), "lib-e2e", "movie", as_json=True)
    assert codigo == 0
    escaneo_directo = json.loads(capsys.readouterr().out)

    codigo = cmd_catalog_sync(str(d), "lib-e2e", "movie", ruta_db, as_json=True)
    assert codigo == 0
    resultado_sync = json.loads(capsys.readouterr().out)
    assert resultado_sync["total"] == escaneo_directo["total"] == 3

    codigo = cmd_catalog_list("lib-e2e", "movie", None, ruta_db, as_json=True)
    assert codigo == 0
    desde_catalogo = json.loads(capsys.readouterr().out)

    assert desde_catalogo["total"] == escaneo_directo["total"]
    rutas_directo = sorted(item["path"] for item in escaneo_directo["items"])
    rutas_catalogo = sorted(item["path"] for item in desde_catalogo["items"])
    assert rutas_catalogo == rutas_directo

    tamanos_directo = sorted(item["size_bytes"] for item in escaneo_directo["items"])
    tamanos_catalogo = sorted(item["size_bytes"] for item in desde_catalogo["items"])
    assert tamanos_catalogo == tamanos_directo

    extensiones_directo = sorted(item["extension"] for item in escaneo_directo["items"])
    extensiones_catalogo = sorted(item["extension"] for item in desde_catalogo["items"])
    assert extensiones_catalogo == extensiones_directo

    # Todo item recién sincronizado por primera vez queda en 'discovered', igual que un
    # InventoryItem recién escaneado (domain/models.py: state por defecto = DISCOVERED).
    assert {item["state"] for item in desde_catalogo["items"]} == {"discovered"}
    assert {item["state"] for item in escaneo_directo["items"]} == {"discovered"}
