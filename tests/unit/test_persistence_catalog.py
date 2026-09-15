"""persistence/catalog.py -- upsert real sobre SQLite + reconstrucción de InventoryItem reales.
SQLite real en tmp_path en todos los tests, nunca unittest.mock sobre sqlite3 (regla del proyecto).
"""
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest

from alpardi_media_manager.domain.models import ContentType, Fingerprint, InventoryItem
from alpardi_media_manager.domain.states import ItemState
from alpardi_media_manager.inventory.scanner import escanear_directorio
from alpardi_media_manager.persistence.catalog import (
    actualizar_estado,
    listar_items,
    sincronizar_biblioteca,
    sincronizar_items,
)
from alpardi_media_manager.persistence.db import abrir_conexion

_AHORA = datetime(2026, 1, 1, tzinfo=UTC)


def _conn(tmp_path: Path) -> sqlite3.Connection:
    return abrir_conexion(tmp_path / "catalogo.sqlite3")


def _item(
    *,
    current_path: str = "Pelicula (2020)/Pelicula (2020).mkv",
    library_id: str = "lib",
    content_type: ContentType = ContentType.MOVIE,
    extension: str = ".mkv",
    authorized_root: str = "/biblioteca",
    size_bytes: int = 1000,
    quick: str = "abc123",
) -> InventoryItem:
    return InventoryItem(
        library_id=library_id, authorized_root=authorized_root, current_path=current_path,
        extension=extension, content_type=content_type,
        fingerprint=Fingerprint(size_bytes=size_bytes, mtime=_AHORA, quick=quick),
        discovered_at=_AHORA, updated_at=_AHORA,
    )


# --- sincronizar_items: identidad estable + nunca resetear item_state ----------------------------

def test_sincronizar_items_conserva_el_id_estable_entre_dos_syncs(tmp_path: Path) -> None:
    conn = _conn(tmp_path)
    try:
        primer_escaneo = _item(current_path="a.mkv")
        sincronizar_items(conn, [primer_escaneo], _AHORA)
        id_guardado = conn.execute("SELECT id FROM inventory_items").fetchone()["id"]

        # Segundo "escaneo" del MISMO archivo real -- InventoryItem.id es un UUID nuevo cada vez
        # (domain/models.py: default_factory=uuid.uuid4), tal como pasaría con dos invocaciones
        # reales de inventory scan sobre el mismo directorio.
        segundo_escaneo = _item(current_path="a.mkv")
        assert segundo_escaneo.id != primer_escaneo.id
        sincronizar_items(conn, [segundo_escaneo], _AHORA)

        assert conn.execute("SELECT COUNT(*) FROM inventory_items").fetchone()[0] == 1
        id_tras_resync = conn.execute("SELECT id FROM inventory_items").fetchone()["id"]
        assert id_tras_resync == id_guardado
    finally:
        conn.close()


def test_sincronizar_items_nunca_resetea_item_state_de_una_fila_ya_existente(tmp_path: Path) -> None:
    conn = _conn(tmp_path)
    try:
        sincronizar_items(conn, [_item(current_path="a.mkv")], _AHORA)
        fila = conn.execute("SELECT id, item_state FROM inventory_items").fetchone()
        assert fila["item_state"] == "discovered"

        item_id = uuid.UUID(fila["id"])
        actualizar_estado(conn, item_id, ItemState.PARSED, _AHORA)
        actualizar_estado(conn, item_id, ItemState.MATCHED, _AHORA)

        # Re-sync del mismo archivo real (p.ej. un `catalog sync` posterior) -- item_state debe
        # seguir 'matched', nunca resetearse a 'discovered'.
        sincronizar_items(conn, [_item(current_path="a.mkv")], _AHORA)
        fila_tras_resync = conn.execute("SELECT item_state FROM inventory_items").fetchone()
        assert fila_tras_resync["item_state"] == "matched"
    finally:
        conn.close()


