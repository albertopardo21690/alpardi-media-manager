"""Tests unitarios directos sobre las funciones del servidor MCP (llamadas como Python normal,
sin pasar por el transporte stdio real -- ese camino real de extremo a extremo ya existe en
`tests/integration/test_mcp_server_real.py`, que lanza el servidor como subproceso real).

Se centra en la Fase 7: el refactor de `match_check`/`plan_rename_preview` para soportar también
`tv_episode`, con el mismo orden de validación que `cli/main.py` (`ContentType(...)` primero,
`verificar_content_type_soportado(...)` después)."""
import json
from pathlib import Path

import pytest

from alpardi_media_manager.mcp.server import match_check, plan_rename_preview

# --- match_check --------------------------------------------------------------------------------

def test_match_check_movie_sin_proveedores_es_needs_review_o_sin_interpretar(tmp_path: Path):
    """Regresión: con content_type='movie' el comportamiento debe ser idéntico al de antes de la
    Fase 7 -- mismo resultado, mismo formato."""
    (tmp_path / "7 minutos (2009).mkv").write_bytes(b"x")
    (tmp_path / "nombre_raro.mkv").write_bytes(b"x")

    resultado = match_check(str(tmp_path), "lib", "movie")

    assert resultado["total"] == 2
    estados = {r["state"] for r in resultado["results"]}
    assert estados <= {"needs_review", "sin_interpretar"}


def test_match_check_tv_episode_da_resultados_de_matching_reales(tmp_path: Path):
    """Test nuevo de la Fase 7: tv_episode ahora funciona vía `verificar_coincidencias_episodio`."""
    (tmp_path / "Band of Brothers (2001) - s01e01 - Currahee.mkv").write_bytes(b"x")

    resultado = match_check(str(tmp_path), "lib-tv", "tv_episode")

    assert resultado["total"] == 1
    assert resultado["results"][0]["state"] == "needs_review"
    assert resultado["results"][0]["reasons"] == ["ningun_candidato_con_ano_coincidente"]


def test_match_check_content_type_invalido_da_mensaje_de_valor_no_valido(tmp_path: Path):
    """Un valor que no es un `ContentType` real debe distinguirse de uno válido pero no soportado
    (bug real corregido en la Fase 7: antes ambos casos se comparaban con el string crudo)."""
    with pytest.raises(ValueError, match="inválido") as exc_info:
        match_check(str(tmp_path), "lib", "disparate")
    assert "aún no soportado" not in str(exc_info.value)


def test_match_check_content_type_valido_pero_no_soportado_da_mensaje_distinto(tmp_path: Path):
    with pytest.raises(ValueError, match="aún no soportado") as exc_info:
        match_check(str(tmp_path), "lib", "music_track")
    assert "inválido" not in str(exc_info.value)


# --- plan_rename_preview -------------------------------------------------------------------------

def test_plan_rename_preview_movie_propone_nombre_canonico(tmp_path: Path):
    """Regresión: con content_type='movie' el resultado debe seguir siendo el mismo plan de
    siempre, generado en memoria, sin escribir nada en disco."""
    (tmp_path / "7 minutos (2009).mkv").write_bytes(b"contenido de prueba")
    antes = sorted(p.name for p in tmp_path.rglob("*"))

    resultado = plan_rename_preview(str(tmp_path), "lib-movies", "movie")

    assert resultado["operations"][0]["destination_path"] == "7 minutos (2009)/7 minutos (2009).mkv"
    despues = sorted(p.name for p in tmp_path.rglob("*"))
    assert antes == despues  # sigue sin tocar nada real


def test_plan_rename_preview_tv_episode_genera_ruta_de_tres_niveles(tmp_path: Path):
    """Test nuevo de la Fase 7: tv_episode ahora funciona vía `proponer_operaciones_episodio`,
    componiendo la ruta de 3 niveles (serie/temporada/archivo)."""
    (tmp_path / "Band of Brothers (2001) - s01e01 - Currahee.mkv").write_bytes(b"contenido de prueba")
    antes = sorted(p.name for p in tmp_path.rglob("*"))

    resultado = plan_rename_preview(str(tmp_path), "lib-tv", "tv_episode")

    assert resultado["operations"][0]["destination_path"] == (
        "Band of Brothers (2001)/Season 01/Band of Brothers (2001) - s01e01 - Currahee.mkv"
    )
    despues = sorted(p.name for p in tmp_path.rglob("*"))
    assert antes == despues  # una "vista previa" nunca toca nada real


def test_plan_rename_preview_content_type_invalido_da_mensaje_de_valor_no_valido(tmp_path: Path):
    with pytest.raises(ValueError, match="inválido") as exc_info:
        plan_rename_preview(str(tmp_path), "lib", "disparate")
    assert "aún no soportado" not in str(exc_info.value)


def test_plan_rename_preview_content_type_valido_pero_no_soportado_da_mensaje_distinto(tmp_path: Path):
    with pytest.raises(ValueError, match="aún no soportado") as exc_info:
        plan_rename_preview(str(tmp_path), "lib", "music_track")
    assert "inválido" not in str(exc_info.value)


def test_plan_rename_preview_resultado_es_serializable_a_json(tmp_path: Path):
    """El resultado debe ser JSON-compatible tal cual -- es lo que el transporte MCP real
    serializa como `structured_content` (probado de extremo a extremo por stdio en
    tests/integration/test_mcp_server_real.py)."""
    (tmp_path / "Band of Brothers (2001) - s01e01 - Currahee.mkv").write_bytes(b"x")
    resultado = plan_rename_preview(str(tmp_path), "lib-tv", "tv_episode")
    json.dumps(resultado)  # no debe lanzar
