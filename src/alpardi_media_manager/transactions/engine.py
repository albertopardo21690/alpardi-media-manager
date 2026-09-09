"""Motor transaccional. ÚNICO componente de todo el proyecto con permiso real de escritura sobre
rutas de medios (ver docs/ARCHITECTURE.md y docs/SECURITY.md) -- y solo dentro de una allowlist
normalizada (`authorized_root`), resuelta tras seguir enlaces simbólicos, y solo tras un `Plan`
generado por `planning/plan.py` y autorizado con la frase exacta.

Prioridad explícita del encargo: correcto y verificable antes que rápido. Cada paso escribe su
resultado en un journal persistente (JSON en disco) ANTES de continuar, para que el proceso pueda
morir a mitad y el journal siga contando con precisión qué se aplicó y qué no -- en AMBAS
direcciones, aplicar y revertir (ver nota de la revisión de seguridad 2026-09-09 más abajo).

Revisión de seguridad adversarial (2026-09-09, 4 ángulos independientes, 14 hallazgos, 11
corregidos aquí -- los 4 críticos incluidos):
- revertir_transaccion() no persistía el journal tras cada operación individual (solo al final) --
  corregido: ahora escribe tras cada paso, igual que aplicar_plan().
- El hash de verificación tras mover estaba fuera del try/except -- una excepción real podía
  escapar sin control. Corregido: ahora está cubierto.
- La comprobación de "el destino sigue dentro de authorized_root" se hacía una sola vez antes de
  crear los directorios intermedios -- un symlink plantado en ese hueco podía escapar la raíz.
  Corregido: se revalida justo antes de cada escritura real (mkdir y movimiento final).
- El propio directorio de journals no se comprobaba contra un escape por symlink. Corregido.
- revertir_transaccion() no aplicaba la misma guarda de symlink/hardlink que aplicar_plan() sobre
  el archivo que va a mover. Corregido: misma guarda en ambas direcciones.
- journal.estado se marcaba siempre "revertida" aunque la reversión fuera parcial. Corregido.
- os.rename() no falla si el destino ya existe (condición de carrera de ventana estrecha pero
  real) -- sustituido por os.link()+os.unlink(), que sí falla atómicamente con FileExistsError.
- Un fallo al borrar el origen tras una copia entre filesystems YA verificada se etiquetaba como
  "fallida_verificacion" (perdiendo el hash ya conocido) y detenía todo el plan. Corregido: se
  distingue de un fallo de integridad real.
- El propio journal no hacía fsync antes de publicarse -- corregido (fsync del temporal antes del
  os.replace), para ser durable frente a un corte de energía real, no solo frente a kill -9.

Límites conocidos, deliberadamente NO corregidos aquí (severidad baja/media, documentados con
honestidad en vez de ocultados -- ver también el registro de la sesión que hizo esta revisión):
- No hay fsync del DIRECTORIO contenedor tras cada os.rename()/os.link() de un archivo de medios
  real (solo el journal y la copia cross-filesystem lo hacen) -- frente a un corte de energía
  real (no un simple kill -9, donde el SO sigue vivo y los buffers se acaban volcando), el orden
  de persistencia entre "el archivo ya se movió" y "el journal lo registra" no tiene una garantía
  fuerte adicional a la que ya da el checkpointing por operación.
- Si el proceso muere (kill -9/OOM) durante `shutil.copyfile()` en la rama cross-filesystem, el
  `finally` que limpia el `.alpardimedia-tmp-*` no llega a ejecutarse (SIGKILL no es
  interceptable) -- puede quedar un temporal huérfano dentro de la carpeta de destino real. No
  hay barrido automático de huérfanos todavía.
- Si el proceso muere justo entre detener el bucle principal de `aplicar_plan()` (tras un fallo de
  verificación) y la escritura final que marca las operaciones restantes como OMITIDA, esas
  operaciones quedan en "pendiente" en vez de "omitida" -- no implica pérdida de datos (nunca se
  tocaron), pero un operador podría interpretar el journal como "todavía en curso".
"""
from __future__ import annotations

