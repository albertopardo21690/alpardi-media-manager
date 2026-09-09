from alpardi_media_manager.policies.naming import (
    EpisodeNamingInput,
    MovieNamingInput,
    cargar_politicas,
    proponer_archivo_episodio,
    proponer_archivo_pelicula,
    proponer_carpeta_pelicula,
    proponer_carpeta_temporada,
)


def test_cargar_politicas_reales_del_proyecto():
    """Carga el config/naming-policies.yaml real del repo -- si esto falla, el fichero de
    configuración que se documentó en la Fase 2 tiene un error real de sintaxis o de ruta."""
    politicas = cargar_politicas()
    assert "movies" in politicas
    assert "tv_shows" in politicas


def test_carpeta_pelicula_sin_id_ni_edicion():
    entrada = MovieNamingInput(title="7 minutos", year=2009)
    assert proponer_carpeta_pelicula(entrada) == "7 minutos (2009)"


def test_carpeta_pelicula_con_id_tmdb():
    entrada = MovieNamingInput(title="Blade Runner", year=1982, external_id_namespace="tmdb", external_id_value="78")
    assert proponer_carpeta_pelicula(entrada) == "Blade Runner (1982) {tmdb-78}"


def test_carpeta_pelicula_con_id_y_edicion_combinados():
    """Coincide exactamente con el ejemplo del propio encargo (docs/PLEX_RULES.md)."""
    entrada = MovieNamingInput(
        title="Blade Runner", year=1982, external_id_namespace="tmdb", external_id_value="78",
        edition="Final Cut",
    )
    assert proponer_carpeta_pelicula(entrada) == "Blade Runner (1982) {tmdb-78} {edition-Final Cut}"


def test_archivo_pelicula_con_sufijo_tecnico():
    entrada = MovieNamingInput(
        title="Blade Runner", year=1982, external_id_namespace="tmdb", external_id_value="78",
        edition="Final Cut", technical_suffix="2160p HEVC HDR10",
    )
    nombre = proponer_archivo_pelicula(entrada, ".mkv")
    assert nombre == "Blade Runner (1982) {tmdb-78} {edition-Final Cut} - 2160p HEVC HDR10.mkv"


def test_archivo_pelicula_sin_sufijo_tecnico_no_deja_guion_colgando():
    """Sin technical_suffix (versión única), no debe quedar '... - .mkv' con un guion vacío."""
    entrada = MovieNamingInput(title="7 minutos", year=2009)
    nombre = proponer_archivo_pelicula(entrada, ".mkv")
    assert nombre == "7 minutos (2009).mkv"
    assert " - .mkv" not in nombre


def test_carpeta_temporada_normal():
    assert proponer_carpeta_temporada(1) == "Season 01"
    assert proponer_carpeta_temporada(12) == "Season 12"


def test_carpeta_temporada_1992_cuatro_digitos():
    """Caso real de Ceremonias Olímpicas -- el formato '{season:02d}' de Python no trunca un
    número de más de 2 dígitos, simplemente no rellena de más -- debe dar '1992', no '92' ni
    fallar."""
    assert proponer_carpeta_temporada(1992) == "Season 1992"


def test_carpeta_temporada_cero_es_specials():
    assert proponer_carpeta_temporada(0) == "Season 00"


def test_archivo_episodio_simple():
    entrada = EpisodeNamingInput(
        show_title="Band of Brothers", year=2001, season=1, episode_start=1, episode_title="Currahee",
    )
    nombre = proponer_archivo_episodio(entrada, ".mkv")
    assert nombre == "Band of Brothers (2001) - s01e01 - Currahee.mkv"


def test_archivo_episodio_multi():
    entrada = EpisodeNamingInput(
        show_title="ShowName", year=2020, season=2, episode_start=5, episode_end=6,
        episode_title="Optional_Info",
    )
    nombre = proponer_archivo_episodio(entrada, ".mkv")
    assert nombre == "ShowName (2020) - s02e05-e06 - Optional_Info.mkv"


def test_archivo_episodio_sin_titulo_no_deja_guion_colgando():
    entrada = EpisodeNamingInput(show_title="Serie", year=2020, season=3, episode_start=10)
    nombre = proponer_archivo_episodio(entrada, ".mkv")
    assert nombre == "Serie (2020) - s03e10.mkv"
    assert nombre.count(" - ") == 1


def test_archivo_episodio_ceremonias_olimpicas():
    entrada = EpisodeNamingInput(
        show_title="Ceremonias Olímpicas", year=1992, season=1992, episode_start=1,
        episode_title="Ceremonia Inaugural",
    )
    nombre = proponer_archivo_episodio(entrada, ".mp4")
    assert nombre == "Ceremonias Olímpicas (1992) - s1992e01 - Ceremonia Inaugural.mp4"
