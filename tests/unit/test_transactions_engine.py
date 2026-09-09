import hashlib
import os
import uuid
from pathlib import Path

import pytest

from alpardi_media_manager.planning.plan import RenameOperation, generar_plan_renombrado
from alpardi_media_manager.transactions import engine
from alpardi_media_manager.transactions.engine import (
    EstadoTransaccion,
    OperationStatus,
    aplicar_plan,
    leer_journal,
    revertir_transaccion,
)


def _op(source: str, destino: str, size: int = 1000) -> RenameOperation:
    return RenameOperation(item_id=uuid.uuid4(), source_path=source, destination_path=destino, size_bytes=size)


def _sha256(contenido: bytes) -> str:
    return hashlib.sha256(contenido).hexdigest()


# --- Aplicar un plan simple -----------------------------------------------------------------

def test_aplica_una_operacion_simple_en_el_mismo_filesystem(tmp_path: Path):
    (tmp_path / "a.mkv").write_bytes(b"contenido original")
    plan = generar_plan_renombrado([_op("a.mkv", "Pelicula (2020)/Pelicula (2020).mkv")], inventory_hash="h", authorized_root=tmp_path)

    resultado = aplicar_plan(plan, tmp_path, plan.frase_autorizacion_esperada(), inventory_hash_actual="h")

    assert resultado.autorizada
    assert resultado.estado == EstadoTransaccion.COMPLETADA
    assert resultado.operations[0].status == OperationStatus.APLICADA

    destino = tmp_path / "Pelicula (2020)" / "Pelicula (2020).mkv"
    assert destino.read_bytes() == b"contenido original"
    assert not (tmp_path / "a.mkv").exists()


def test_aplica_varias_operaciones_todas_se_aplican(tmp_path: Path):
    (tmp_path / "a.mkv").write_bytes(b"contenido a")
    (tmp_path / "b.mkv").write_bytes(b"contenido b")
    (tmp_path / "c.mkv").write_bytes(b"contenido c")
    operaciones = [
        _op("a.mkv", "A2.mkv"),
        _op("b.mkv", "carpeta/B2.mkv"),
        _op("c.mkv", "C2.mkv"),
    ]
    plan = generar_plan_renombrado(operaciones, inventory_hash="h", authorized_root=tmp_path)

    resultado = aplicar_plan(plan, tmp_path, plan.frase_autorizacion_esperada(), inventory_hash_actual="h")

    assert resultado.estado == EstadoTransaccion.COMPLETADA
    assert all(op.status == OperationStatus.APLICADA for op in resultado.operations)
    assert (tmp_path / "A2.mkv").read_bytes() == b"contenido a"
    assert (tmp_path / "carpeta" / "B2.mkv").read_bytes() == b"contenido b"
    assert (tmp_path / "C2.mkv").read_bytes() == b"contenido c"
    assert not (tmp_path / "a.mkv").exists()
    assert not (tmp_path / "b.mkv").exists()
    assert not (tmp_path / "c.mkv").exists()


def test_journal_persistido_coincide_con_el_resultado_devuelto(tmp_path: Path):
    """El journal en disco debe reflejar exactamente lo mismo que el TransactionResult devuelto
    en memoria -- nunca debe haber divergencia entre ambos."""
    (tmp_path / "a.mkv").write_bytes(b"x")
    plan = generar_plan_renombrado([_op("a.mkv", "b.mkv")], inventory_hash="h", authorized_root=tmp_path)
    resultado = aplicar_plan(plan, tmp_path, plan.frase_autorizacion_esperada(), inventory_hash_actual="h")

    journal = leer_journal(tmp_path, resultado.transaction_id)  # type: ignore[arg-type]
    assert journal is not None
    assert journal.estado == EstadoTransaccion.COMPLETADA
    assert journal.operations[0].status == OperationStatus.APLICADA
    assert journal.operations[0].source_hash_before == resultado.operations[0].source_hash_before


# --- Rechazo de autorización ---------------------------------------------------------------