import json
import os
import shutil
import stat
import tempfile
import uuid
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from alpardi_media_manager.inventory.fingerprint import calcular_hash_completo
from alpardi_media_manager.planning.plan import Plan, RenameOperation, verificar_frase_autorizacion

# Carpeta de journals, fuera de cualquier ruta real de biblioteca (nunca se confunde con contenido
# multimedia, ni un escáner de bibliotecas la recorrería por error -- empieza por ".").
_NOMBRE_DIRECTORIO_JOURNAL = ".alpardimedia-journal"


class OperationStatus(StrEnum):
    """Estado individual de una operación dentro del journal."""

    PENDIENTE = "pendiente"
    EN_APLICACION = "en_aplicacion"                     # el movimiento real ya empezó, aún sin verificar
    APLICADA = "aplicada"                               # movida y verificada con éxito
    FALLIDA_VERIFICACION = "fallida_verificacion"       # el hash tras mover (o la copia) no coincide
    ERROR_APLICACION = "error_aplicacion"               # error de E/S inesperado al aplicar
    CONFLICTO_DESTINO = "conflicto_destino"             # el destino ya existía justo antes de mover
    FUERA_DE_RAIZ = "fuera_de_raiz"                     # el destino resuelto no cae en authorized_root
    REQUIERE_REVISION_MANUAL = "requiere_revision_manual"  # origen symlink o con hardlinks
    OMITIDA = "omitida"                                 # el plan se detuvo antes de llegar aquí
    REVERTIDA = "revertida"
    ERROR_REVERSION = "error_reversion"


# Estados que, al aplicar, obligan a DETENER el resto del plan (regla f del encargo). El resto de
# estados "raros" (conflicto, symlink, fuera de raíz) se registran y se sigue con la operación
# siguiente -- nunca se aborta todo el plan por un caso aislado que no implica pérdida de datos.
_ESTADOS_QUE_DETIENEN_EL_PLAN = frozenset({
    OperationStatus.FALLIDA_VERIFICACION,
    OperationStatus.ERROR_APLICACION,
})


class EstadoTransaccion(StrEnum):
    """Estados del journal en su conjunto."""

    INICIADA = "iniciada"
    EN_PROGRESO = "en_progreso"
    COMPLETADA = "completada"
    FALLIDA = "fallida"
    REVERTIDA = "revertida"


@dataclass(frozen=True)
class OperationJournalEntry:
    """Registro de una operación dentro del journal. Inmutable -- cada cambio de estado crea una
    entrada nueva vía `dataclasses.replace()` que sustituye a la anterior en `Journal.operations`."""

    index: int
    source_path: str
    destination_path: str
    status: OperationStatus = OperationStatus.PENDIENTE
    source_hash_before: str | None = None      # sha256 del origen, calculado ANTES de mover
    destination_hash_after: str | None = None  # sha256 del destino, calculado TRAS mover
    detail: str | None = None                  # motivo legible cuando status no es "aplicada"


@dataclass
class Journal:
    """Estado persistente de una transacción. A diferencia de los tipos de `planning/plan.py`,
    esto SÍ es mutable a propósito: se actualiza y se vuelve a escribir en disco tras cada paso,
    para poder reanudar o auditar exactamente desde dónde se interrumpió el proceso."""

    transaction_id: str
    plan_id: str
    authorized_root: str
    started_at: str
    finished_at: str | None
    estado: EstadoTransaccion
    operations: list[OperationJournalEntry]


@dataclass(frozen=True)
class TransactionResult:
    """Resultado devuelto por `aplicar_plan()`. `transaction_id` es `None` únicamente cuando la
    autorización se rechazó en el paso (a) -- en ese caso no se creó journal ni se tocó nada."""

    plan_id: str
    autorizada: bool
    transaction_id: str | None = None
    estado: EstadoTransaccion | None = None
    motivo_rechazo: str | None = None
    operations: tuple[OperationJournalEntry, ...] = field(default_factory=tuple)
    journal_path: str | None = None


