from pathlib import Path

from alpardi_media_manager.domain.models import ContentType
from alpardi_media_manager.inventory.scanner import escanear_directorio


def _crear_arbol_pelicula(raiz: Path) -> None:
    d = raiz / "Blade Runner (1982)"
    d.mkdir(parents=True)
    (d / "Blade Runner (1982).mkv").write_bytes(b"contenido de prueba")


def test_encuentra_video_por_extension(tmp_path: Path):
    _crear_arbol_pelicula(tmp_path)
    items = escanear_directorio(tmp_path, library_id="lib-movies", content_type=ContentType.MOVIE)
    assert len(items) == 1
    assert items[0].current_path == "Blade Runner (1982)/Blade Runner (1982).mkv"


def test_ignora_extensiones_no_reconocidas(tmp_path: Path):
    d = tmp_path / "Pelicula"
    d.mkdir()
    (d / "Pelicula.mkv").write_bytes(b"x")
    (d / "Pelicula.nfo").write_text("<movie/>")
    (d / "poster.jpg").write_bytes(b"x")
    (d / "readme.txt").write_text("nota")

    items = escanear_directorio(tmp_path, library_id="lib", content_type=ContentType.MOVIE)
    assert len(items) == 1
    assert items[0].extension == ".mkv"


def test_excluye_carpetas_ocultas_y_at_eadir(tmp_path: Path):
    (tmp_path / "@eaDir").mkdir()
    (tmp_path / "@eaDir" / "no_deberia_aparecer.mkv").write_bytes(b"x")
    (tmp_path / ".hidden").mkdir()
    (tmp_path / ".hidden" / "tampoco.mkv").write_bytes(b"x")
    (tmp_path / "Real").mkdir()
    (tmp_path / "Real" / "si.mkv").write_bytes(b"x")

    items = escanear_directorio(tmp_path, library_id="lib", content_type=ContentType.MOVIE)
    assert len(items) == 1
    assert items[0].current_path == "Real/si.mkv"


def test_current_path_es_relativo_a_la_raiz_no_absoluto(tmp_path: Path):
    _crear_arbol_pelicula(tmp_path)
    items = escanear_directorio(tmp_path, library_id="lib", content_type=ContentType.MOVIE)
    assert not Path(items[0].current_path).is_absolute()


def test_no_sigue_symlink_que_escapa_de_la_raiz(tmp_path: Path):
    """Regla de seguridad del encargo: nunca escapar de la raíz autorizada, ni siquiera vía
    enlace simbólico."""
    raiz = tmp_path / "biblioteca"
    raiz.mkdir()
    fuera = tmp_path / "fuera_de_la_biblioteca"
    fuera.mkdir()
    (fuera / "secreto.mkv").write_bytes(b"no deberia inventariarse")

    enlace = raiz / "enlace_sospechoso"
    enlace.symlink_to(fuera, target_is_directory=True)

    items = escanear_directorio(raiz, library_id="lib", content_type=ContentType.MOVIE)
    assert items == []


def test_content_type_se_asigna_segun_lo_pedido(tmp_path: Path):
    d = tmp_path / "Serie"
    d.mkdir()
    (d / "episodio.mkv").write_bytes(b"x")
    items = escanear_directorio(tmp_path, library_id="lib-tv", content_type=ContentType.TV_EPISODE)
    assert items[0].content_type == ContentType.TV_EPISODE


def test_biblioteca_vacia_da_lista_vacia(tmp_path: Path):
    items = escanear_directorio(tmp_path, library_id="lib", content_type=ContentType.MOVIE)
    assert items == []