def test_rechaza_aplicar_si_la_frase_de_autorizacion_no_es_exacta(tmp_path: Path):
    (tmp_path / "a.mkv").write_bytes(b"contenido")
    plan = generar_plan_renombrado([_op("a.mkv", "b.mkv")], inventory_hash="h", authorized_root=tmp_path)

    resultado = aplicar_plan(plan, tmp_path, "sí, adelante, aplícalo", inventory_hash_actual="h")

    assert not resultado.autorizada
    assert resultado.transaction_id is None
    assert resultado.motivo_rechazo is not None
    # No se ejecuta NADA: el archivo original sigue exactamente donde estaba.
    assert (tmp_path / "a.mkv").read_bytes() == b"contenido"
    assert not (tmp_path / "b.mkv").exists()
    # Tampoco se crea ningún journal.
    assert not (tmp_path / ".alpardimedia-journal").exists()


def test_rechaza_aplicar_si_el_inventory_hash_no_coincide_plan_expirado(tmp_path: Path):
    (tmp_path / "a.mkv").write_bytes(b"contenido")
    plan = generar_plan_renombrado([_op("a.mkv", "b.mkv")], inventory_hash="hash-viejo", authorized_root=tmp_path)

    resultado = aplicar_plan(
        plan, tmp_path, plan.frase_autorizacion_esperada(), inventory_hash_actual="hash-nuevo-distinto",
    )

    assert not resultado.autorizada
    assert "expirado" in (resultado.motivo_rechazo or "")
    assert (tmp_path / "a.mkv").exists()
    assert not (tmp_path / "b.mkv").exists()


# --- Nunca sobrescribir un destino ya existente ---------------------------------------------

def test_nunca_sobrescribe_un_destino_que_aparece_por_condicion_de_carrera(tmp_path: Path):
    """El plan se genera cuando el destino todavía no existe (no hay conflicto detectado en el
    plan). Justo antes de aplicar, otro proceso crea ese mismo destino -- condición de carrera
    real. La operación concreta debe rechazarse sin tocar el archivo que ya estaba ahí, y sin
    tocar tampoco el origen."""
    (tmp_path / "origen.mkv").write_bytes(b"contenido del origen")
    plan = generar_plan_renombrado([_op("origen.mkv", "destino.mkv")], inventory_hash="h", authorized_root=tmp_path)
    assert plan.is_safe_to_apply  # en el momento de generar el plan, destino.mkv no existía

    # Simula la condición de carrera: el destino aparece DESPUÉS de generar el plan.
    (tmp_path / "destino.mkv").write_bytes(b"esto ya estaba aqui, no se debe tocar")

    resultado = aplicar_plan(plan, tmp_path, plan.frase_autorizacion_esperada(), inventory_hash_actual="h")

    assert resultado.operations[0].status == OperationStatus.CONFLICTO_DESTINO
    # El archivo que ya estaba en el destino permanece intacto.
    assert (tmp_path / "destino.mkv").read_bytes() == b"esto ya estaba aqui, no se debe tocar"
    # El origen no se ha tocado ni borrado.
    assert (tmp_path / "origen.mkv").read_bytes() == b"contenido del origen"


# --- Symlinks nunca se mueven automáticamente ------------------------------------------------

def test_symlink_como_origen_se_marca_requiere_revision_manual_y_no_se_mueve(tmp_path: Path):
    objetivo_real = tmp_path / "objetivo_real.mkv"
    objetivo_real.write_bytes(b"contenido real")
    enlace = tmp_path / "enlace.mkv"
    enlace.symlink_to(objetivo_real)

    plan = generar_plan_renombrado([_op("enlace.mkv", "destino.mkv")], inventory_hash="h", authorized_root=tmp_path)
    resultado = aplicar_plan(plan, tmp_path, plan.frase_autorizacion_esperada(), inventory_hash_actual="h")

    assert resultado.operations[0].status == OperationStatus.REQUIERE_REVISION_MANUAL
    assert enlace.is_symlink()
    assert os.readlink(enlace) == str(objetivo_real)
    assert not (tmp_path / "destino.mkv").exists()
    assert objetivo_real.read_bytes() == b"contenido real"


