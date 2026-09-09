import unicodedata
import uuid
from datetime import UTC, datetime
from pathlib import Path

from alpardi_media_manager.domain.models import ContentType, Fingerprint, InventoryItem
from alpardi_media_manager.planning.plan import (
    RenameOperation,
    calcular_inventory_hash,
    cargar_plan,
    deserializar_plan,
    generar_plan_renombrado,
    guardar_plan,
    serializar_plan,
    verificar_frase_autorizacion,
)


def _op(source: str, destino: str, size: int = 1000) -> RenameOperation:
    return RenameOperation(item_id=uuid.uuid4(), source_path=source, destination_path=destino, size_bytes=size)


def test_plan_sin_conflictos_es_seguro_de_aplicar(tmp_path: Path):
    operaciones = [_op("a.mkv", "Blade Runner (1982)/Blade Runner (1982).mkv")]
    plan = generar_plan_renombrado(operaciones, inventory_hash="hash123", authorized_root=tmp_path)
    assert plan.is_safe_to_apply
    assert plan.conflicts == ()


def test_total_bytes_suma_todas_las_operaciones(tmp_path: Path):
    operaciones = [_op("a.mkv", "a2.mkv", size=1000), _op("b.mkv", "b2.mkv", size=2500)]
    plan = generar_plan_renombrado(operaciones, inventory_hash="h", authorized_root=tmp_path)
    assert plan.total_bytes == 3500


def test_plan_id_tiene_formato_esperado(tmp_path: Path):
    plan = generar_plan_renombrado([_op("a.mkv", "b.mkv")], inventory_hash="h", authorized_root=tmp_path)
    assert plan.plan_id.startswith("plan_")
    partes = plan.plan_id.split("_")
    assert len(partes) == 3  # plan, YYYYMMDD, hash-corto
    assert len(partes[1]) == 8  # YYYYMMDD


def test_mismo_inventory_hash_y_operaciones_dan_mismo_plan_id(tmp_path: Path):
    """El plan_id debe ser reproducible a partir de las mismas entradas -- no aleatorio."""
    ops = [_op("a.mkv", "b.mkv")]
    p1 = generar_plan_renombrado(ops, inventory_hash="mismo-hash", authorized_root=tmp_path)
    p2 = generar_plan_renombrado(ops, inventory_hash="mismo-hash", authorized_root=tmp_path)
    assert p1.plan_id == p2.plan_id


# --- Detección de conflictos -------------------------------------------------------------------

def test_destino_ya_existente_es_conflicto(tmp_path: Path):
    (tmp_path / "ya_existe.mkv").write_bytes(b"x")
    plan = generar_plan_renombrado([_op("origen.mkv", "ya_existe.mkv")], inventory_hash="h", authorized_root=tmp_path)
    assert not plan.is_safe_to_apply
    assert plan.conflicts[0].kind == "destination_exists"


def test_caracteres_invalidos_de_windows_es_conflicto(tmp_path: Path):
    plan = generar_plan_renombrado([_op("a.mkv", "Titulo: con dos puntos.mkv")], inventory_hash="h", authorized_root=tmp_path)
    assert any(c.kind == "invalid_chars" for c in plan.conflicts)


def test_nombre_reservado_de_windows_es_conflicto(tmp_path: Path):
    plan = generar_plan_renombrado([_op("a.mkv", "CON.mkv")], inventory_hash="h", authorized_root=tmp_path)
    assert any(c.kind == "reserved_name" for c in plan.conflicts)


def test_componente_demasiado_largo_es_conflicto(tmp_path: Path):
    nombre_largo = "x" * 300 + ".mkv"
    plan = generar_plan_renombrado([_op("a.mkv", nombre_largo)], inventory_hash="h", authorized_root=tmp_path)
    assert any(c.kind == "path_too_long" for c in plan.conflicts)


def test_colision_de_mayusculas_entre_dos_operaciones_del_plan(tmp_path: Path):
    operaciones = [_op("a.mkv", "Pelicula.mkv"), _op("b.mkv", "PELICULA.mkv")]
    plan = generar_plan_renombrado(operaciones, inventory_hash="h", authorized_root=tmp_path)
    assert any(c.kind == "case_collision" for c in plan.conflicts)


