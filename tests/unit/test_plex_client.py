"""Tests de parseo puro -- JSON sintético basado en las respuestas REALES capturadas del
servidor de Alberto el 2026-09-09 (ver docs/SOURCES.md si se documenta ahí más adelante), nunca
inventado desde la documentación sin comprobar."""
import httpx
import pytest

from alpardi_media_manager.plex.client import PlexClient, _parsear_biblioteca, _parsear_item


def test_parsear_biblioteca_campos_basicos():
    d = {
        "key": "3", "type": "movie", "title": "Películas", "agent": "tv.plex.agents.movie",
        "scanner": "Plex Movie", "language": "en-US",
        "uuid": "388129f6-cc6a-4783-b65c-32c5347975ed",
        "updatedAt": 1788015894, "createdAt": 1735309767, "scannedAt": 1788015839,
        "Location": [{"id": 128, "path": "/volume1/home/alpardimedia/Videos/Películas"}],
    }
    biblioteca = _parsear_biblioteca(d)
    assert biblioteca.key == "3"
    assert biblioteca.title == "Películas"
    assert biblioteca.agent == "tv.plex.agents.movie"
    assert len(biblioteca.locations) == 1
    assert biblioteca.locations[0].path == "/volume1/home/alpardimedia/Videos/Películas"


def test_parsear_biblioteca_con_varias_rutas():
    d = {
        "key": "26", "type": "show", "title": "ILERNA FP", "agent": "com.plexapp.agents.none",
        "scanner": "Plex TV Series", "language": "es-ES", "uuid": "x",
        "updatedAt": 1, "createdAt": 1, "scannedAt": 1,
        "Location": [{"id": 1, "path": "/ruta/a"}, {"id": 2, "path": "/ruta/b"}],
    }
    biblioteca = _parsear_biblioteca(d)
    assert [loc.path for loc in biblioteca.locations] == ["/ruta/a", "/ruta/b"]


def test_parsear_biblioteca_sin_locations_da_lista_vacia():
    d = {
        "key": "1", "type": "artist", "title": "Vacía", "agent": "a", "scanner": "s",
        "language": "es", "uuid": "x", "updatedAt": 1, "createdAt": 1, "scannedAt": 1,
    }
    biblioteca = _parsear_biblioteca(d)
    assert biblioteca.locations == []


def test_parsear_item_pelicula_basica():
    """Shape real capturado de /library/sections/3/all -- una película nunca vista, sin
    valoración de usuario, sin colecciones. Estos campos son opcionales en la API de Plex, no
    siempre están presentes -- el parseo no debe fallar por su ausencia."""
    d = {
        "ratingKey": "73059", "key": "/library/metadata/73059",
        "guid": "plex://movie/5d77684f5af944001f1fec60",
        "type": "movie", "title": "7 minutos", "year": 2009,
        "addedAt": 1784833471, "updatedAt": 1788021050,
        "Media": [{
            "id": 77905, "Part": [{
                "id": 79785, "file": "/volume1/home/alpardimedia/Videos/Películas/7 Minutos (2009)/7 Minutos (2009).mp4",
                "size": 3595120638, "container": "mp4",
            }],
        }],
    }
    item = _parsear_item(d)
    assert item.rating_key == "73059"
    assert item.title == "7 minutos"
    assert item.year == 2009
    assert item.view_count == 0  # nunca visto -- viewCount no viene en la respuesta real
    assert item.view_offset is None
    assert item.user_rating is None
    assert item.collections == []
    assert item.locked_fields == []
    assert item.file_paths == ["/volume1/home/alpardimedia/Videos/Películas/7 Minutos (2009)/7 Minutos (2009).mp4"]


def test_parsear_item_con_visto_valorado_y_en_coleccion():
    d = {
        "ratingKey": "1", "key": "/library/metadata/1", "type": "movie", "title": "X",
        "addedAt": 1, "updatedAt": 1,
        "viewCount": 3, "viewOffset": 120000, "lastViewedAt": 1788000000, "userRating": 8.5,
        "Collection": [{"tag": "Cine de los 2000"}, {"tag": "Favoritas"}],
        "Field": [{"name": "thumb", "locked": 1}, {"name": "title", "locked": 0}],
        "Media": [],
    }
    item = _parsear_item(d)
    assert item.view_count == 3
    assert item.view_offset == 120000
    assert item.user_rating == 8.5
    assert item.collections == ["Cine de los 2000", "Favoritas"]
    # Solo los campos con locked=1/true se consideran bloqueados -- "title" con locked=0 no cuenta.
    assert item.locked_fields == ["thumb"]


def test_parsear_item_con_varios_media_parts_junta_todas_las_rutas():
    """Una edición con varias versiones técnicas (mismo elemento, varios Media) debe recoger
    TODAS las rutas de archivo, no solo la primera."""
    d = {
        "ratingKey": "1", "key": "/library/metadata/1", "type": "movie", "title": "X",
        "addedAt": 1, "updatedAt": 1,
        "Media": [
            {"id": 1, "Part": [{"id": 1, "file": "/a/1080p.mkv", "size": 1}]},
            {"id": 2, "Part": [{"id": 2, "file": "/a/2160p.mkv", "size": 2}]},
        ],
    }
    item = _parsear_item(d)
    assert item.file_paths == ["/a/1080p.mkv", "/a/2160p.mkv"]


def test_parsear_item_sin_year_es_none():
    """Series/episodios y algunos vídeos personales no siempre tienen 'year' -- opcional."""
    d = {"ratingKey": "1", "key": "/library/metadata/1", "type": "episode", "title": "X", "addedAt": 1, "updatedAt": 1}
    item = _parsear_item(d)
    assert item.year is None


# --- snapshot_item: traducción del 404 real de Plex a un error claro --------------------------

@pytest.mark.asyncio
async def test_snapshot_item_con_404_real_da_valueerror_claro():
    """Verificado contra el servidor real (2026-09-09): un ratingKey inexistente devuelve un 404
    HTML, no JSON con lista vacía -- se simula ese 404 exacto con un transporte falso de httpx
    (sin red real) y se comprueba que el cliente lo traduce a un ValueError legible, en vez de
    dejar escapar la excepción de httpx sin contexto."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="<html><head><title>Not Found</title></head></html>")

    transporte = httpx.MockTransport(handler)
    http_client = httpx.AsyncClient(transport=transporte)
    cliente = PlexClient("http://plex-falso:32400", "token-falso", http_client=http_client)

    with pytest.raises(ValueError, match="999999999"):
        await cliente.snapshot_item("999999999")

    await cliente.cerrar()  # no cierra http_client porque no es "propio" -- se cierra a mano aquí
    await http_client.aclose()