def test_origen_con_mas_de_un_hardlink_se_marca_requiere_revision_manual(tmp_path: Path):
    original = tmp_path / "original.mkv"
    original.write_bytes(b"contenido compartido")
    otro_nombre = tmp_path / "otro_nombre.mkv"
    os.link(original, otro_nombre)  # ahora original.mkv tiene st_nlink == 2

    plan = generar_plan_renombrado([_op("original.mkv", "destino.mkv")], inventory_hash="h", authorized_root=tmp_path)
    resultado = aplicar_plan(plan, tmp_path, plan.frase_autorizacion_esperada(), inventory_hash_actual="h")

    assert resultado.operations[0].status == OperationStatus.REQUIERE_REVISION_MANUAL
    assert original.exists()
    assert not (tmp_path / "destino.mkv").exists()


# --- Revertir una transacción -----------------------------------------------------------------

def test_revertir_transaccion_deshace_una_transaccion_aplicada(tmp_path: Path):
    (tmp_path / "a.mkv").write_bytes(b"contenido original")
    plan = generar_plan_renombrado([_op("a.mkv", "carpeta/b.mkv")], inventory_hash="h", authorized_root=tmp_path)
    aplicado = aplicar_plan(plan, tmp_path, plan.frase_autorizacion_esperada(), inventory_hash_actual="h")
    assert aplicado.estado == EstadoTransaccion.COMPLETADA
    assert aplicado.transaction_id is not None

    resultado = revertir_transaccion(aplicado.transaction_id, tmp_path)

    assert resultado.encontrada
    assert resultado.completa
    assert resultado.operations[0].status == OperationStatus.REVERTIDA
    # El archivo vuelve exactamente a su ubicación y contenido original.
    assert (tmp_path / "a.mkv").read_bytes() == b"contenido original"
    assert _sha256((tmp_path / "a.mkv").read_bytes()) == aplicado.operations[0].source_hash_before
    assert not (tmp_path / "carpeta" / "b.mkv").exists()

    journal = leer_journal(tmp_path, aplicado.transaction_id)
    assert journal is not None
    assert journal.estado == EstadoTransaccion.REVERTIDA


def test_revertir_transaccion_inexistente_devuelve_no_encontrada(tmp_path: Path):
    resultado = revertir_transaccion("tx_no_existe", tmp_path)
    assert not resultado.encontrada
    assert resultado.operations == ()


# --- Fallo a mitad de un plan de varias operaciones -------------------------------------------

