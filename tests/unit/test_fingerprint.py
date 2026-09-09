from pathlib import Path

from alpardi_media_manager.inventory.fingerprint import (
    anadir_hash_completo,
    calcular_fingerprint_rapido,
    calcular_hash_completo,
)


def test_mismo_contenido_mismo_quick_hash(tmp_path: Path):
    a = tmp_path / "a.mkv"
    b = tmp_path / "b.mkv"
    a.write_bytes(b"contenido identico de prueba")
    b.write_bytes(b"contenido identico de prueba")
    fp_a = calcular_fingerprint_rapido(a)
    fp_b = calcular_fingerprint_rapido(b)
    assert fp_a.quick == fp_b.quick


def test_contenido_distinto_quick_hash_distinto(tmp_path: Path):
    a = tmp_path / "a.mkv"
    b = tmp_path / "b.mkv"
    a.write_bytes(b"contenido A")
    b.write_bytes(b"contenido B, distinto")
    assert calcular_fingerprint_rapido(a).quick != calcular_fingerprint_rapido(b).quick


def test_size_bytes_correcto(tmp_path: Path):
    f = tmp_path / "x.mkv"
    f.write_bytes(b"0123456789")
    assert calcular_fingerprint_rapido(f).size_bytes == 10


def test_full_hash_no_se_calcula_en_fingerprint_rapido(tmp_path: Path):
    f = tmp_path / "x.mkv"
    f.write_bytes(b"algo")
    fp = calcular_fingerprint_rapido(f)
    assert fp.full_sha256 is None


def test_anadir_hash_completo_no_muta_el_original(tmp_path: Path):
    f = tmp_path / "x.mkv"
    f.write_bytes(b"contenido para hash completo")
    fp_original = calcular_fingerprint_rapido(f)
    fp_con_hash = anadir_hash_completo(fp_original, f)
    assert fp_original.full_sha256 is None  # el original no cambia
    assert fp_con_hash.full_sha256 is not None


def test_hash_completo_es_determinista(tmp_path: Path):
    f = tmp_path / "x.mkv"
    f.write_bytes(b"contenido repetible" * 1000)
    assert calcular_hash_completo(f) == calcular_hash_completo(f)


def test_hash_completo_cubre_todo_el_archivo_no_solo_la_muestra_rapida(tmp_path: Path):
    """Dos archivos con los mismos primeros 64KiB pero distinto final deben dar full hash
    distinto -- si no, el nivel "profundo" no aportaría nada sobre el rápido."""
    a = tmp_path / "a.mkv"
    b = tmp_path / "b.mkv"
    comun = b"x" * 70000  # > _MUESTRA_RAPIDA_BYTES (64KiB)
    a.write_bytes(comun + b"final-A")
    b.write_bytes(comun + b"final-B")
    assert calcular_hash_completo(a) != calcular_hash_completo(b)