@dataclass(frozen=True)
class RollbackResult:
    """Resultado devuelto por `revertir_transaccion()`."""

    transaction_id: str
    encontrada: bool  # False si no existe journal para ese transaction_id bajo authorized_root
    operations: tuple[OperationJournalEntry, ...] = field(default_factory=tuple)
    completa: bool = False  # True si TODAS las operaciones que se intentó revertir acabaron bien


@dataclass(frozen=True)
class _ResultadoMovimiento:
    """Resultado interno de mover un único archivo (en cualquier dirección: aplicar o revertir).
    No decide el `OperationStatus` -- eso lo hace quien llama, según el contexto."""

    hash_destino: str | None
    motivo_fallo: str | None  # None si tuvo éxito (aunque haya una advertencia no bloqueante)
    advertencia: str | None = None  # éxito real pero con un detalle a registrar (p.ej. origen no borrado)


_MOTIVO_FUERA_DE_RAIZ = "fuera_de_raiz"
_MOTIVO_CONFLICTO_DESTINO = "conflicto_destino"


def _journal_dir(authorized_root_resuelto: Path) -> Path:
    return authorized_root_resuelto / _NOMBRE_DIRECTORIO_JOURNAL


def _journal_path(authorized_root_resuelto: Path, transaction_id: str) -> Path:
    # Se indexa por transaction_id (no por plan_id) a propósito: un mismo plan_id podría, en
    # teoría, intentarse aplicar más de una vez (p.ej. tras una autorización rechazada), y cada
    # intento real genera su propia transacción con su propio journal -- transaction_id es la
    # clave natural para `revertir_transaccion()`, que solo recibe ese id.
    return _journal_dir(authorized_root_resuelto) / f"{transaction_id}.json"


def _verificar_contencion(ruta: Path, authorized_root_resuelto: Path) -> bool:
    """True si `ruta`, tras resolver symlinks, sigue dentro de `authorized_root_resuelto`. Se
    llama en varios puntos distintos a propósito (nunca basta una sola comprobación al principio,
    ver hallazgo crítico de la revisión de seguridad: un symlink plantado DESPUÉS de la primera
    comprobación pero ANTES de escribir de verdad puede escapar la raíz)."""
    try:
        ruta.resolve().relative_to(authorized_root_resuelto)
        return True
    except ValueError:
        return False


