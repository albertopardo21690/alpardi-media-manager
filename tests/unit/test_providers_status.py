from pathlib import Path

import pytest

from alpardi_media_manager.providers.status import leer_estado_proveedores


def test_lee_config_real_cuando_existe(tmp_path: Path):
    (tmp_path / "providers.yaml").write_text(
        "providers:\n"
        "  tmdb:\n"
        "    enabled: true\n"
        "    credential_ref: keyring://alpardi-media/tmdb-read-token\n"
        "  musicbrainz:\n"
        "    enabled: false\n",
        encoding="utf-8",
    )

    estado = leer_estado_proveedores(tmp_path / "providers.yaml")
    assert estado.is_template is False
    por_nombre = {p.provider: p for p in estado.providers}
    assert por_nombre["tmdb"].enabled is True
    assert por_nombre["tmdb"].has_credential_ref is True
    assert por_nombre["musicbrainz"].enabled is False
    assert por_nombre["musicbrainz"].has_credential_ref is False


def test_cae_a_la_plantilla_si_no_hay_config_real(tmp_path: Path):
    (tmp_path / "providers.example.yaml").write_text(
        "providers:\n  tmdb:\n    enabled: false\n", encoding="utf-8",
    )

    estado = leer_estado_proveedores(tmp_path / "providers.yaml")
    assert estado.is_template is True
    assert estado.config_path.name == "providers.example.yaml"


def test_falla_con_claridad_si_no_existe_ni_config_ni_plantilla(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        leer_estado_proveedores(tmp_path / "providers.yaml")


def test_config_real_de_verdad_del_proyecto_tiene_todos_deshabilitados():
    """Regresión honesta: mientras Alberto no cree credenciales (docs/DECISIONS.md #5), el
    fichero real del proyecto debe mostrar 0 proveedores habilitados -- si esto falla, algo se
    activó sin la decisión explícita que exige el encargo."""
    raiz = Path(__file__).resolve().parents[2]
    estado = leer_estado_proveedores(raiz / "config" / "providers.yaml")
    assert all(not p.enabled for p in estado.providers)
    assert len(estado.providers) > 0
