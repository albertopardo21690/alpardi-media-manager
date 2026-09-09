"""Prueba de integración real del servidor MCP -- lo lanza como subproceso de verdad por stdio
(el mismo transporte que usará Claude Code) y habla el protocolo real con el SDK oficial cliente,
sin mocks. Además de comprobar que las herramientas de solo lectura funcionan, esta es la prueba
de REGRESIÓN DE SEGURIDAD más importante del propio servidor: confirma que `apply`, `rollback` y
`backup_create` NUNCA aparecen en la lista de herramientas expuestas -- esa es la garantía de que
Claude no puede aplicar un cambio real sobre la colección multimedia sin que Alberto escriba el
comando de la skill correspondiente (ver el docstring de mcp/server.py)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

pytestmark = pytest.mark.integration

_SERVER_BIN = Path(sys.exec_prefix) / "bin" / "alpardi-media-mcp"

_HERRAMIENTAS_ESPERADAS = {
    "doctor", "plex_libraries", "inventory_scan",
    "providers_status", "match_check", "plan_rename_preview",
}
_HERRAMIENTAS_PROHIBIDAS = {"apply", "rollback", "backup_create", "backup_verify"}


def _server_params() -> StdioServerParameters:
    if not _SERVER_BIN.exists():
        pytest.skip(f"binario del servidor MCP no encontrado en {_SERVER_BIN} (¿pip install -e . ejecutado?)")
    return StdioServerParameters(command=str(_SERVER_BIN), args=[])


async def test_lista_de_herramientas_es_exactamente_la_esperada_y_nunca_expone_mutacion():
    async with stdio_client(_server_params()) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        resultado = await session.list_tools()
        nombres = {t.name for t in resultado.tools}

        assert nombres == _HERRAMIENTAS_ESPERADAS
        assert nombres.isdisjoint(_HERRAMIENTAS_PROHIBIDAS)
        for tool in resultado.tools:
            assert tool.annotations is not None
            assert tool.annotations.read_only_hint is True
            assert tool.annotations.destructive_hint is False


async def test_doctor_real_via_mcp():
    async with stdio_client(_server_params()) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        resultado = await session.call_tool("doctor", {})
        assert resultado.is_error is not True
        assert resultado.structured_content is not None
        nombres_check = {c["name"] for c in resultado.structured_content["checks"]}
        assert "python" in nombres_check
        assert "plex" in nombres_check


async def test_inventory_scan_real_via_mcp_con_ficheros_sinteticos(tmp_path: Path):
    (tmp_path / "Pelicula (2020)").mkdir()
    (tmp_path / "Pelicula (2020)" / "Pelicula (2020).mkv").write_bytes(b"contenido de prueba")

    async with stdio_client(_server_params()) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        resultado = await session.call_tool(
            "inventory_scan",
            {"root": str(tmp_path), "library_id": "lib-test", "content_type": "movie"},
        )
        assert resultado.is_error is not True
        assert resultado.structured_content["total"] == 1


async def test_plan_rename_preview_nunca_escribe_nada_en_disco(tmp_path: Path):
    (tmp_path / "7 minutos (2009).mkv").write_bytes(b"contenido")
    antes = sorted(p.name for p in tmp_path.rglob("*"))

    async with stdio_client(_server_params()) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        resultado = await session.call_tool(
            "plan_rename_preview",
            {"root": str(tmp_path), "library_id": "lib-test", "content_type": "movie"},
        )
        assert resultado.is_error is not True
        assert resultado.structured_content["operations"][0]["destination_path"] == "7 minutos (2009)/7 minutos (2009).mkv"

    despues = sorted(p.name for p in tmp_path.rglob("*"))
    assert antes == despues  # ni un solo archivo nuevo, movido o renombrado


async def test_match_check_content_type_no_soportado_es_error_claro(tmp_path: Path):
    async with stdio_client(_server_params()) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        resultado = await session.call_tool(
            "match_check",
            {"root": str(tmp_path), "library_id": "lib", "content_type": "tv_episode"},
        )
        assert resultado.is_error is True