def test_colision_unicode_nfc_vs_nfd(tmp_path: Path):
    """La misma palabra con tilde compuesta de dos formas distintas (NFC vs NFD) debe detectarse
    como el mismo destino -- si no, dos operaciones "distintas" podrían pisarse en un filesystem
    que normaliza de forma distinta a como se comparó en memoria."""
    nfc = unicodedata.normalize("NFC", "Año.mkv")
    nfd = unicodedata.normalize("NFD", "Año.mkv")
    assert nfc != nfd  # confirma que de verdad son bytes distintos antes de comprobar el conflicto
    operaciones = [_op("a.mkv", nfc), _op("b.mkv", nfd)]
    plan = generar_plan_renombrado(operaciones, inventory_hash="h", authorized_root=tmp_path)
    assert any(c.kind == "unicode_collision" for c in plan.conflicts)


def test_plan_sin_operaciones_no_es_seguro_de_aplicar(tmp_path: Path):
    """Un plan vacío no tiene conflictos, pero tampoco tiene sentido aplicarlo."""
    plan = generar_plan_renombrado([], inventory_hash="h", authorized_root=tmp_path)
    assert plan.conflicts == ()
    assert not plan.is_safe_to_apply


# --- Frase de autorización ----------------------------------------------------------------------

def test_frase_autorizacion_exacta_es_valida(tmp_path: Path):
    plan = generar_plan_renombrado([_op("a.mkv", "b.mkv")], inventory_hash="h", authorized_root=tmp_path)
    ok, motivo = verificar_frase_autorizacion(plan.frase_autorizacion_esperada(), plan, inventory_hash_actual="h")
    assert ok, motivo


def test_frase_con_plan_id_equivocado_se_rechaza(tmp_path: Path):
    plan = generar_plan_renombrado([_op("a.mkv", "b.mkv")], inventory_hash="h", authorized_root=tmp_path)
    ok, motivo = verificar_frase_autorizacion("AUTORIZO APLICAR PLAN plan_falso SOBRE 1 ELEMENTOS", plan, inventory_hash_actual="h")
    assert not ok
    assert "no coincide" in motivo


def test_frase_con_numero_de_elementos_equivocado_se_rechaza(tmp_path: Path):
    plan = generar_plan_renombrado([_op("a.mkv", "b.mkv")], inventory_hash="h", authorized_root=tmp_path)
    frase = f"AUTORIZO APLICAR PLAN {plan.plan_id} SOBRE 999 ELEMENTOS"
    ok, _motivo = verificar_frase_autorizacion(frase, plan, inventory_hash_actual="h")
    assert not ok


def test_inventario_cambiado_expira_el_plan(tmp_path: Path):
    """Regla explícita del encargo: si el inventario cambió desde que se generó el plan, el plan
    expira -- aunque la frase de autorización sea, letra por letra, correcta."""
    plan = generar_plan_renombrado([_op("a.mkv", "b.mkv")], inventory_hash="hash-viejo", authorized_root=tmp_path)
    ok, motivo = verificar_frase_autorizacion(
        plan.frase_autorizacion_esperada(), plan, inventory_hash_actual="hash-nuevo-distinto",
    )
    assert not ok
    assert "expirado" in motivo


def test_plan_con_conflictos_no_se_puede_autorizar(tmp_path: Path):
    (tmp_path / "ya_existe.mkv").write_bytes(b"x")
    plan = generar_plan_renombrado([_op("a.mkv", "ya_existe.mkv")], inventory_hash="h", authorized_root=tmp_path)
    ok, motivo = verificar_frase_autorizacion(plan.frase_autorizacion_esperada(), plan, inventory_hash_actual="h")
    assert not ok
    assert "conflicto" in motivo


def test_frase_con_formato_libre_no_se_acepta(tmp_path: Path):
    """No basta con "aprobar" en lenguaje natural -- tiene que ser la frase exacta, letra por
    letra (regla explícita: "Claude no puede autorizarse a sí mismo")."""
    plan = generar_plan_renombrado([_op("a.mkv", "b.mkv")], inventory_hash="h", authorized_root=tmp_path)
    ok, _ = verificar_frase_autorizacion("sí, adelante, aplícalo", plan, inventory_hash_actual="h")
    assert not ok


# --- calcular_inventory_hash --------------------------------------------------------------------

def _item(path: str, quick: str = "abc") -> InventoryItem:
    ahora = datetime.now(UTC)
    return InventoryItem(
        library_id="lib", authorized_root="/data", current_path=path, extension=".mkv",
        content_type=ContentType.MOVIE,
        fingerprint=Fingerprint(size_bytes=1, mtime=ahora, quick=quick),
        discovered_at=ahora, updated_at=ahora,
    )


