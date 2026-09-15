"""persistence/db.py -- capa más baja: conectar, migrar, checkpoint de backup. Sin domain/."""
import sqlite3
from pathlib import Path

import pytest

from alpardi_media_manager.persistence.db import (
    abrir_conexion,
    aplicar_migraciones,
    checkpoint_para_backup,
)


def _insertar_fila_minima(conn: sqlite3.Connection, **overrides: str) -> None:
    """Inserta una fila de inventory_items con los NOT NULL mínimos -- para probar los CHECK
    constraints reales del esquema sin repetir el INSERT completo en cada test."""
    valores = {
        "id": "id-1", "library_id": "lib", "authorized_root": "/root", "current_path": "a.mkv",
        "extension": ".mkv", "content_type": "movie", "item_state": "discovered",
        "size_bytes": "1", "mtime": "2026-01-01T00:00:00+00:00", "fingerprint_quick": "q",
        "discovered_at": "2026-01-01T00:00:00+00:00", "updated_at": "2026-01-01T00:00:00+00:00",
        "last_seen_at": "2026-01-01T00:00:00+00:00",
    }
    valores.update(overrides)
    columnas = ", ".join(valores)
    placeholders = ", ".join(f":{c}" for c in valores)
    conn.execute(f"INSERT INTO inventory_items ({columnas}) VALUES ({placeholders})", valores)


# --- abrir_conexion / aplicar_migraciones -------------------------------------------------------

