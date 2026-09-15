"""crear_backup nunca toca la colección multimedia -- solo plans/journals/reports/config reales
del propio proyecto (regla explícita de docs/BACKUP_RESTORE.md). verificar_backup siempre
recalcula el hash y extrae de verdad, nunca confía en que el fichero exista sin más.

Fase 8: `_snapshot_base_de_datos`/`crear_backup` también capturan un snapshot consistente de
`data/alpardi_media_manager.sqlite3` -- probado con SQLite real en modo WAL, con escrituras
confirmadas (COMMIT real) pero SIN checkpoint manual, para confirmar que el snapshot (vía
`VACUUM INTO`) captura esos datos igualmente, nunca solo lo que ya estuviera en el fichero
principal."""
import sqlite3
import tarfile
from datetime import UTC, datetime
from pathlib import Path

from alpardi_media_manager.backup.engine import (
    _snapshot_base_de_datos,
    crear_backup,
    verificar_backup,
)
from alpardi_media_manager.persistence.db import abrir_conexion

_AHORA = datetime(2026, 9, 9, 12, 0, 0, tzinfo=UTC)


def test_backup_con_cero_archivos_es_valido_y_honesto(tmp_path: Path):
    """plans/journals/reports normalmente no existen todavía -- eso no es un error."""
    resultado = crear_backup(tmp_path, tmp_path / "salida", _AHORA)
    assert resultado.file_count == 0
    assert resultado.archive_path.exists()
    assert resultado.sha256_path.exists()


def test_backup_incluye_plans_journals_reports_y_config_real(tmp_path: Path):
    (tmp_path / "plans").mkdir()
    (tmp_path / "plans" / "plan_1.json").write_text("{}", encoding="utf-8")
    (tmp_path / "journals").mkdir()
    (tmp_path / "journals" / "tx_1.json").write_text("{}", encoding="utf-8")
    (tmp_path / "reports").mkdir()
    (tmp_path / "reports" / "informe.md").write_text("# informe", encoding="utf-8")
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "providers.yaml").write_text("providers: {}", encoding="utf-8")

    resultado = crear_backup(tmp_path, tmp_path / "salida", _AHORA)
    assert resultado.file_count == 4
    assert resultado.total_bytes > 0


def test_backup_excluye_las_plantillas_example_yaml(tmp_path: Path):
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "providers.example.yaml").write_text("providers: {}", encoding="utf-8")

    resultado = crear_backup(tmp_path, tmp_path / "salida", _AHORA)
    assert resultado.file_count == 0


def test_backup_nunca_incluye_la_coleccion_multimedia(tmp_path: Path):
    """Solo plans/journals/reports/config están en la lista de inclusión -- cualquier otra
    carpeta del proyecto (incluida una que simule una biblioteca de medios) queda fuera."""
    (tmp_path / "Peliculas").mkdir()
    (tmp_path / "Peliculas" / "pelicula.mkv").write_bytes(b"contenido real de video")

    resultado = crear_backup(tmp_path, tmp_path / "salida", _AHORA)
    assert resultado.file_count == 0


def test_verificar_backup_real_recien_creado_es_ok(tmp_path: Path):
    (tmp_path / "plans").mkdir()
    (tmp_path / "plans" / "plan_1.json").write_text('{"plan_id": "x"}', encoding="utf-8")

    resultado = crear_backup(tmp_path, tmp_path / "salida", _AHORA)
    verificacion = verificar_backup(resultado.archive_path)
    assert verificacion.ok is True


def test_verificar_backup_detecta_archivo_corrupto(tmp_path: Path):
    (tmp_path / "plans").mkdir()
    (tmp_path / "plans" / "plan_1.json").write_text('{"plan_id": "x"}', encoding="utf-8")
    resultado = crear_backup(tmp_path, tmp_path / "salida", _AHORA)

    # Corrompemos el archivo DESPUÉS de calcular su sha256 real -- simula una copia dañada.
    with resultado.archive_path.open("ab") as f:
        f.write(b"basura-que-rompe-el-hash")

    verificacion = verificar_backup(resultado.archive_path)
    assert verificacion.ok is False
    assert "sha256" in verificacion.detail


def test_verificar_backup_fichero_inexistente(tmp_path: Path):
    verificacion = verificar_backup(tmp_path / "no_existe.tar.gz")
    assert verificacion.ok is False
    assert "No existe" in verificacion.detail


# --- Fase 8: snapshot de data/alpardi_media_manager.sqlite3 ---------------------------------------

def test_snapshot_base_de_datos_none_si_todavia_no_existe(tmp_path: Path):
    """Caso válido, no un error -- nadie ha hecho `catalog sync` todavía."""
    assert _snapshot_base_de_datos(tmp_path, tmp_path / "tmp_snapshot") is None