def _escribir_journal(path: Path, journal: Journal, authorized_root_resuelto: Path) -> None:
    """Escritura atómica: se escribe a un temporal en el mismo directorio y se renombra encima --
    así un fallo a mitad de escritura nunca deja un journal.json truncado/corrupto en disco.

    Antes de escribir se revalida que el propio directorio de journals sigue dentro de
    authorized_root -- se llama muchas veces por transacción, así que es la ventana de ataque más
    amplia de todo el módulo si alguien planta un symlink en `.alpardimedia-journal` (hallazgo de
    la revisión de seguridad)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if not _verificar_contencion(path.parent, authorized_root_resuelto):
        raise RuntimeError(
            f"El directorio de journals ({path.parent}) ya no está dentro de authorized_root "
            f"({authorized_root_resuelto}) -- posible symlink plantado, negándose a escribir."
        )
    datos: dict[str, Any] = {
        "transaction_id": journal.transaction_id,
        "plan_id": journal.plan_id,
        "authorized_root": journal.authorized_root,
        "started_at": journal.started_at,
        "finished_at": journal.finished_at,
        "estado": journal.estado.value,
        "operations": [
            {
                "index": e.index,
                "source_path": e.source_path,
                "destination_path": e.destination_path,
                "status": e.status.value,
                "source_hash_before": e.source_hash_before,
                "destination_hash_after": e.destination_hash_after,
                "detail": e.detail,
            }
            for e in journal.operations
        ],
    }
    tmp_path = path.parent / f"{path.name}.tmp"
    fd = os.open(tmp_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(json.dumps(datos, indent=2, ensure_ascii=False))
            f.flush()
            os.fsync(f.fileno())  # durable frente a un corte de energía real, no solo kill -9
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise
    os.replace(tmp_path, path)  # rename atómico dentro del mismo filesystem (mismo directorio)


def leer_journal(authorized_root: Path, transaction_id: str) -> Journal | None:
    """Lee el journal persistido de una transacción, o `None` si no existe. Pública para permitir
    auditar/inspeccionar el estado real en disco, no solo el resultado en memoria devuelto por
    `aplicar_plan()`."""
    path = _journal_path(authorized_root.resolve(), transaction_id)
    if not path.exists():
        return None
    datos = json.loads(path.read_text(encoding="utf-8"))
    operations = [
        OperationJournalEntry(
            index=o["index"],
            source_path=o["source_path"],
            destination_path=o["destination_path"],
            status=OperationStatus(o["status"]),
            source_hash_before=o["source_hash_before"],
            destination_hash_after=o["destination_hash_after"],
            detail=o["detail"],
        )
        for o in datos["operations"]
    ]
    return Journal(
        transaction_id=datos["transaction_id"],
        plan_id=datos["plan_id"],
        authorized_root=datos["authorized_root"],
        started_at=datos["started_at"],
        finished_at=datos["finished_at"],
        estado=EstadoTransaccion(datos["estado"]),
        operations=operations,
    )


def _mismo_filesystem(origen: Path, destino_parent_ya_creado: Path) -> bool:
    # Función aparte (en vez de inline) para poder simular en tests un escenario cross-filesystem
    # sin depender de que el entorno de CI realmente tenga dos filesystems distintos disponibles.
    return origen.lstat().st_dev == destino_parent_ya_creado.stat().st_dev


def _enlazar_sin_sobrescribir(origen: Path, destino: Path) -> None:
    """os.rename() NO falla si `destino` ya existe (lo sobrescribe en silencio) -- os.link() SÍ
    falla atómicamente con FileExistsError. Se usa link+unlink en vez de rename precisamente para
    que la ventana de carrera entre "comprobar que no existe" y "escribir" nunca pueda destruir un
    archivo real que apareciera justo ahí (hallazgo de la revisión de seguridad). Si el proceso
    muere entre el link() y el unlink(), el resultado es una copia duplicada inocua (mismo
    contenido en origen y destino), nunca una pérdida de datos."""
    os.link(origen, destino)
    os.unlink(origen)


def _mover_archivo_verificado(
    origen: Path,
    destino: Path,
    hash_esperado: str,
    authorized_root_resuelto: Path,
) -> _ResultadoMovimiento:
    """Mueve `origen` a `destino`, en cualquier dirección (aplicar o revertir). Nunca sobrescribe
    un `destino` que ya exista, nunca borra `origen` hasta que el destino está escrito y
    verificado, y nunca escribe fuera de `authorized_root_resuelto` aunque `destino` resuelva a
    otra ruta vía symlink o "..". Usado tanto por `aplicar_plan()` como por
    `revertir_transaccion()` -- la lógica de seguridad es idéntica en ambos sentidos."""
    if not _verificar_contencion(destino, authorized_root_resuelto):
        return _ResultadoMovimiento(None, _MOTIVO_FUERA_DE_RAIZ)

    # Recomprobar que el destino no existe -- el inventory_hash del plan solo detecta cambios en
    # el ORIGEN inventariado, nunca detectaría que alguien creó justo ese archivo de destino
    # mientras tanto. Esta es la primera de varias comprobaciones -- se repite lo más pegada
    # posible a cada escritura real para minimizar la ventana de carrera.
    if os.path.lexists(destino):
        return _ResultadoMovimiento(None, _MOTIVO_CONFLICTO_DESTINO)

    try:
        destino.parent.mkdir(parents=True, exist_ok=True)

        # Revalidar contención DESPUÉS de crear los directorios intermedios: mkdir(parents=True)
        # sigue symlinks ya existentes en componentes intermedios, y Path.resolve(strict=False)
        # no puede detectar uno que todavía no existía en la primera comprobación de arriba --
        # si alguien plantó un symlink en ese hueco, esta segunda comprobación lo atrapa antes de
        # escribir nada (hallazgo crítico de la revisión de seguridad).
        if not _verificar_contencion(destino, authorized_root_resuelto):
            return _ResultadoMovimiento(None, _MOTIVO_FUERA_DE_RAIZ)

        advertencia: str | None = None

        if _mismo_filesystem(origen, destino.parent):
            if os.path.lexists(destino):
                return _ResultadoMovimiento(None, _MOTIVO_CONFLICTO_DESTINO)
            try:
                _enlazar_sin_sobrescribir(origen, destino)
            except FileExistsError:
                return _ResultadoMovimiento(None, _MOTIVO_CONFLICTO_DESTINO)
        else:
            # Filesystems distintos: copiar a un temporal EN EL DIRECTORIO DESTINO (para que el
            # enlace final sí sea atómico), verificar su hash contra el hash de origen ya
            # conocido, fsync, y solo entonces publicar el temporal con el nombre final. El
            # original no se toca hasta que todo esto se ha verificado con éxito.
            tmp_fd, tmp_name = tempfile.mkstemp(dir=str(destino.parent), prefix=".alpardimedia-tmp-")
            tmp_path = Path(tmp_name)
            try:
                os.close(tmp_fd)
                shutil.copyfile(origen, tmp_path)
                with open(tmp_path, "rb") as f:
                    os.fsync(f.fileno())
                if calcular_hash_completo(tmp_path) != hash_esperado:
                    return _ResultadoMovimiento(None, "la copia al filesystem destino no coincide con el hash de origen")
                if os.path.lexists(destino):
                    return _ResultadoMovimiento(None, _MOTIVO_CONFLICTO_DESTINO)
                try:
                    _enlazar_sin_sobrescribir(tmp_path, destino)
                except FileExistsError:
                    return _ResultadoMovimiento(None, _MOTIVO_CONFLICTO_DESTINO)
            finally:
                if tmp_path.exists():
                    tmp_path.unlink(missing_ok=True)

            # El original solo se borra AHORA, con el destino ya escrito y verificado por hash --
            # si esto falla, el destino sigue siendo correcto y verificado; no es un fallo de
            # integridad, es un fallo de limpieza. Se distingue explícitamente (hallazgo de la
            # revisión de seguridad: antes se perdía el hash ya conocido y se detenía todo el plan
            # por esto, tratándolo como si la copia fuera dudosa cuando no lo era).
            try:
                os.unlink(origen)
            except OSError as e:
                advertencia = f"el destino se copió y verificó correctamente, pero no se pudo borrar el origen: {e}"
    except OSError as e:
        return _ResultadoMovimiento(None, f"error de E/S al mover: {e}")

    try:
        hash_destino = calcular_hash_completo(destino)
    except OSError as e:
        # Antes esta línea estaba fuera del try/except y una excepción real de E/S aquí escapaba
        # sin control fuera de toda la función (hallazgo crítico de la revisión de seguridad,
        # confirmado ejecutando código real).
        return _ResultadoMovimiento(None, f"error de E/S al verificar el hash tras mover: {e}")

    if hash_destino != hash_esperado:
        return _ResultadoMovimiento(hash_destino, "el hash tras mover no coincide con el hash de origen")
    return _ResultadoMovimiento(hash_destino, None, advertencia=advertencia)


def _entrada_pendiente(indice: int, op: RenameOperation) -> OperationJournalEntry:
    return OperationJournalEntry(index=indice, source_path=op.source_path, destination_path=op.destination_path)


def _guarda_enlaces(origen: Path) -> OperationJournalEntry | None:
    """Comprobación compartida entre aplicar y revertir: nunca se opera automáticamente sobre un
    symlink o un archivo con más de un hardlink -- mover/borrar el origen podría afectar a más de
    una ruta de las que el usuario cree que está tocando. Devuelve una entrada parcial (solo
    status/detail, sin index/paths -- el llamador la completa) o `None` si no hay problema.

    Antes esta guarda solo existía en la dirección de aplicar; revertir_transaccion() la movía sin
    ella (hallazgo de la revisión de seguridad: un archivo que gana un hardlink o se convierte en
    symlink en la ventana entre aplicar y revertir se movía en silencio sin la misma protección)."""
    try:
        st = origen.lstat()
    except OSError:
        return None  # el llamador ya maneja "origen no accesible" con su propio try/except
    if stat.S_ISLNK(st.st_mode):
        return OperationJournalEntry(0, "", "", status=OperationStatus.REQUIERE_REVISION_MANUAL, detail="el origen es un enlace simbólico")
    if st.st_nlink > 1:
        return OperationJournalEntry(0, "", "", status=OperationStatus.REQUIERE_REVISION_MANUAL, detail=f"el origen tiene {st.st_nlink} hardlinks")
    return None


def _aplicar_operacion(
    indice: int, op: RenameOperation, authorized_root_resuelto: Path,
) -> OperationJournalEntry:
    base = _entrada_pendiente(indice, op)
    origen = authorized_root_resuelto / op.source_path
    destino = authorized_root_resuelto / op.destination_path

    try:
        origen.lstat()
    except OSError as e:
        return replace(base, status=OperationStatus.ERROR_APLICACION, detail=f"origen no accesible: {e}")

    guarda = _guarda_enlaces(origen)
    if guarda is not None:
        return replace(base, status=guarda.status, detail=guarda.detail)

    try:
        origen_hash = calcular_hash_completo(origen)
    except OSError as e:
        return replace(base, status=OperationStatus.ERROR_APLICACION, detail=f"no se pudo leer el origen: {e}")

    resultado = _mover_archivo_verificado(origen, destino, origen_hash, authorized_root_resuelto)

    if resultado.motivo_fallo == _MOTIVO_FUERA_DE_RAIZ:
        return replace(
            base, status=OperationStatus.FUERA_DE_RAIZ, source_hash_before=origen_hash,
            detail="el destino resuelto cae fuera de authorized_root",
        )
    if resultado.motivo_fallo == _MOTIVO_CONFLICTO_DESTINO:
        return replace(
            base, status=OperationStatus.CONFLICTO_DESTINO, source_hash_before=origen_hash,
            detail="el destino ya existe (condición de carrera detectada justo antes de aplicar)",
        )
    if resultado.motivo_fallo is not None:
        return replace(
            base, status=OperationStatus.FALLIDA_VERIFICACION, source_hash_before=origen_hash,
            destination_hash_after=resultado.hash_destino, detail=resultado.motivo_fallo,
        )
    return replace(
        base, status=OperationStatus.APLICADA, source_hash_before=origen_hash,
        destination_hash_after=resultado.hash_destino, detail=resultado.advertencia,
    )


def aplicar_plan(
    plan: Plan,
    authorized_root: Path,
    frase_autorizacion: str,
    inventory_hash_actual: str,
) -> TransactionResult:
    """Aplica un plan ya generado. Secuencia obligatoria del encargo:

    a) Revalida la frase de autorización -- si no es válida, no se toca nada, ni se crea journal.
    b) Cada destino se vuelve a comprobar "justo antes de aplicar" -- se hace dentro del propio
       bucle (ver `_mover_archivo_verificado`), no en una pasada previa: una comprobación en
       bloque quedaría igual de obsoleta que el propio plan si el filesystem cambia mientras se
       aplican las primeras operaciones de un plan largo. `inventory_hash_actual` solo detecta que
       cambió el INVENTARIO DE ORIGEN, nunca que apareció un archivo nuevo justo en un destino.
    c) El journal se crea y se persiste ANTES de tocar el primer archivo.
    d) Se aplica operación por operación, EN ORDEN. Antes de mover, se persiste un estado
       intermedio EN_APLICACION (para que, si el proceso muere justo después del movimiento real
       pero antes de calcular/persistir el resultado final -- el rehash de un vídeo de varios GB
       puede tardar segundos -- el journal en disco al menos sepa que esa operación concreta
       estaba en curso, en vez de seguir diciendo "pendiente" como si nunca se hubiera tocado).
       Tras cada operación se reescribe el journal con el resultado final.
    e)/f) Ver `_aplicar_operacion` / `_mover_archivo_verificado`.
    g) Al terminar, el journal queda en "completada" (el proceso llegó al final, aunque alguna
       operación individual quedara en conflicto/revisión manual -- el detalle exacto vive en cada
       entrada) o en "fallida" (se tuvo que detener el resto del plan por un fallo real de
       verificación o de E/S -- ver `_ESTADOS_QUE_DETIENEN_EL_PLAN`).
    """
    ok, motivo = verificar_frase_autorizacion(frase_autorizacion, plan, inventory_hash_actual)
    if not ok:
        return TransactionResult(plan_id=plan.plan_id, autorizada=False, motivo_rechazo=motivo)

    authorized_root_resuelto = authorized_root.resolve()
    transaction_id = f"tx_{uuid.uuid4().hex}"
    journal_path = _journal_path(authorized_root_resuelto, transaction_id)

    journal = Journal(
        transaction_id=transaction_id,
        plan_id=plan.plan_id,
        authorized_root=str(authorized_root_resuelto),
        started_at=datetime.now(UTC).isoformat(),
        finished_at=None,
        estado=EstadoTransaccion.INICIADA,
        operations=[_entrada_pendiente(i, op) for i, op in enumerate(plan.operations)],
    )
    _escribir_journal(journal_path, journal, authorized_root_resuelto)  # (c) journal ANTES de tocar nada

    journal.estado = EstadoTransaccion.EN_PROGRESO
    _escribir_journal(journal_path, journal, authorized_root_resuelto)

    indice_de_parada: int | None = None
    for i, op in enumerate(plan.operations):
        # Estado intermedio ANTES del movimiento real -- ver docstring, punto (d).
        journal.operations[i] = replace(
            journal.operations[i], status=OperationStatus.EN_APLICACION,
            source_path=op.source_path, destination_path=op.destination_path,
        )
        _escribir_journal(journal_path, journal, authorized_root_resuelto)

        journal.operations[i] = _aplicar_operacion(i, op, authorized_root_resuelto)
        _escribir_journal(journal_path, journal, authorized_root_resuelto)  # resultado final persistido

        if journal.operations[i].status in _ESTADOS_QUE_DETIENEN_EL_PLAN:
            indice_de_parada = i
            break

    if indice_de_parada is not None:
        # Las operaciones ya aplicadas y verificadas se QUEDAN aplicadas -- revertir es una acción
        # separada y explícita (`revertir_transaccion`), nunca automática solo por esto.
        for j in range(indice_de_parada + 1, len(journal.operations)):
            journal.operations[j] = replace(journal.operations[j], status=OperationStatus.OMITIDA)
        journal.estado = EstadoTransaccion.FALLIDA
    else:
        journal.estado = EstadoTransaccion.COMPLETADA

    journal.finished_at = datetime.now(UTC).isoformat()
    _escribir_journal(journal_path, journal, authorized_root_resuelto)

    return TransactionResult(
        plan_id=plan.plan_id,
        autorizada=True,
        transaction_id=transaction_id,
        estado=journal.estado,
        operations=tuple(journal.operations),
        journal_path=str(journal_path),
    )


def revertir_transaccion(transaction_id: str, authorized_root: Path) -> RollbackResult:
    """Deshace una transacción ya aplicada. Solo se revierten las operaciones que llegaron a
    quedar `APLICADA` (las que nunca se aplicaron -- omitidas, en conflicto, symlinks -- no se
    tocaron nunca, así que no hay nada que deshacer), en orden INVERSO al que se aplicaron.

    Igual que `aplicar_plan()`, el journal se reescribe tras CADA operación individual revertida
    -- antes esta función solo escribía al final de todo el bucle, lo que significaba que un
    proceso interrumpido a mitad de una reversión larga dejaba el journal en disco exactamente
    como si la reversión nunca hubiera empezado, pese a que parte de los archivos ya habían vuelto
    físicamente a su sitio (hallazgo crítico de la revisión de seguridad, confirmado
    independientemente por dos ángulos de revisión distintos)."""
    authorized_root_resuelto = authorized_root.resolve()
    journal_path = _journal_path(authorized_root_resuelto, transaction_id)
    if not journal_path.exists():
        return RollbackResult(transaction_id=transaction_id, encontrada=False)

    journal = leer_journal(authorized_root, transaction_id)
    assert journal is not None  # journal_path.exists() ya lo garantiza

    aplicadas = [e for e in journal.operations if e.status == OperationStatus.APLICADA]

    for entrada in reversed(aplicadas):
        origen_original = authorized_root_resuelto / entrada.source_path   # dónde estaba antes de aplicar
        destino_actual = authorized_root_resuelto / entrada.destination_path  # dónde está ahora

        if entrada.destination_hash_after is None:
            # No debería ocurrir para una entrada APLICADA (siempre se rellena al aplicar), pero
            # nunca se asume silenciosamente -- se registra como error explícito.
            journal.operations[entrada.index] = replace(
                entrada, status=OperationStatus.ERROR_REVERSION,
                detail="la entrada no tiene hash de destino registrado -- no se puede verificar la reversión",
            )
            _escribir_journal(journal_path, journal, authorized_root_resuelto)
            continue

        if not os.path.lexists(destino_actual):
            # Puede ser un intento de reversión repetido tras una interrupción a mitad (el archivo
            # ya está de vuelta en origen_original, gracias a que ahora persistimos tras cada
            # paso) -- se distingue de "alguien borró el archivo de verdad" comprobando si el
            # propio origen ya tiene el contenido esperado (hallazgo de la revisión de seguridad:
            # antes esto se reportaba siempre como error_reversion aunque la reversión anterior ya
            # hubiera tenido éxito de verdad).
            if os.path.lexists(origen_original):
                try:
                    ya_revertido = calcular_hash_completo(origen_original) == entrada.destination_hash_after
                except OSError:
                    ya_revertido = False
                if ya_revertido:
                    journal.operations[entrada.index] = replace(entrada, status=OperationStatus.REVERTIDA)
                    _escribir_journal(journal_path, journal, authorized_root_resuelto)
                    continue
            journal.operations[entrada.index] = replace(
                entrada, status=OperationStatus.ERROR_REVERSION,
                detail="el archivo aplicado ya no está en su ubicación -- no se puede revertir",
            )
            _escribir_journal(journal_path, journal, authorized_root_resuelto)
            continue

        # Misma guarda de symlink/hardlink que aplicar_plan() -- ver _guarda_enlaces().
        guarda = _guarda_enlaces(destino_actual)
        if guarda is not None:
            journal.operations[entrada.index] = replace(entrada, status=guarda.status, detail=guarda.detail)
            _escribir_journal(journal_path, journal, authorized_root_resuelto)
            continue

        resultado = _mover_archivo_verificado(
            destino_actual, origen_original, entrada.destination_hash_after, authorized_root_resuelto,
        )
        if resultado.motivo_fallo is not None:
            journal.operations[entrada.index] = replace(
                entrada, status=OperationStatus.ERROR_REVERSION, detail=resultado.motivo_fallo,
            )
        else:
            journal.operations[entrada.index] = replace(
                entrada, status=OperationStatus.REVERTIDA, detail=resultado.advertencia,
            )
        _escribir_journal(journal_path, journal, authorized_root_resuelto)  # tras CADA operación revertida

    operaciones_revertidas = tuple(journal.operations[e.index] for e in aplicadas)
    completa = all(e.status == OperationStatus.REVERTIDA for e in operaciones_revertidas)

    # Antes se marcaba siempre REVERTIDA incluso con reversiones parciales/fallidas -- un
    # consumidor que solo mirara journal.estado (sin bajar a cada operación) llegaba a una
    # conclusión falsa (hallazgo de la revisión de seguridad).
    journal.estado = EstadoTransaccion.REVERTIDA if completa else EstadoTransaccion.FALLIDA
    journal.finished_at = datetime.now(UTC).isoformat()
    _escribir_journal(journal_path, journal, authorized_root_resuelto)

    return RollbackResult(
        transaction_id=transaction_id, encontrada=True,
        operations=operaciones_revertidas, completa=completa,
    )
