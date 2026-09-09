"""Pruebas de integración reales -- sin mocks, contra el Plex y el NAS de verdad. Solo lectura
en todos los casos (echo remoto por SSH, GET a la raíz de la API de Plex). Si el entorno no tiene
acceso real (p.ej. CI sin red), se marcan como skip explícito, nunca como falso positivo."""
from __future__ import annotations

import shutil

import pytest

from alpardi_media_manager.cli.checks import (
    CheckStatus,
    check_nas_ssh_reachable,
    check_plex_reachable,
)
from alpardi_media_manager.cli.config import leer_plex_token, nas_ssh_host, plex_base_url

pytestmark = pytest.mark.integration


def test_plex_real_es_alcanzable():
    token = leer_plex_token()
    if not token:
        pytest.skip("sin token de Plex disponible en este entorno")
    resultado = check_plex_reachable(plex_base_url(), token)
    assert resultado.status == CheckStatus.OK, resultado.detail


def test_nas_real_es_alcanzable_por_ssh():
    if not shutil.which("ssh"):
        pytest.skip("sin cliente ssh en este entorno")
    resultado = check_nas_ssh_reachable(nas_ssh_host())
    assert resultado.status == CheckStatus.OK, resultado.detail
