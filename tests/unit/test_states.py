from itertools import pairwise

from alpardi_media_manager.domain.states import ItemState, transicion_permitida


def test_flujo_feliz_completo_permitido():
    secuencia = [
        ItemState.DISCOVERED, ItemState.PARSED, ItemState.MATCHED,
        ItemState.PLANNED, ItemState.APPLIED, ItemState.VERIFIED,
    ]
    for origen, destino in pairwise(secuencia):
        assert transicion_permitida(origen, destino), f"{origen} -> {destino} debería permitirse"


def test_no_se_puede_saltar_de_discovered_a_applied():
    """Ninguna mutación sin plan -- regla no negociable del encargo."""
    assert not transicion_permitida(ItemState.DISCOVERED, ItemState.APPLIED)


def test_no_se_puede_saltar_directo_a_verified():
    assert not transicion_permitida(ItemState.DISCOVERED, ItemState.VERIFIED)


def test_needs_review_puede_volver_a_matched_o_ir_a_planned():
    assert transicion_permitida(ItemState.NEEDS_REVIEW, ItemState.MATCHED)
    assert transicion_permitida(ItemState.NEEDS_REVIEW, ItemState.PLANNED)


def test_failed_es_reintentable_no_terminal():
    assert transicion_permitida(ItemState.FAILED, ItemState.PLANNED)
    assert transicion_permitida(ItemState.FAILED, ItemState.ROLLED_BACK)


def test_verified_y_rolled_back_son_terminales():
    for destino in ItemState:
        assert not transicion_permitida(ItemState.VERIFIED, destino)
        assert not transicion_permitida(ItemState.ROLLED_BACK, destino)


def test_applied_no_puede_volver_a_planned():
    """Una vez aplicado, solo se puede verificar o revertir -- no 're-planear' sobre lo ya hecho."""
    assert not transicion_permitida(ItemState.APPLIED, ItemState.PLANNED)