def test_sincronizar_items_cuenta_nuevos_y_actualizados_por_separado(tmp_path: Path) -> None:
    conn = _conn(tmp_path)
    try:
        primero = sincronizar_items(conn, [_item(current_path="a.mkv"), _item(current_path="b.mkv")], _AHORA)
        assert (primero.nuevos, primero.actualizados, primero.total) == (2, 0, 2)

        segundo = sincronizar_items(conn, [_item(current_path="a.mkv"), _item(current_path="c.mkv")], _AHORA)
        assert (segundo.nuevos, segundo.actualizados, segundo.total) == (1, 1, 2)
    finally:
        conn.close()


def test_sincronizar_items_preserva_full_sha256_si_el_reescaneo_no_lo_trae(tmp_path: Path) -> None:
    """inventory/fingerprint.py nunca calcula el hash profundo en un escaneo normal -- si ya
    había uno guardado (calculado aparte), un re-sync normal no debe borrarlo con NULL."""
    conn = _conn(tmp_path)
    try:
        sincronizar_items(conn, [_item(current_path="a.mkv")], _AHORA)
        conn.execute(
            "UPDATE inventory_items SET full_sha256 = ?, full_sha256_computed_at = ? "
            "WHERE current_path = 'a.mkv'",
            ("f" * 64, _AHORA.isoformat()),
        )
        conn.commit()

        sincronizar_items(conn, [_item(current_path="a.mkv")], _AHORA)

        fila = conn.execute("SELECT full_sha256 FROM inventory_items").fetchone()
        assert fila["full_sha256"] == "f" * 64
    finally:
        conn.close()


def test_sincronizar_items_calcula_season_episode_derivados_del_nombre(tmp_path: Path) -> None:
    conn = _conn(tmp_path)
    try:
        episodio = _item(
            current_path="Serie (2020) - s02e05.mkv", content_type=ContentType.TV_EPISODE,
        )
        sincronizar_items(conn, [episodio], _AHORA)
        fila = conn.execute(
            "SELECT season_number, episode_number, episode_number_end FROM inventory_items"
        ).fetchone()
        assert (fila["season_number"], fila["episode_number"], fila["episode_number_end"]) == (2, 5, None)
    finally:
        conn.close()


def test_sincronizar_items_multi_episodio_calcula_episode_number_end(tmp_path: Path) -> None:
    conn = _conn(tmp_path)
    try:
        episodio = _item(
            current_path="Serie (2020) - s01e01-e02.mkv", content_type=ContentType.TV_EPISODE,
        )
        sincronizar_items(conn, [episodio], _AHORA)
        fila = conn.execute(
            "SELECT season_number, episode_number, episode_number_end FROM inventory_items"
        ).fetchone()
        assert (fila["season_number"], fila["episode_number"], fila["episode_number_end"]) == (1, 1, 2)
    finally:
        conn.close()


def test_sincronizar_items_nombre_no_interpretable_deja_season_episode_a_null(tmp_path: Path) -> None:
    conn = _conn(tmp_path)
    try:
        sincronizar_items(conn, [_item(current_path="7 minutos (2009).mkv")], _AHORA)
        fila = conn.execute(
            "SELECT season_number, episode_number, episode_number_end FROM inventory_items"
        ).fetchone()
        assert (fila["season_number"], fila["episode_number"], fila["episode_number_end"]) == (None, None, None)
    finally:
        conn.close()


# --- actualizar_estado: única función con permiso de escribir item_state -------------------------

def test_actualizar_estado_rechaza_transicion_no_permitida(tmp_path: Path) -> None:
    conn = _conn(tmp_path)
    try:
        item = _item(current_path="a.mkv")
        sincronizar_items(conn, [item], _AHORA)

        with pytest.raises(ValueError, match="no permitida"):
            actualizar_estado(conn, item.id, ItemState.APPLIED, _AHORA)  # discovered -> applied

        fila = conn.execute("SELECT item_state FROM inventory_items WHERE id = ?", (str(item.id),)).fetchone()
        assert fila["item_state"] == "discovered"  # el UPDATE nunca se llegó a aplicar
    finally:
        conn.close()


