import uuid
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from alpardi_media_manager.domain.models import (
    ContentType,
    DeviceInode,
    Edition,
    Fingerprint,
    InventoryItem,
    RelationKind,
    Version,
)
from alpardi_media_manager.domain.states import ItemState


def _fingerprint() -> Fingerprint:
    return Fingerprint(size_bytes=123456, mtime=datetime.now(UTC), quick="deadbeef")


def test_inventory_item_id_es_estable_no_depende_de_la_ruta():
    """La identidad interna no debe derivarse de la ruta -- si no, un renombrado 'perdería' el
    elemento en vez de simplemente actualizar su current_path."""
    item = InventoryItem(
        library_id="lib-movies",
        authorized_root="/data/Movies",
        current_path="Blade Runner (1982)/Blade Runner (1982).mkv",
        extension=".mkv",
        content_type=ContentType.MOVIE,
        fingerprint=_fingerprint(),
        discovered_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    id_antes = item.id
    item.current_path = "Blade Runner (1982) {edition-Final Cut}/Blade Runner (1982).mkv"
    assert item.id == id_antes


def test_inventory_item_por_defecto_arranca_discovered():
    item = InventoryItem(
        library_id="lib-movies", authorized_root="/data/Movies", current_path="x.mkv",
        extension=".mkv", content_type=ContentType.MOVIE, fingerprint=_fingerprint(),
        discovered_at=datetime.now(UTC), updated_at=datetime.now(UTC),
    )
    assert item.state == ItemState.DISCOVERED


def test_full_sha256_no_calculado_por_defecto():
    """El encargo exige dos niveles: rápido (contenedor/cabeceras) y profundo (hash completo,
    solo bajo petición) -- el hash completo nunca debe rellenarse "gratis" en el escaneo normal."""
    fp = _fingerprint()
    assert fp.full_sha256 is None
    assert fp.full_sha256_computed_at is None


def test_device_inode_marca_explicitamente_si_no_es_fiable():
    di = DeviceInode(device_id=1, inode=999, reliable=False)
    assert di.reliable is False


def test_edition_auto_detected_por_defecto_false():
    """Nunca se marca una edición como detectada automáticamente sin evidencia real -- por
    defecto False, quien la cree debe declarar explícitamente que viene de evidencia."""
    ed = Edition(parent_content_id=uuid.uuid4(), name="Final Cut")
    assert ed.auto_detected is False


def test_version_no_tiene_campo_edition_name_no_se_confunde_con_edicion():
    """Una Version (resolución/códec distinto de la MISMA edición) no debe tener forma de
    'fingir' ser una Edition -- son tipos distintos a propósito, para no confundir calidad
    técnica con un montaje realmente diferente (regla explícita del encargo)."""
    v = Version(parent_content_id=uuid.uuid4(), technical_label="2160p HEVC HDR10")
    assert not hasattr(v, "name")
    assert v.edition_id is None  # versión "por defecto" sin edición explícita


def test_item_sin_padre_ni_relacion_es_valido():
    item = InventoryItem(
        library_id="lib", authorized_root="/data", current_path="x.mkv", extension=".mkv",
        content_type=ContentType.TV_EPISODE, fingerprint=_fingerprint(),
        discovered_at=datetime.now(UTC), updated_at=datetime.now(UTC),
    )
    assert item.parent_id is None and item.relation_to_parent is None


def test_item_con_padre_y_relacion_es_valido():
    item = InventoryItem(
        library_id="lib", authorized_root="/data", current_path="s01e01.mkv", extension=".mkv",
        content_type=ContentType.TV_EPISODE, fingerprint=_fingerprint(),
        parent_id=uuid.uuid4(), relation_to_parent=RelationKind.EPISODE_OF_SEASON,
        discovered_at=datetime.now(UTC), updated_at=datetime.now(UTC),
    )
    assert item.parent_id is not None
    assert item.relation_to_parent == RelationKind.EPISODE_OF_SEASON


def test_parent_id_sin_relation_to_parent_falla():
    with pytest.raises(ValidationError):
        InventoryItem(
            library_id="lib", authorized_root="/data", current_path="x.mkv", extension=".mkv",
            content_type=ContentType.TV_EPISODE, fingerprint=_fingerprint(),
            parent_id=uuid.uuid4(),  # relation_to_parent ausente -- estado a medias
            discovered_at=datetime.now(UTC), updated_at=datetime.now(UTC),
        )


def test_relation_to_parent_sin_parent_id_falla():
    with pytest.raises(ValidationError):
        InventoryItem(
            library_id="lib", authorized_root="/data", current_path="x.mkv", extension=".mkv",
            content_type=ContentType.TV_EPISODE, fingerprint=_fingerprint(),
            relation_to_parent=RelationKind.EPISODE_OF_SEASON,  # parent_id ausente
            discovered_at=datetime.now(UTC), updated_at=datetime.now(UTC),
        )


def test_content_type_no_admite_valores_inventados():
    with pytest.raises(ValidationError):
        InventoryItem(
            library_id="lib", authorized_root="/data", current_path="x", extension=".mkv",
            content_type="pelicula_inventada",  # type: ignore[arg-type]
            fingerprint=_fingerprint(),
            discovered_at=datetime.now(UTC), updated_at=datetime.now(UTC),
        )
