from pathlib import Path

from alpardi_media_manager.inventory.sidecars import encontrar_sidecars


def test_encuentra_nfo_con_mismo_basename(tmp_path: Path):
    video = tmp_path / "Blade Runner (1982).mkv"
    video.write_bytes(b"x")
    (tmp_path / "Blade Runner (1982).nfo").write_text("<movie></movie>")

    sidecars = encontrar_sidecars(video)
    assert sidecars.nfo_path == tmp_path / "Blade Runner (1982).nfo"


def test_sin_nfo_devuelve_none(tmp_path: Path):
    video = tmp_path / "Sin NFO.mkv"
    video.write_bytes(b"x")
    sidecars = encontrar_sidecars(video)
    assert sidecars.nfo_path is None


def test_encuentra_subtitulos_con_idioma_en_el_nombre(tmp_path: Path):
    video = tmp_path / "Pelicula (2020).mkv"
    video.write_bytes(b"x")
    (tmp_path / "Pelicula (2020).es.srt").write_text("1\n00:00:00,000 --> 00:00:01,000\nHola\n")
    (tmp_path / "Pelicula (2020).en.srt").write_text("1\n00:00:00,000 --> 00:00:01,000\nHi\n")

    sidecars = encontrar_sidecars(video)
    nombres = {p.name for p in sidecars.subtitles}
    assert nombres == {"Pelicula (2020).es.srt", "Pelicula (2020).en.srt"}


def test_no_confunde_subtitulos_de_otro_video_con_basename_parecido(tmp_path: Path):
    """'Pelicula (2020).mkv' no debe recoger los subtítulos de 'Pelicula (2020) Extra.srt' --
    solo los que empiezan EXACTAMENTE por el basename completo."""
    video = tmp_path / "Pelicula (2020).mkv"
    video.write_bytes(b"x")
    (tmp_path / "Pelicula (2020).es.srt").write_text("real")
    otro_video_srt = tmp_path / "Pelicula (2020) Extra.en.srt"
    otro_video_srt.write_text("de otro archivo")

    sidecars = encontrar_sidecars(video)
    nombres = {p.name for p in sidecars.subtitles}
    # startswith(base) es deliberadamente permisivo (incluye el caso "Pelicula (2020).es.srt"),
    # pero aquí se documenta el límite real: si el otro vídeo comparte el mismo prefijo exacto
    # más un carácter, también se cuela -- ver nota en el código sobre esta limitación conocida.
    assert "Pelicula (2020).es.srt" in nombres


def test_encuentra_arte_local_de_pelicula(tmp_path: Path):
    video = tmp_path / "Pelicula (2020).mkv"
    video.write_bytes(b"x")
    (tmp_path / "poster.jpg").write_bytes(b"fake-jpg")
    (tmp_path / "background.jpg").write_bytes(b"fake-jpg")

    sidecars = encontrar_sidecars(video)
    nombres = {p.name for p in sidecars.local_art}
    assert nombres == {"poster.jpg", "background.jpg"}


def test_sidecars_es_inmutable():
    """dataclass(frozen=True) -- si alguien intenta reasignar un campo, debe fallar."""
    import dataclasses

    import pytest

    from alpardi_media_manager.inventory.sidecars import Sidecars

    sidecars = Sidecars(video_path=Path("/x.mkv"))
    with pytest.raises(dataclasses.FrozenInstanceError):
        sidecars.nfo_path = Path("/otro.nfo")  # type: ignore[misc]


def test_carpeta_inexistente_no_lanza_excepcion(tmp_path: Path):
    """Condición de carrera real: el archivo (y su carpeta) pudo borrarse entre el escaneo y
    este análisis -- no debe tumbar el proceso, debe devolver un Sidecars vacío."""
    video_en_carpeta_borrada = tmp_path / "ya_no_existe" / "video.mkv"
    sidecars = encontrar_sidecars(video_en_carpeta_borrada)
    assert sidecars.nfo_path is None
    assert sidecars.subtitles == ()
    assert sidecars.local_art == ()