def test_actualizar_estado_aplica_una_transicion_permitida(tmp_path: Path) -> None:
    conn = _conn(tmp_path)
    try:
        item = _item(current_path="a.mkv")
        sincronizar_items(conn, [item], _AHORA)

        actualizar_estado(conn, item.id, ItemState.PARSED, _AHORA)

        fila = conn.execute("SELECT item_state FROM inventory_items WHERE id = ?", (str(item.id),)).fetchone()
        assert fila["item_state"] == "parsed"
    finally:
        conn.close()


def test_actualizar_estado_item_inexistente_lanza_value_error(tmp_path: Path) -> None:
    conn = _conn(tmp_path)
    try:
        with pytest.raises(ValueError, match="No existe"):
            actualizar_estado(conn, uuid.uuid4(), ItemState.PARSED, _AHORA)
    finally:
        conn.close()


# --- listar_items: reconstrucción real de InventoryItem ------------------------------------------

def test_listar_items_reconstruye_un_inventory_item_real_con_los_mismos_campos(tmp_path: Path) -> None:
    conn = _conn(tmp_path)
    try:
        original = _item(current_path="a.mkv", size_bytes=12345, quick="huella-real")
        sincronizar_items(conn, [original], _AHORA)

        reconstruidos = listar_items(conn, library_id="lib")
        assert len(reconstruidos) == 1
        item = reconstruidos[0]

        assert item.library_id == original.library_id
        assert item.authorized_root == original.authorized_root
        assert item.current_path == original.current_path
        assert item.extension == original.extension
        assert item.content_type == original.content_type
        assert item.state == ItemState.DISCOVERED
        assert item.fingerprint.size_bytes == 12345
        assert item.fingerprint.quick == "huella-real"
        assert item.fingerprint.full_sha256 is None
        assert item.device_inode is None
        assert item.parent_id is None
        assert item.relation_to_parent is None
    finally:
        conn.close()


def test_listar_items_reconstruye_device_inode_cuando_esta_presente(tmp_path: Path) -> None:
    conn = _conn(tmp_path)
    try:
        sincronizar_items(conn, [_item(current_path="a.mkv")], _AHORA)
        conn.execute(
            "UPDATE inventory_items SET device_id = 7, inode = 42, device_inode_reliable = 1 "
            "WHERE current_path = 'a.mkv'"
        )
        conn.commit()

        item = listar_items(conn, library_id="lib")[0]
        assert item.device_inode is not None
        assert item.device_inode.device_id == 7
        assert item.device_inode.inode == 42
        assert item.device_inode.reliable is True
    finally:
        conn.close()


def test_listar_items_filtra_por_library_content_type_y_state(tmp_path: Path) -> None:
    conn = _conn(tmp_path)
    try:
        pelicula = _item(current_path="a.mkv", content_type=ContentType.MOVIE, library_id="lib-1")
        episodio = _item(current_path="b - s01e01.mkv", content_type=ContentType.TV_EPISODE, library_id="lib-1")
        otra_biblioteca = _item(current_path="c.mkv", content_type=ContentType.MOVIE, library_id="lib-2")
        sincronizar_items(conn, [pelicula, episodio, otra_biblioteca], _AHORA)

        solo_lib_1 = listar_items(conn, library_id="lib-1")
        assert {i.current_path for i in solo_lib_1} == {"a.mkv", "b - s01e01.mkv"}

        solo_movie = listar_items(conn, library_id="lib-1", content_type=ContentType.MOVIE)
        assert [i.current_path for i in solo_movie] == ["a.mkv"]

        fila_ep = conn.execute(
            "SELECT id FROM inventory_items WHERE current_path = 'b - s01e01.mkv'"
        ).fetchone()
        actualizar_estado(conn, uuid.UUID(fila_ep["id"]), ItemState.PARSED, _AHORA)

        solo_parsed = listar_items(conn, library_id="lib-1", state=ItemState.PARSED)
        assert [i.current_path for i in solo_parsed] == ["b - s01e01.mkv"]
    finally:
        conn.close()