def test_snapshot_base_de_datos_captura_datos_confirmados_pero_sin_checkpoint_manual(tmp_path: Path):
    ruta_bd = tmp_path / "data" / "alpardi_media_manager.sqlite3"
    conn_escritura = abrir_conexion(ruta_bd)  # activa WAL (ver persistence/db.py)
    conn_escritura.execute(
        "INSERT INTO libraries (library_id, authorized_root, created_at) VALUES (?, ?, ?)",
        ("lib-wal-real", "/biblioteca", "2026-01-01T00:00:00+00:00"),
    )
    conn_escritura.commit()  # COMMIT real -- pero SIN checkpoint manual

    ruta_wal = ruta_bd.with_name(ruta_bd.name + "-wal")
    assert ruta_wal.exists() and ruta_wal.stat().st_size > 0  # confirma que de verdad hay datos sin volcar

    directorio_temporal = tmp_path / "tmp_snapshot"
    directorio_temporal.mkdir()
    # La conexión de escritura se mantiene ABIERTA a propósito mientras se toma el snapshot -- así
    # el -wal no puede haberse checkpointeado por el simple cierre de la conexión.
    snapshot = _snapshot_base_de_datos(tmp_path, directorio_temporal)
    assert snapshot is not None
    assert snapshot.name == "alpardi_media_manager.sqlite3"
    assert snapshot.parent == directorio_temporal

    conn_escritura.close()

    conn_verificacion = sqlite3.connect(snapshot)
    try:
        fila = conn_verificacion.execute(
            "SELECT library_id FROM libraries WHERE library_id = 'lib-wal-real'"
        ).fetchone()
    finally:
        conn_verificacion.close()
    assert fila is not None
    # El snapshot es un fichero consistente de un solo fichero -- sin -wal/-shm propios.
    assert not snapshot.with_name(snapshot.name + "-wal").exists()


def test_crear_backup_sigue_funcionando_sin_base_de_datos_todavia(tmp_path: Path):
    """Regresión: el comportamiento sin `data/alpardi_media_manager.sqlite3` es idéntico a antes
    de la Fase 8 -- 0 archivos sigue siendo válido, y el backup nunca menciona la base de datos."""
    resultado = crear_backup(tmp_path, tmp_path / "salida", _AHORA)
    assert resultado.file_count == 0
    with tarfile.open(resultado.archive_path, "r:gz") as tar:
        assert "data/alpardi_media_manager.sqlite3" not in tar.getnames()


def test_crear_backup_incluye_snapshot_de_la_bd_con_datos_solo_en_el_wal(tmp_path: Path):
    ruta_bd = tmp_path / "data" / "alpardi_media_manager.sqlite3"
    conn = abrir_conexion(ruta_bd)
    conn.execute(
        "INSERT INTO libraries (library_id, authorized_root, created_at) VALUES (?, ?, ?)",
        ("lib-backup-real", "/biblioteca", "2026-01-01T00:00:00+00:00"),
    )
    conn.commit()  # confirmado, pero sin checkpoint manual -- igual que arriba

    resultado = crear_backup(tmp_path, tmp_path / "salida", _AHORA)
    conn.close()

    assert resultado.file_count == 1
    assert resultado.total_bytes > 0

    with tarfile.open(resultado.archive_path, "r:gz") as tar:
        nombres = tar.getnames()
        assert "data/alpardi_media_manager.sqlite3" in nombres  # arcname fijo, nunca el temporal
        assert not any(n.startswith("data/") and n != "data/alpardi_media_manager.sqlite3" for n in nombres)
        extraido = tmp_path / "extraido"
        tar.extractall(extraido, filter="data")

    conn_verif = sqlite3.connect(extraido / "data" / "alpardi_media_manager.sqlite3")
    try:
        fila = conn_verif.execute(
            "SELECT library_id FROM libraries WHERE library_id = 'lib-backup-real'"
        ).fetchone()
    finally:
        conn_verif.close()
    assert fila is not None

    # verificar_backup real (extrae de verdad, no solo comprueba el sha256) sigue en verde.
    verificacion = verificar_backup(resultado.archive_path)
    assert verificacion.ok is True


def test_crear_backup_con_bd_no_afecta_al_conteo_de_plans_journals_reports(tmp_path: Path):
    """El snapshot de la BD se SUMA a los contadores ya existentes -- nunca los reemplaza ni
    interfiere con ellos (mismo principio de whitelist explícita, nunca lista negra)."""
    (tmp_path / "plans").mkdir()
    (tmp_path / "plans" / "plan_1.json").write_text("{}", encoding="utf-8")
    ruta_bd = tmp_path / "data" / "alpardi_media_manager.sqlite3"
    conn = abrir_conexion(ruta_bd)
    conn.close()  # BD vacía pero ya creada -- el fichero .sqlite3 existe de verdad en disco

    resultado = crear_backup(tmp_path, tmp_path / "salida", _AHORA)
    assert resultado.file_count == 2  # 1 plan + 1 snapshot de BD
    with tarfile.open(resultado.archive_path, "r:gz") as tar:
        nombres = set(tar.getnames())
        assert nombres == {"plans/plan_1.json", "data/alpardi_media_manager.sqlite3"}
