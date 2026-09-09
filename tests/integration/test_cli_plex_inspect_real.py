"""Camino feliz de `alpardi-media plex inspect` -- contra el Plex real de Alberto, sin mocks."""
import json

import pytest

from alpardi_media_manager.cli.main import main
from alpardi_media_manager.config import leer_plex_token

pytestmark = pytest.mark.integration


def test_plex_inspect_real_via_cli(capsys: pytest.CaptureFixture[str]):
    if not leer_plex_token():
        pytest.skip("sin token de Plex disponible en este entorno")

    codigo = main(["plex", "inspect", "--json"])

    assert codigo == 0
    salida = json.loads(capsys.readouterr().out)
    assert len(salida) > 0
    assert any(b["key"] == "3" for b in salida)  # Películas, ya conocida de auditorías anteriores
