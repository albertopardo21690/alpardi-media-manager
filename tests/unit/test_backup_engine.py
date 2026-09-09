"""crear_backup nunca toca la colección multimedia -- solo plans/journals/reports/config reales
del propio proyecto (regla explícita de docs/BACKUP_RESTORE.md). verificar_backup siempre
recalcula el hash y extrae de verdad, nunca confía en que el fichero exista sin más."""
from datetime import UTC, datetime
from pathlib import Path

from alpardi_media_manager.backup.engine import crear_backup, verificar_backup

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
