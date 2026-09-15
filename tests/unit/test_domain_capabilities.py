import pytest

from alpardi_media_manager.domain.capabilities import (
    CONTENT_TYPES_SOPORTADOS_PARA_PLAN_Y_MATCH,
    verificar_content_type_soportado,
)
from alpardi_media_manager.domain.models import ContentType


def test_movie_esta_soportado():
    verificar_content_type_soportado(ContentType.MOVIE)  # no debe lanzar


def test_tv_episode_esta_soportado():
    verificar_content_type_soportado(ContentType.TV_EPISODE)  # no debe lanzar


@pytest.mark.parametrize("tipo", [
    ContentType.TV_SHOW, ContentType.TV_SEASON, ContentType.MUSIC_ARTIST,
    ContentType.MUSIC_ALBUM, ContentType.MUSIC_TRACK, ContentType.PHOTO,
    ContentType.OTHER_VIDEO, ContentType.EXTRA,
])
def test_content_types_no_soportados_lanzan_value_error(tipo: ContentType):
    with pytest.raises(ValueError, match="aún no soportado"):
        verificar_content_type_soportado(tipo)


def test_conjunto_soportado_es_exactamente_movie_y_tv_episode():
    """Fija el conjunto exacto -- si un día se amplía sin querer (o se olvida ampliar tras
    conectar un content_type nuevo a planning/matching), este test debe romperse a propósito."""
    assert CONTENT_TYPES_SOPORTADOS_PARA_PLAN_Y_MATCH == frozenset({
        ContentType.MOVIE, ContentType.TV_EPISODE,
    })