def test_fallo_de_verificacion_a_mitad_de_plan_detiene_el_resto_pero_conserva_lo_ya_aplicado(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    """Simula, de forma controlada, que la verificación posterior a mover falla para la SEGUNDA
    operación (p.ej. corrupción real detectada al releer el destino). La primera operación, ya
    aplicada y verificada antes de llegar a la segunda, debe quedarse aplicada -- no hay rollback
    automático solo por esto. La tercera operación ni siquiera debe intentarse."""
    (tmp_path / "a.mkv").write_bytes(b"contenido a")
    (tmp_path / "b.mkv").write_bytes(b"contenido b")
    (tmp_path / "c.mkv").write_bytes(b"contenido c")
    operaciones = [_op("a.mkv", "A2.mkv"), _op("b.mkv", "B2.mkv"), _op("c.mkv", "C2.mkv")]
    plan = generar_plan_renombrado(operaciones, inventory_hash="h", authorized_root=tmp_path)

    destino_b2 = (tmp_path / "B2.mkv").resolve()
    hash_real = engine.calcular_hash_completo

    def hash_falseado_para_b2(path: Path) -> str:
        # El hash de origen (b.mkv) se calcula con normalidad; solo se falsea cuando se relee el
        # archivo YA MOVIDO a su destino final (B2.mkv), simulando una verificación posterior que
        # detecta que algo no cuadra.
        if path.resolve() == destino_b2:
            return "0" * 64
        return hash_real(path)

    monkeypatch.setattr(engine, "calcular_hash_completo", hash_falseado_para_b2)

    resultado = aplicar_plan(plan, tmp_path, plan.frase_autorizacion_esperada(), inventory_hash_actual="h")

    assert resultado.estado == EstadoTransaccion.FALLIDA
    assert resultado.operations[0].status == OperationStatus.APLICADA
    assert resultado.operations[1].status == OperationStatus.FALLIDA_VERIFICACION
    assert resultado.operations[2].status == OperationStatus.OMITIDA

    # La primera operación, ya aplicada y verificada, se queda tal cual -- no se revierte sola.
    assert (tmp_path / "A2.mkv").read_bytes() == b"contenido a"
    assert not (tmp_path / "a.mkv").exists()

    # La tercera operación nunca se intentó: el origen sigue intacto en su sitio.
    assert (tmp_path / "c.mkv").read_bytes() == b"contenido c"
    assert not (tmp_path / "C2.mkv").exists()

    # El journal en disco refleja exactamente lo mismo.
    journal = leer_journal(tmp_path, resultado.transaction_id)  # type: ignore[arg-type]
    assert journal is not None
    assert journal.estado == EstadoTransaccion.FALLIDA
    assert [op.status for op in journal.operations] == [
        OperationStatus.APLICADA, OperationStatus.FALLIDA_VERIFICACION, OperationStatus.OMITIDA,
    ]


# --- Nunca escribir fuera de authorized_root ---------------------------------------------------

def test_destino_que_escapa_de_authorized_root_via_dobles_puntos_se_rechaza(tmp_path: Path):
    """Un destination_path malicioso o corrupto (p.ej. "../fuera/secreto.mkv") jamás debe permitir
    escribir fuera de authorized_root, aunque el plan lo haya dejado pasar sin conflictos (el
    generador de planes no valida ".." -- esta es la última línea de defensa real)."""
    raiz_autorizada = tmp_path / "biblioteca"
    raiz_autorizada.mkdir()
    (raiz_autorizada / "origen.mkv").write_bytes(b"contenido sensible")

    operacion = _op("origen.mkv", "../fuera/secreto.mkv")
    plan = generar_plan_renombrado([operacion], inventory_hash="h", authorized_root=raiz_autorizada)
    assert plan.is_safe_to_apply  # el generador de planes no detecta esto -- lo debe hacer el motor

    resultado = aplicar_plan(plan, raiz_autorizada, plan.frase_autorizacion_esperada(), inventory_hash_actual="h")

    assert resultado.operations[0].status == OperationStatus.FUERA_DE_RAIZ
    assert not (tmp_path / "fuera" / "secreto.mkv").exists()
    assert (raiz_autorizada / "origen.mkv").read_bytes() == b"contenido sensible"


def test_destino_que_escapa_via_symlink_de_una_carpeta_intermedia_se_rechaza(tmp_path: Path):
    """Igual que el caso anterior, pero el escape ocurre porque una carpeta DENTRO de
    authorized_root es en realidad un symlink que apunta fuera -- Path.resolve() debe detectarlo
    igual que con "..", porque resuelve symlinks antes de comparar."""
    raiz_autorizada = tmp_path / "biblioteca"
    raiz_autorizada.mkdir()
    (raiz_autorizada / "origen.mkv").write_bytes(b"contenido sensible")

    fuera = tmp_path / "fuera_de_la_biblioteca"
    fuera.mkdir()
    (raiz_autorizada / "enlace_carpeta").symlink_to(fuera, target_is_directory=True)

    operacion = _op("origen.mkv", "enlace_carpeta/secreto.mkv")
    plan = generar_plan_renombrado([operacion], inventory_hash="h", authorized_root=raiz_autorizada)

    resultado = aplicar_plan(plan, raiz_autorizada, plan.frase_autorizacion_esperada(), inventory_hash_actual="h")

    assert resultado.operations[0].status == OperationStatus.FUERA_DE_RAIZ
    assert not (fuera / "secreto.mkv").exists()
    assert (raiz_autorizada / "origen.mkv").read_bytes() == b"contenido sensible"


# --- Copia verificada entre filesystems distintos ----------------------------------------------

def test_copia_entre_filesystems_distintos_verifica_hash_antes_de_borrar_el_origen(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    """No siempre hay dos filesystems reales disponibles en el entorno de test -- se fuerza la
    rama "filesystems distintos" monkeypachando el propio detector (`_mismo_filesystem`), sin
    tocar Path.stat/lstat globalmente (evita romper el resto de operaciones internas de pathlib).
    Ejercita la rama real de copia a temporal + hash + fsync + rename, en vez de os.rename()."""
    (tmp_path / "a.mkv").write_bytes(b"contenido cross-fs")
    plan = generar_plan_renombrado([_op("a.mkv", "b.mkv")], inventory_hash="h", authorized_root=tmp_path)

    monkeypatch.setattr(engine, "_mismo_filesystem", lambda origen, destino_parent: False)

    resultado = aplicar_plan(plan, tmp_path, plan.frase_autorizacion_esperada(), inventory_hash_actual="h")

    assert resultado.operations[0].status == OperationStatus.APLICADA
    assert (tmp_path / "b.mkv").read_bytes() == b"contenido cross-fs"
    assert not (tmp_path / "a.mkv").exists()
    # No debe quedar ningún temporal huérfano.
    assert list(tmp_path.glob(".alpardimedia-tmp-*")) == []


def test_revertir_transaccion_persiste_journal_tras_cada_operacion_no_solo_al_final(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    """Regresión de un hallazgo crítico real de la revisión de seguridad: revertir_transaccion()
    escribía el journal UNA sola vez, al final de todo el bucle -- si el proceso moría a mitad de
    revertir una transacción larga, el journal en disco no reflejaba nada de lo ya revertido de
    verdad. Aquí se comprueba, contando llamadas reales, que se persiste tras CADA operación
    revertida, igual que aplicar_plan()."""
    for nombre in ("a.mkv", "b.mkv", "c.mkv"):
        (tmp_path / nombre).write_bytes(nombre.encode())
    operaciones = [_op("a.mkv", "A2.mkv"), _op("b.mkv", "B2.mkv"), _op("c.mkv", "C2.mkv")]
    plan = generar_plan_renombrado(operaciones, inventory_hash="h", authorized_root=tmp_path)
    aplicado = aplicar_plan(plan, tmp_path, plan.frase_autorizacion_esperada(), inventory_hash_actual="h")
    assert aplicado.estado == EstadoTransaccion.COMPLETADA

    llamadas = []
    real_escribir = engine._escribir_journal

    def contador(path, journal, root):
        llamadas.append([op.status for op in journal.operations])
        return real_escribir(path, journal, root)

    monkeypatch.setattr(engine, "_escribir_journal", contador)

    resultado = revertir_transaccion(aplicado.transaction_id, tmp_path)  # type: ignore[arg-type]

    assert resultado.completa
    # 3 operaciones revertidas -> al menos 3 escrituras del journal durante el propio bucle de
    # reversión (antes del fix, esto habría sido exactamente 1, la del final).
    assert len(llamadas) >= 3


def test_revertir_transaccion_reconoce_una_reversion_ya_hecha_en_un_intento_anterior(tmp_path: Path):
    """Regresión directa del escenario descrito por la revisión de seguridad: si un intento
    anterior de revertir_transaccion() ya movió el archivo de vuelta a su origen (por ejemplo,
    porque el proceso murió justo después de esa operación pero antes -- en el código viejo -- de
    persistir el journal), un segundo intento no debe reportar 'el archivo ya no está, no se puede
    revertir' como si fuera una pérdida de datos real. Aquí se simula ese estado directamente:
    origen_original YA tiene el contenido correcto, destino_actual ya no existe."""
    (tmp_path / "a.mkv").write_bytes(b"contenido original")
    plan = generar_plan_renombrado([_op("a.mkv", "b.mkv")], inventory_hash="h", authorized_root=tmp_path)
    aplicado = aplicar_plan(plan, tmp_path, plan.frase_autorizacion_esperada(), inventory_hash_actual="h")
    assert aplicado.estado == EstadoTransaccion.COMPLETADA

    # Simula que un intento de reversión anterior ya tuvo éxito de verdad, pero el journal en
    # disco se quedó desactualizado (el escenario exacto que el fix de checkpointing evita hacia
    # delante -- esto comprueba además que, si llegara a pasar, se reconoce con honestidad).
    (tmp_path / "b.mkv").rename(tmp_path / "a.mkv")

    resultado = revertir_transaccion(aplicado.transaction_id, tmp_path)  # type: ignore[arg-type]

    assert resultado.completa
    assert resultado.operations[0].status == OperationStatus.REVERTIDA
    assert (tmp_path / "a.mkv").read_bytes() == b"contenido original"


def test_revertir_transaccion_con_contenido_distinto_en_origen_es_error_real_no_falso_positivo(tmp_path: Path):
    """Contraprueba del test anterior: si destino_actual no existe pero origen_original tampoco
    tiene el contenido esperado (no es una reversión previa exitosa, es de verdad un archivo
    perdido), debe seguir reportándose como error_reversion -- el fix no debe convertir un error
    real en un falso 'todo bien'."""
    (tmp_path / "a.mkv").write_bytes(b"contenido original")
    plan = generar_plan_renombrado([_op("a.mkv", "b.mkv")], inventory_hash="h", authorized_root=tmp_path)
    aplicado = aplicar_plan(plan, tmp_path, plan.frase_autorizacion_esperada(), inventory_hash_actual="h")

    # b.mkv desaparece de verdad (p.ej. alguien lo borró) y NO hay nada en a.mkv.
    (tmp_path / "b.mkv").unlink()

    resultado = revertir_transaccion(aplicado.transaction_id, tmp_path)  # type: ignore[arg-type]

    assert not resultado.completa
    assert resultado.operations[0].status == OperationStatus.ERROR_REVERSION


def test_error_de_es_al_verificar_hash_tras_mover_no_escapa_sin_control(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    """Regresión: antes, un OSError real al releer el hash del destino justo después de mover
    (p.ej. el disco falla en ese instante) escapaba de _mover_archivo_verificado() sin ningún
    try/except que lo cubriera, y por tanto de toda la función aplicar_plan() -- en vez de
    quedar registrado en el journal como un fallo controlado."""
    (tmp_path / "a.mkv").write_bytes(b"contenido")
    plan = generar_plan_renombrado([_op("a.mkv", "b.mkv")], inventory_hash="h", authorized_root=tmp_path)

    hash_real = engine.calcular_hash_completo
    destino_b = (tmp_path / "b.mkv").resolve()

    def hash_que_falla_al_verificar(path: Path) -> str:
        if path.resolve() == destino_b:
            raise OSError("fallo de E/S simulado al releer el destino")
        return hash_real(path)

    monkeypatch.setattr(engine, "calcular_hash_completo", hash_que_falla_al_verificar)

    # No debe lanzar ninguna excepción -- debe devolver un TransactionResult normal.
    resultado = aplicar_plan(plan, tmp_path, plan.frase_autorizacion_esperada(), inventory_hash_actual="h")

    assert resultado.estado == EstadoTransaccion.FALLIDA
    assert resultado.operations[0].status == OperationStatus.FALLIDA_VERIFICACION
    assert "E/S" in (resultado.operations[0].detail or "")


def test_directorio_de_journals_como_symlink_hacia_fuera_se_rechaza(tmp_path: Path):
    """Regresión: _escribir_journal() nunca comprobaba que el propio directorio de journals
    (.alpardimedia-journal) siguiera dentro de authorized_root -- si alguien lo convierte en un
    symlink hacia fuera ANTES de la primera escritura, toda la transacción se escribiría fuera de
    la raíz autorizada sin ningún aviso."""
    raiz = tmp_path / "biblioteca"
    raiz.mkdir()
    (raiz / "a.mkv").write_bytes(b"contenido")
    fuera = tmp_path / "fuera"
    fuera.mkdir()
    (raiz / ".alpardimedia-journal").symlink_to(fuera, target_is_directory=True)

    plan = generar_plan_renombrado([_op("a.mkv", "b.mkv")], inventory_hash="h", authorized_root=raiz)

    with pytest.raises(RuntimeError, match="symlink"):
        aplicar_plan(plan, raiz, plan.frase_autorizacion_esperada(), inventory_hash_actual="h")

    # Nada se ha escrito en el directorio externo.
    assert list(fuera.iterdir()) == []


def test_revertir_aplica_la_misma_guarda_de_symlink_que_aplicar(tmp_path: Path):
    """Regresión: aplicar_plan() nunca mueve automáticamente un origen que sea symlink o tenga
    hardlinks -- pero revertir_transaccion() movía destino_actual sin esa misma comprobación. Aquí
    se simula que, entre aplicar y revertir, el archivo en destino_actual se sustituye por un
    symlink -- la reversión debe negarse a moverlo automáticamente, igual que haría aplicar_plan()
    en la dirección contraria."""
    (tmp_path / "a.mkv").write_bytes(b"contenido original")
    plan = generar_plan_renombrado([_op("a.mkv", "b.mkv")], inventory_hash="h", authorized_root=tmp_path)
    aplicado = aplicar_plan(plan, tmp_path, plan.frase_autorizacion_esperada(), inventory_hash_actual="h")
    assert aplicado.estado == EstadoTransaccion.COMPLETADA

    # Simula que, en la ventana entre aplicar y revertir, b.mkv pasa a ser un symlink.
    objetivo_real = tmp_path / "objetivo_real.mkv"
    objetivo_real.write_bytes(b"contenido original")  # mismo hash que el b.mkv original
    (tmp_path / "b.mkv").unlink()
    (tmp_path / "b.mkv").symlink_to(objetivo_real)

    resultado = revertir_transaccion(aplicado.transaction_id, tmp_path)  # type: ignore[arg-type]

    assert resultado.operations[0].status == OperationStatus.REQUIERE_REVISION_MANUAL
    # El symlink no se ha tocado -- no se movió en silencio.
    assert (tmp_path / "b.mkv").is_symlink()
    assert not (tmp_path / "a.mkv").exists()


def test_reversion_parcial_marca_el_journal_como_fallida_no_revertida(tmp_path: Path):
    """Regresión: journal.estado se fijaba SIEMPRE a REVERTIDA al final, incluso cuando alguna
    operación terminaba en error_reversion -- un consumidor que solo mirara journal.estado (sin
    bajar a cada operación) llegaba a una conclusión falsa. Con dos operaciones, una revertible y
    otra con un error real (contenido no coincide con nada esperado), el estado global debe
    reflejar que la reversión NO fue completa."""
    (tmp_path / "a.mkv").write_bytes(b"contenido a")
    (tmp_path / "b.mkv").write_bytes(b"contenido b")
    operaciones = [_op("a.mkv", "A2.mkv"), _op("b.mkv", "B2.mkv")]
    plan = generar_plan_renombrado(operaciones, inventory_hash="h", authorized_root=tmp_path)
    aplicado = aplicar_plan(plan, tmp_path, plan.frase_autorizacion_esperada(), inventory_hash_actual="h")
    assert aplicado.estado == EstadoTransaccion.COMPLETADA

    # B2.mkv se borra de verdad, sin que A2.mkv haya recibido su contenido -- error real, no una
    # reversión previa exitosa (ver test específico de esa distinción, arriba).
    (tmp_path / "B2.mkv").unlink()

    resultado = revertir_transaccion(aplicado.transaction_id, tmp_path)  # type: ignore[arg-type]

    assert not resultado.completa
    journal = leer_journal(tmp_path, aplicado.transaction_id)  # type: ignore[arg-type]
    assert journal is not None
    assert journal.estado == EstadoTransaccion.FALLIDA  # nunca REVERTIDA si algo no se revirtió


def test_fallo_al_borrar_origen_tras_copia_verificada_no_detiene_el_plan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    """Regresión: si la copia entre filesystems distintos ya se verificó por hash y se publicó en
    destino con éxito, pero el borrado posterior del origen falla (p.ej. el recurso de red se
    desmontó justo en ese instante), la operación NO debe tratarse como un fallo de integridad
    (antes: FALLIDA_VERIFICACION, deteniendo todo el plan y perdiendo el hash ya conocido) -- el
    destino sigue siendo correcto y verificado, solo queda una copia duplicada del origen."""
    (tmp_path / "a.mkv").write_bytes(b"contenido cross-fs")
    (tmp_path / "siguiente.mkv").write_bytes(b"otra operacion que debe seguir")
    operaciones = [_op("a.mkv", "b.mkv"), _op("siguiente.mkv", "siguiente2.mkv")]
    plan = generar_plan_renombrado(operaciones, inventory_hash="h", authorized_root=tmp_path)

    origen_a = (tmp_path / "a.mkv").resolve()
    unlink_real = os.unlink

    def unlink_que_falla_solo_para_a(path, *a, **kw):
        if Path(path).resolve() == origen_a:
            raise OSError("el recurso de red se desmontó justo ahora")
        return unlink_real(path, *a, **kw)

    monkeypatch.setattr(engine, "_mismo_filesystem", lambda origen, destino_parent: False)
    monkeypatch.setattr(engine.os, "unlink", unlink_que_falla_solo_para_a)

    resultado = aplicar_plan(plan, tmp_path, plan.frase_autorizacion_esperada(), inventory_hash_actual="h")

    # La operación se considera aplicada de verdad -- el destino está copiado y verificado.
    assert resultado.operations[0].status == OperationStatus.APLICADA
    assert resultado.operations[0].destination_hash_after is not None
    assert "no se pudo borrar el origen" in (resultado.operations[0].detail or "")
    assert (tmp_path / "b.mkv").read_bytes() == b"contenido cross-fs"
    # El plan sigue con la siguiente operación en vez de detenerse.
    assert resultado.estado == EstadoTransaccion.COMPLETADA
    assert resultado.operations[1].status == OperationStatus.APLICADA


def test_symlink_plantado_justo_durante_el_mkdir_del_destino_se_detecta(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    """Regresión del hallazgo crítico más sutil: la comprobación de contención se hacía UNA vez
    antes de crear los directorios intermedios del destino -- si un símlink se planta justo en la
    ventana entre esa comprobación y el propio mkdir/rename, el mkdir(parents=True) lo sigue sin
    darse cuenta. Aquí se simula la carrera real interceptando la llamada a mkdir para plantar el
    symlink en el momento exacto en que el código real la invoca."""
    raiz = tmp_path / "biblioteca"
    raiz.mkdir()
    (raiz / "a.mkv").write_bytes(b"contenido sensible")
    fuera = tmp_path / "fuera_de_la_biblioteca"
    fuera.mkdir()

    from pathlib import Path as PathClass
    mkdir_real = PathClass.mkdir

    def mkdir_que_planta_symlink(self, *args, **kwargs):
        # Justo cuando el código real llama a destino.parent.mkdir(...), un "atacante" gana la
        # carrera y convierte ese componente en un symlink hacia fuera antes de que se cree.
        if self.name == "carpeta_nueva" and not self.exists():
            self.symlink_to(fuera)
            return None
        return mkdir_real(self, *args, **kwargs)

    monkeypatch.setattr(PathClass, "mkdir", mkdir_que_planta_symlink)

    operacion = _op("a.mkv", "carpeta_nueva/secreto.mkv")
    plan = generar_plan_renombrado([operacion], inventory_hash="h", authorized_root=raiz)

    resultado = aplicar_plan(plan, raiz, plan.frase_autorizacion_esperada(), inventory_hash_actual="h")

    assert resultado.operations[0].status == OperationStatus.FUERA_DE_RAIZ
    assert not (fuera / "secreto.mkv").exists()
    assert (raiz / "a.mkv").read_bytes() == b"contenido sensible"


def test_copia_entre_filesystems_no_borra_el_origen_si_la_copia_no_verifica(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    """Si la copia al filesystem destino no verifica (hash distinto tras copiar), el original NO
    se borra bajo ningún concepto -- se detiene el plan con la operación marcada como fallida."""
    (tmp_path / "a.mkv").write_bytes(b"contenido cross-fs")
    plan = generar_plan_renombrado([_op("a.mkv", "b.mkv")], inventory_hash="h", authorized_root=tmp_path)

    hash_real = engine.calcular_hash_completo

    def hash_falseado_solo_para_el_temporal(path: Path) -> str:
        # El hash de origen (a.mkv) se calcula con normalidad; solo se falsea al releer el
        # temporal recién copiado, simulando una corrupción real durante la copia entre
        # filesystems -- el original nunca se debe borrar en ese caso.
        if ".alpardimedia-tmp-" in path.name:
            return "hash-que-nunca-coincide"
        return hash_real(path)

    monkeypatch.setattr(engine, "_mismo_filesystem", lambda origen, destino_parent: False)
    monkeypatch.setattr(engine, "calcular_hash_completo", hash_falseado_solo_para_el_temporal)

    resultado = aplicar_plan(plan, tmp_path, plan.frase_autorizacion_esperada(), inventory_hash_actual="h")

    assert resultado.estado == EstadoTransaccion.FALLIDA
    assert resultado.operations[0].status == OperationStatus.FALLIDA_VERIFICACION
    # El original sigue intacto -- nunca se borra sin verificar antes.
    assert (tmp_path / "a.mkv").read_bytes() == b"contenido cross-fs"
    assert not (tmp_path / "b.mkv").exists()
    assert list(tmp_path.glob(".alpardimedia-tmp-*")) == []