def test_abrir_conexion_crea_el_fichero_y_aplica_la_migracion_0001(tmp_path: Path) -> None:
    ruta = tmp_path / "catalogo.sqlite3"
    conn = abrir_conexion(ruta)
    try:
        assert ruta.exists()
        tablas = {
            fila[0] for fila in
            conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        assert {"inventory_items", "libraries", "schema_migrations"} <= tablas
        versiones = [fila[0] for fila in conn.execute("SELECT version FROM schema_migrations")]
        assert versiones == [1]
    finally:
        conn.close()


def test_abrir_conexion_activa_wal_y_foreign_keys(tmp_path: Path) -> None:
    conn = abrir_conexion(tmp_path / "catalogo.sqlite3")
    try:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    finally:
        conn.close()


def test_abrir_conexion_usa_row_factory_sqlite_row(tmp_path: Path) -> None:
    conn = abrir_conexion(tmp_path / "catalogo.sqlite3")
    try:
        conn.execute(
            "INSERT INTO libraries (library_id, authorized_root, created_at) VALUES (?, ?, ?)",
            ("lib", "/root", "2026-01-01T00:00:00+00:00"),
        )
        conn.commit()
        fila = conn.execute("SELECT * FROM libraries").fetchone()
        assert fila["library_id"] == "lib"
        assert fila["authorized_root"] == "/root"
    finally:
        conn.close()


def test_abrir_conexion_dos_veces_sobre_el_mismo_fichero_no_repite_la_migracion(tmp_path: Path) -> None:
    ruta = tmp_path / "catalogo.sqlite3"
    abrir_conexion(ruta).close()
    conn = abrir_conexion(ruta)  # segunda apertura real -- si repitiera el CREATE TABLE, fallaría
    try:
        versiones = [fila[0] for fila in conn.execute("SELECT version FROM schema_migrations")]
        assert versiones == [1]
    finally:
        conn.close()


def test_aplicar_migraciones_es_idempotente_llamada_directa(tmp_path: Path) -> None:
    conn = abrir_conexion(tmp_path / "catalogo.sqlite3")  # ya migró vía auto_migrar=True
    try:
        aplicadas_de_nuevo = aplicar_migraciones(conn)
        assert aplicadas_de_nuevo == []
    finally:
        conn.close()


def test_abrir_conexion_con_auto_migrar_false_no_crea_tablas(tmp_path: Path) -> None:
    conn = abrir_conexion(tmp_path / "catalogo.sqlite3", auto_migrar=False)
    try:
        tablas = {
            fila[0] for fila in
            conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        assert "inventory_items" not in tablas
        aplicadas = aplicar_migraciones(conn)
        assert aplicadas == [1]
    finally:
        conn.close()


# --- CHECK constraints del esquema real (0001_create_inventory_schema.sql) -----------------------

def test_check_rechaza_content_type_invalido(tmp_path: Path) -> None:
    conn = abrir_conexion(tmp_path / "catalogo.sqlite3")
    try:
        with pytest.raises(sqlite3.IntegrityError):
            _insertar_fila_minima(conn, content_type="tipo_que_no_existe")
    finally:
        conn.close()


def test_check_rechaza_item_state_invalido(tmp_path: Path) -> None:
    conn = abrir_conexion(tmp_path / "catalogo.sqlite3")
    try:
        with pytest.raises(sqlite3.IntegrityError):
            _insertar_fila_minima(conn, item_state="estado_que_no_existe")
    finally:
        conn.close()


def test_check_rechaza_relation_to_parent_invalido(tmp_path: Path) -> None:
    conn = abrir_conexion(tmp_path / "catalogo.sqlite3")
    try:
        _insertar_fila_minima(conn, id="id-padre")
        conn.commit()
        with pytest.raises(sqlite3.IntegrityError):
            _insertar_fila_minima(
                conn, id="id-hijo", current_path="b.mkv",
                parent_id="id-padre", relation_to_parent="relacion_inventada",
            )
    finally:
        conn.close()


def test_check_xor_parent_id_y_relation_to_parent_rechaza_parent_sin_relacion(tmp_path: Path) -> None:
    """Mismo XOR que el validador Pydantic de domain/models.py::InventoryItem: parent_id y
    relation_to_parent deben ir ambos presentes o ambos ausentes."""
    conn = abrir_conexion(tmp_path / "catalogo.sqlite3")
    try:
        _insertar_fila_minima(conn, id="padre")
        conn.commit()
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO inventory_items "
                "(id, library_id, authorized_root, current_path, extension, content_type, "
                " item_state, size_bytes, mtime, fingerprint_quick, discovered_at, updated_at, "
                " last_seen_at, parent_id) "
                "VALUES ('hijo', 'lib', '/root', 'b.mkv', '.mkv', 'movie', 'discovered', 1, "
                " '2026-01-01T00:00:00+00:00', 'q', '2026-01-01T00:00:00+00:00', "
                " '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00', 'padre')"
            )
    finally:
        conn.close()


def test_unique_library_id_current_path_rechaza_duplicado(tmp_path: Path) -> None:
    conn = abrir_conexion(tmp_path / "catalogo.sqlite3")
    try:
        _insertar_fila_minima(conn, id="id-1")
        conn.commit()
        with pytest.raises(sqlite3.IntegrityError):
            _insertar_fila_minima(conn, id="id-2")  # mismo library_id + current_path
    finally:
        conn.close()


# --- checkpoint_para_backup ----------------------------------------------------------------------

def test_checkpoint_para_backup_produce_un_fichero_consistente_sin_wal_ni_shm(tmp_path: Path) -> None:
    origen = tmp_path / "origen.sqlite3"
    conn = abrir_conexion(origen)
    conn.execute(
        "INSERT INTO libraries (library_id, authorized_root, created_at) VALUES (?, ?, ?)",
        ("lib", "/root", "2026-01-01T00:00:00+00:00"),
    )
    conn.commit()

    destino = tmp_path / "backups" / "snapshot.sqlite3"
    checkpoint_para_backup(origen, destino)
    conn.close()

    assert destino.exists()
    assert not destino.with_name(destino.name + "-wal").exists()
    assert not destino.with_name(destino.name + "-shm").exists()

    verificacion = sqlite3.connect(destino)
    try:
        filas = verificacion.execute("SELECT library_id, authorized_root FROM libraries").fetchall()
        assert filas == [("lib", "/root")]
    finally:
        verificacion.close()


def test_checkpoint_para_backup_sobrescribe_un_destino_previo(tmp_path: Path) -> None:
    origen = tmp_path / "origen.sqlite3"
    abrir_conexion(origen).close()
    destino = tmp_path / "snapshot.sqlite3"
    destino.write_text("contenido antiguo que no es un sqlite valido")

    checkpoint_para_backup(origen, destino)

    verificacion = sqlite3.connect(destino)
    try:
        tablas = {f[0] for f in verificacion.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert "inventory_items" in tablas
    finally:
        verificacion.close()
