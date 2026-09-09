"""Pruebas de integración reales -- sin mocks, contra el Plex real de Alberto. Solo lectura en
todos los casos. Si no hay token disponible en este entorno, se marcan como skip explícito."""
from __future__ import annotations

import pytest

from alpardi_media_manager.config import leer_plex_token, plex_base_url
from alpardi_media_manager.plex.client import PlexClient

pytestmark = pytest.mark.integration


async def _cliente() -> PlexClient | None:
    token = leer_plex_token()
    if not token:
        return None
    return PlexClient(plex_base_url(), token)


async def test_listar_bibliotecas_reales():
    cliente = await _cliente()
    if cliente is None:
        pytest.skip("sin token de Plex disponible en este entorno")
    async with cliente:
        bibliotecas = await cliente.listar_bibliotecas()

    assert len(bibliotecas) > 0
    # El servidor real de Alberto tiene 25 bibliotecas (verificado en la auditoría de Fase 0,
    # 2026-09-09) -- si esto cambia, es una señal real de que algo se creó/borró, no un fallo del
    # test en sí, pero se documenta el número esperado para detectarlo si pasa.
    claves = {b.key for b in bibliotecas}
    assert "3" in claves  # Películas, ya conocida de auditorías anteriores


async def test_snapshot_biblioteca_pequena_real():
    cliente = await _cliente()
    if cliente is None:
        pytest.skip("sin token de Plex disponible en este entorno")
    async with cliente:
        bibliotecas = await cliente.listar_bibliotecas()
        peliculas = next(b for b in bibliotecas if b.key == "3")
        items = await cliente.snapshot_biblioteca(peliculas.key)

    assert len(items) > 0
    assert all(item.rating_key for item in items)
    assert all(item.file_paths for item in items)  # toda película real tiene al menos un archivo


async def test_hay_sesiones_activas_no_lanza_error():
    cliente = await _cliente()
    if cliente is None:
        pytest.skip("sin token de Plex disponible en este entorno")
    async with cliente:
        resultado = await cliente.hay_sesiones_activas()
    assert isinstance(resultado, bool)


async def test_snapshot_item_con_ratingkey_inexistente_lanza_valueerror():
    cliente = await _cliente()
    if cliente is None:
        pytest.skip("sin token de Plex disponible en este entorno")
    async with cliente:
        with pytest.raises(ValueError, match="ratingKey"):
            await cliente.snapshot_item("999999999")
