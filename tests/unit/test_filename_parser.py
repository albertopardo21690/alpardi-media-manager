from alpardi_media_manager.parsers.filename import (
    es_carpeta_temporada,
    parsear_nombre_episodio,
    parsear_nombre_pelicula,
)

# --- Películas -------------------------------------------------------------------------------

def test_pelicula_completa_con_id_y_edicion():
    info = parsear_nombre_pelicula("Blade Runner (1982) {tmdb-78} {edition-Final Cut}")
    assert info is not None
    assert info.title == "Blade Runner"
    assert info.year == 1982
    assert info.external_id_namespace == "tmdb"
    assert info.external_id_value == "78"
    assert info.edition == "Final Cut"


def test_pelicula_solo_titulo_y_ano():
    info = parsear_nombre_pelicula("7 minutos (2009)")
    assert info is not None
    assert info.title == "7 minutos"
    assert info.year == 2009
    assert info.external_id_namespace is None
    assert info.edition is None


def test_pelicula_con_imdb_id():
    info = parsear_nombre_pelicula("Alien (1979) {imdb-tt0078748}")
    assert info is not None
    assert info.external_id_namespace == "imdb"
    assert info.external_id_value == "tt0078748"


def test_pelicula_sin_ano_no_hace_match():
    """El año es obligatorio en el patrón -- sin él, no se debe inventar un match parcial."""
    assert parsear_nombre_pelicula("Una pelicula sin año") is None


def test_pelicula_titulo_con_parentesis_propios():
    """Un título que ya contiene paréntesis (poco común pero real) no debe romper el parseo del
    año final -- se usa el ÚLTIMO grupo (Año) como año real."""
    info = parsear_nombre_pelicula("Alguna Cosa (Rareza) (1995)")
    assert info is not None
    assert info.year == 1995


# --- Episodios ---------------------------------------------------------------------------------

def test_episodio_completo_con_titulo():
    info = parsear_nombre_episodio("Band of Brothers (2001) - s01e01 - Currahee")
    assert info is not None
    assert info.show_title == "Band of Brothers"
    assert info.year == 2001
    assert info.season == 1
    assert info.episode_start == 1
    assert info.episode_title == "Currahee"
    assert not info.is_multi_episode


def test_episodio_multi_episodio():
    info = parsear_nombre_episodio("ShowName - s02e05-e06 - Optional_Info")
    assert info is not None
    assert info.episode_start == 5
    assert info.episode_end == 6
    assert info.is_multi_episode


def test_episodio_sin_ano_ni_titulo_de_episodio():
    info = parsear_nombre_episodio("Serie - s03e10")
    assert info is not None
    assert info.year is None
    assert info.episode_title is None


def test_episodio_ceremonias_olimpicas_ano_como_temporada():
    """Caso real ya establecido en la biblioteca de Alberto: el año hace de número de temporada
    (s1992e01) -- el patrón debe admitir temporadas de hasta 4 dígitos, no solo 1-2."""
    info = parsear_nombre_episodio("Ceremonias Olímpicas - s1992e01 - Ceremonia Inaugural")
    assert info is not None
    assert info.season == 1992
    assert info.episode_start == 1
    assert info.episode_title == "Ceremonia Inaugural"


def test_episodio_case_insensitive_en_s_e():
    """El propio Plex acepta sXXeYY en minúscula (confirmado en docs/SOURCES.md) -- el parser
    debe aceptar también S/E en mayúscula por si el archivo real las trae así."""
    info = parsear_nombre_episodio("Serie - S01E01 - Titulo")
    assert info is not None
    assert info.season == 1


def test_nombre_de_pelicula_no_hace_match_como_episodio():
    assert parsear_nombre_episodio("Blade Runner (1982)") is None


# --- Carpetas de temporada -----------------------------------------------------------------

def test_season_carpeta_normal():
    assert es_carpeta_temporada("Season 01") == 1
    assert es_carpeta_temporada("Season 1992") == 1992


def test_season_00_es_especiales():
    assert es_carpeta_temporada("Season 00") == 0


def test_specials_alias_devuelve_cero():
    assert es_carpeta_temporada("Specials") == 0
    assert es_carpeta_temporada("specials") == 0  # no distingue mayúsculas en el alias


def test_season_en_espanol_no_es_valido():
    """'Season' debe ir literal incluso en contenido en español -- confirmado en
    docs/SOURCES.md. 'Temporada 01' NO debe reconocerse como carpeta de temporada válida."""
    assert es_carpeta_temporada("Temporada 01") is None


def test_carpeta_no_season_devuelve_none():
    assert es_carpeta_temporada("Extras") is None