def test_listar_items_sin_filtros_devuelve_todo(tmp_path: Path) -> None:
    conn = _conn(tmp_path)
    try:
        sincronizar_items(conn, [_item(current_path="a.mkv"), _item(current_path="b.mkv")], _AHORA)
        assert len(listar_items(conn)) == 2
    finally:
        conn.close()


# --- sincronizar_biblioteca: orquestador fino sobre el scanner real, sin tocarlo -----------------

def test_sincronizar_biblioteca_nunca_escribe_en_el_filesystem_escaneado(tmp_path: Path) -> None:
    biblioteca = tmp_path / "biblioteca"
    biblioteca.mkdir()
    (biblioteca / "a.mkv").write_bytes(b"contenido original")
    conn = _conn(tmp_path)
    try:
        sincronizar_biblioteca(conn, biblioteca, "lib", ContentType.MOVIE, ahora=_AHORA)
        assert (biblioteca / "a.mkv").read_bytes() == b"contenido original"
        assert [p.name for p in biblioteca.iterdir()] == ["a.mkv"]
    finally:
        conn.close()


def test_sincronizar_biblioteca_reproduce_el_mismo_inventario_que_el_escaneo_directo(tmp_path: Path) -> None:
    biblioteca = tmp_path / "biblioteca"
    (biblioteca / "Pelicula Uno (2020)").mkdir(parents=True)
    (biblioteca / "Pelicula Uno (2020)" / "Pelicula Uno (2020).mkv").write_bytes(b"contenido 1")
    (biblioteca / "Pelicula Dos (2021).mkv").write_bytes(b"contenido 2 mas largo de verdad")

    esperado = escanear_directorio(biblioteca, library_id="lib-test", content_type=ContentType.MOVIE)

    conn = _conn(tmp_path)
    try:
        sincronizar_biblioteca(conn, biblioteca, "lib-test", ContentType.MOVIE, ahora=_AHORA)
        obtenido = listar_items(conn, library_id="lib-test")

        assert len(obtenido) == len(esperado) == 2
        por_ruta_esperado = {i.current_path: i for i in esperado}
        por_ruta_obtenido = {i.current_path: i for i in obtenido}
        assert por_ruta_obtenido.keys() == por_ruta_esperado.keys()
        for ruta, item_esperado in por_ruta_esperado.items():
            item_obtenido = por_ruta_obtenido[ruta]
            assert item_obtenido.extension == item_esperado.extension
            assert item_obtenido.content_type == item_esperado.content_type
            assert item_obtenido.fingerprint.size_bytes == item_esperado.fingerprint.size_bytes
            assert item_obtenido.fingerprint.quick == item_esperado.fingerprint.quick
            assert item_obtenido.state == ItemState.DISCOVERED
    finally:
        conn.close()


def test_sincronizar_biblioteca_conserva_created_at_de_libraries_entre_dos_syncs(tmp_path: Path) -> None:
    biblioteca = tmp_path / "biblioteca"
    biblioteca.mkdir()
    (biblioteca / "a.mkv").write_bytes(b"x")
    conn = _conn(tmp_path)
    try:
        sincronizar_biblioteca(conn, biblioteca, "lib", ContentType.MOVIE, ahora=_AHORA)
        creado_1 = conn.execute("SELECT created_at FROM libraries WHERE library_id = 'lib'").fetchone()["created_at"]

        mas_tarde = datetime(2026, 6, 1, tzinfo=UTC)
        sincronizar_biblioteca(conn, biblioteca, "lib", ContentType.MOVIE, ahora=mas_tarde)
        creado_2 = conn.execute("SELECT created_at FROM libraries WHERE library_id = 'lib'").fetchone()["created_at"]

        assert creado_1 == creado_2
        assert conn.execute("SELECT COUNT(*) FROM libraries").fetchone()[0] == 1
    finally:
        conn.close()
