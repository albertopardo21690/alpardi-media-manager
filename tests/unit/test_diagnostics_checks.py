import subprocess
from unittest.mock import Mock

from alpardi_media_manager.diagnostics.checks import (
    CheckStatus,
    check_binary_present,
    check_nas_ssh_reachable,
    check_plex_reachable,
    check_python_version,
)


def test_python_version_ok_en_314_o_superior():
    resultado = check_python_version()
    assert resultado.status == CheckStatus.OK


def test_binary_present_encuentra_python3():
    """python3 seguro que existe en cualquier entorno donde esto se ejecute."""
    resultado = check_binary_present("python3")
    assert resultado.status == CheckStatus.OK


def test_binary_present_warn_si_no_existe():
    resultado = check_binary_present("un-binario-que-no-existe-de-verdad-12345")
    assert resultado.status == CheckStatus.WARN


def test_plex_sin_token_es_error_sin_llamar_a_la_red():
    runner = Mock()
    resultado = check_plex_reachable("http://x", "", runner=runner)
    assert resultado.status == CheckStatus.ERROR
    runner.assert_not_called()


def test_plex_200_es_ok():
    runner = Mock(return_value=Mock(stdout="200", returncode=0))
    resultado = check_plex_reachable("http://x", "tok", runner=runner)
    assert resultado.status == CheckStatus.OK


def test_plex_401_es_error():
    runner = Mock(return_value=Mock(stdout="401", returncode=0))
    resultado = check_plex_reachable("http://x", "tok-malo", runner=runner)
    assert resultado.status == CheckStatus.ERROR
    assert "401" in resultado.detail


def test_plex_timeout_es_error():
    runner = Mock(side_effect=subprocess.TimeoutExpired(cmd="curl", timeout=10))
    resultado = check_plex_reachable("http://x", "tok", runner=runner)
    assert resultado.status == CheckStatus.ERROR
    assert "timeout" in resultado.detail


def test_nas_ssh_ok_cuando_devuelve_ok():
    runner = Mock(return_value=Mock(stdout="ok\n", stderr="", returncode=0))
    resultado = check_nas_ssh_reachable("HostFalso", runner=runner)
    assert resultado.status == CheckStatus.OK


def test_nas_ssh_error_cuando_returncode_no_es_cero():
    runner = Mock(return_value=Mock(stdout="", stderr="Permission denied", returncode=255))
    resultado = check_nas_ssh_reachable("HostFalso", runner=runner)
    assert resultado.status == CheckStatus.ERROR
    assert "Permission denied" in resultado.detail