def test_inventory_hash_es_reproducible_para_el_mismo_inventario():
    items = [_item("a.mkv"), _item("b.mkv")]
    assert calcular_inventory_hash(items) == calcular_inventory_hash(items)


def test_inventory_hash_no_depende_del_orden_de_la_lista():
    a, b = _item("a.mkv"), _item("b.mkv")
    assert calcular_inventory_hash([a, b]) == calcular_inventory_hash([b, a])


def test_inventory_hash_cambia_si_cambia_un_solo_archivo():
    items = [_item("a.mkv", quick="original")]
    items_modificados = [_item("a.mkv", quick="contenido-cambiado")]
    assert calcular_inventory_hash(items) != calcular_inventory_hash(items_modificados)


def test_inventory_hash_inventario_vacio_es_estable():
    assert calcular_inventory_hash([]) == calcular_inventory_hash([])


def test_inventory_hash_coincide_entre_dos_escaneos_reales_independientes(tmp_path: Path):
    """Regresión de un fallo de diseño real: item.id es un UUID aleatorio nuevo en cada
    InventoryItem -- si calcular_inventory_hash lo usara, dos escaneos del MISMO archivo real (el
    caso real de uso: `plan rename` escanea en un proceso, `apply` vuelve a escanear en otro
    proceso distinto más tarde) nunca darían el mismo hash, y todo plan "caducaría" siempre. Aquí
    se escanea dos veces de verdad el mismo directorio sintético sin tocar nada entre medias."""
    from alpardi_media_manager.domain.models import ContentType as CT
    from alpardi_media_manager.inventory.scanner import escanear_directorio

    (tmp_path / "a.mkv").write_bytes(b"contenido sin cambios")

    primer_escaneo = escanear_directorio(tmp_path, library_id="lib", content_type=CT.MOVIE)
    segundo_escaneo = escanear_directorio(tmp_path, library_id="lib", content_type=CT.MOVIE)

    # Los IDs son distintos a propósito (son objetos "nuevos" cada vez) -- pero el hash del
    # inventario debe coincidir, porque el archivo real no cambió.
    assert primer_escaneo[0].id != segundo_escaneo[0].id
    assert calcular_inventory_hash(primer_escaneo) == calcular_inventory_hash(segundo_escaneo)


# --- serializar_plan / deserializar_plan / guardar_plan / cargar_plan ---------------------------

def test_deserializar_reconstruye_el_plan_identico(tmp_path: Path):
    (tmp_path / "ya_existe.mkv").write_bytes(b"x")
    plan = generar_plan_renombrado(
        [_op("a.mkv", "b.mkv"), _op("c.mkv", "ya_existe.mkv")],
        inventory_hash="h", authorized_root=tmp_path,
    )
    assert plan.conflicts  # el segundo debe dar conflicto -- se comprueba que también se conserva

    reconstruido = deserializar_plan(serializar_plan(plan))

    assert reconstruido.plan_id == plan.plan_id
    assert reconstruido.inventory_hash == plan.inventory_hash
    assert reconstruido.operations == plan.operations
    assert reconstruido.conflicts == plan.conflicts
    assert reconstruido.frase_autorizacion_esperada() == plan.frase_autorizacion_esperada()


def test_guardar_y_cargar_plan_desde_disco(tmp_path: Path):
    plan = generar_plan_renombrado([_op("a.mkv", "b.mkv")], inventory_hash="h", authorized_root=tmp_path)
    ruta = tmp_path / "plan.json"

    guardar_plan(plan, ruta)
    cargado = cargar_plan(ruta)

    assert cargado.plan_id == plan.plan_id
    assert cargado.operations == plan.operations
    assert cargado.is_safe_to_apply == plan.is_safe_to_apply


def test_plan_cargado_de_disco_se_puede_autorizar_igual_que_el_original(tmp_path: Path):
    """El caso de uso real: generar el plan en un proceso, guardarlo, cargarlo en otro proceso
    (la CLI real hace exactamente esto entre `plan rename` y `apply`), y que la autorización siga
    funcionando exactamente igual."""
    plan = generar_plan_renombrado([_op("a.mkv", "b.mkv")], inventory_hash="hash-real", authorized_root=tmp_path)
    ruta = tmp_path / "plan.json"
    guardar_plan(plan, ruta)

    cargado = cargar_plan(ruta)
    ok, motivo = verificar_frase_autorizacion(
        cargado.frase_autorizacion_esperada(), cargado, inventory_hash_actual="hash-real",
    )
    assert ok, motivo
