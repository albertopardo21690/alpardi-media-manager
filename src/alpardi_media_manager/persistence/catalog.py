"""Persiste en SQLite lo que `inventory.scanner.escanear_directorio()` ya descubrió, y reconstruye
`InventoryItem` reales a partir de esas filas. Segundo escalón de la capa "Base de datos" de
`docs/ARCHITECTURE.md`: a diferencia de `persistence/db.py`, este módulo sí importa `domain/` y
`parsers/`.

Principio de "único escritor" reutilizado del motor transaccional (CLAUDE.md invariante #2, que
habla de archivos multimedia -- aquí el equivalente para METADATOS): `sincronizar_items()` es la
única función que hace INSERT/UPDATE de un item, y nunca toca `item_state` de una fila ya
existente (solo la fija a `discovered` en el INSERT inicial). `actualizar_estado()` es la ÚNICA
función con permiso de escribir `item_state`, y siempre pasa antes por
`domain.states.transicion_permitida()`.
"""
from __future__ import annotations

import sqlite3
import uuid
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from alpardi_media_manager.domain.models import (
    ContentType,
    DeviceInode,
    Fingerprint,
    InventoryItem,
    RelationKind,
)
from alpardi_media_manager.domain.states import ItemState, transicion_permitida
from alpardi_media_manager.inventory.scanner import escanear_directorio
from alpardi_media_manager.parsers.filename import parsear_nombre_episodio
from alpardi_media_manager.transactions.engine import Journal, OperationStatus, RollbackResult

_COLUMNAS_INSERT = (
    "id", "library_id", "authorized_root", "current_path", "extension", "content_type",
    "item_state", "size_bytes", "mtime", "fingerprint_quick", "full_sha256",
    "full_sha256_computed_at", "device_id", "inode", "device_inode_reliable",
    "season_number", "episode_number", "episode_number_end",
    "discovered_at", "updated_at", "last_seen_at",
)

_SQL_INSERT = f"""
    INSERT INTO inventory_items ({", ".join(_COLUMNAS_INSERT)})
    VALUES (
        :id, :library_id, :authorized_root, :current_path, :extension, :content_type,
        'discovered', :size_bytes, :mtime, :fingerprint_quick, :full_sha256,
        :full_sha256_computed_at, :device_id, :inode, :device_inode_reliable,
        :season_number, :episode_number, :episode_number_end,
        :discovered_at, :updated_at, :last_seen_at
    )
"""

# `id`, `item_state`, `discovered_at`, `parent_id`, `relation_to_parent`: deliberadamente NUNCA
# se tocan en un re-sync -- ver docstring del módulo.
_SQL_UPDATE = """
    UPDATE inventory_items SET
        extension = :extension, content_type = :content_type,
        size_bytes = :size_bytes, mtime = :mtime, fingerprint_quick = :fingerprint_quick,
        full_sha256 = :full_sha256, full_sha256_computed_at = :full_sha256_computed_at,
        device_id = :device_id, inode = :inode, device_inode_reliable = :device_inode_reliable,
        season_number = :season_number, episode_number = :episode_number,
        episode_number_end = :episode_number_end,
        updated_at = :updated_at, last_seen_at = :last_seen_at
    WHERE library_id = :library_id AND current_path = :current_path
"""


@dataclass(frozen=True)
class SincronizacionResultado:
    nuevos: int
    actualizados: int

    @property
    def total(self) -> int:
        return self.nuevos + self.actualizados


def _texto(fila: sqlite3.Row, columna: str) -> str:
    return str(fila[columna])


def _texto_opcional(fila: sqlite3.Row, columna: str) -> str | None:
    valor = fila[columna]
    return None if valor is None else str(valor)


def _entero(fila: sqlite3.Row, columna: str) -> int:
    return int(fila[columna])


def _entero_opcional(fila: sqlite3.Row, columna: str) -> int | None:
    valor = fila[columna]
    return None if valor is None else int(valor)


def _numeros_episodio_derivados(current_path: str) -> tuple[int | None, int | None, int | None]:
    """season_number/episode_number/episode_number_end son columnas DERIVADAS (nunca se añaden a
    domain/models.py) -- se recalculan re-parseando `current_path` con
    `parsers.filename.parsear_nombre_episodio()` en cada sync, igual que `planning/plan.py` ya
    reparsea título/año de película en vez de guardarlos aparte."""
    info = parsear_nombre_episodio(Path(current_path).stem)
    if info is None:
        return None, None, None
    return info.season, info.episode_start, info.episode_end


def _parametros_fila(item: InventoryItem, ahora: datetime) -> dict[str, Any]:
    fp = item.fingerprint
    di = item.device_inode
    season, episode, episode_end = _numeros_episodio_derivados(item.current_path)
    return {
        "id": str(item.id),
        "library_id": item.library_id,
        "authorized_root": item.authorized_root,
        "current_path": item.current_path,
        "extension": item.extension,
        "content_type": item.content_type.value,
        "size_bytes": fp.size_bytes,
        "mtime": fp.mtime.isoformat(),
        "fingerprint_quick": fp.quick,
        "full_sha256": fp.full_sha256,
        "full_sha256_computed_at": (
            fp.full_sha256_computed_at.isoformat() if fp.full_sha256_computed_at else None
        ),
        "device_id": di.device_id if di is not None else None,
        "inode": di.inode if di is not None else None,
        "device_inode_reliable": int(di.reliable) if di is not None else None,
        "season_number": season,
        "episode_number": episode,
        "episode_number_end": episode_end,
        "discovered_at": item.discovered_at.isoformat(),
        "updated_at": ahora.isoformat(),
        "last_seen_at": ahora.isoformat(),
    }


def sincronizar_items(
    conn: sqlite3.Connection, items: list[InventoryItem], ahora: datetime,
) -> SincronizacionResultado:
    """Upsert puro sobre una lista ya escaneada -- el "persistir" de "escanear (puro) ->
    persistir (nuevo)". La identidad de lookup real es (library_id, current_path) -- el mismo
    criterio que `planning/plan.py::calcular_inventory_hash` ya usa, deliberadamente ignorando
    `item.id` (que es un UUID nuevo en cada escaneo). Si la fila ya existe, su `id` original se
    conserva -- nunca se sobrescribe con el UUID recién generado por este escaneo."""
    nuevos = 0
    actualizados = 0
    for item in items:
        fila_existente = conn.execute(
            "SELECT full_sha256, full_sha256_computed_at FROM inventory_items "
            "WHERE library_id = ? AND current_path = ?",
            (item.library_id, item.current_path),
        ).fetchone()
        parametros = _parametros_fila(item, ahora)

        if fila_existente is None:
            conn.execute(_SQL_INSERT, parametros)
            nuevos += 1
        else:
            # El escaneo normal nunca calcula el hash profundo (inventory/fingerprint.py: nivel
            # "profundo" solo bajo petición explícita) -- si este escaneo no trae uno nuevo, se
            # conserva el que ya hubiera en la fila en vez de borrarlo con NULL.
            if parametros["full_sha256"] is None:
                parametros["full_sha256"] = _texto_opcional(fila_existente, "full_sha256")
                parametros["full_sha256_computed_at"] = _texto_opcional(
                    fila_existente, "full_sha256_computed_at",
                )
            conn.execute(_SQL_UPDATE, parametros)
            actualizados += 1
    conn.commit()
    return SincronizacionResultado(nuevos=nuevos, actualizados=actualizados)


def _registrar_biblioteca(
    conn: sqlite3.Connection, library_id: str, authorized_root: str, ahora: datetime,
) -> None:
    """Mantiene la tabla `libraries` -- crea la fila la primera vez (con su `created_at` real),
    y en syncs posteriores solo refresca `authorized_root` (por si la raíz se resolvió de forma
    distinta, p.ej. un symlink cambiado), nunca `created_at`."""
    existente = conn.execute(
        "SELECT library_id FROM libraries WHERE library_id = ?", (library_id,),
    ).fetchone()
    if existente is None:
        conn.execute(
            "INSERT INTO libraries (library_id, authorized_root, created_at) VALUES (?, ?, ?)",
            (library_id, authorized_root, ahora.isoformat()),
        )
    else:
        conn.execute(
            "UPDATE libraries SET authorized_root = ? WHERE library_id = ?",
            (authorized_root, library_id),
        )
    conn.commit()


def sincronizar_biblioteca(
    conn: sqlite3.Connection,
    raiz: Path,
    library_id: str,
    content_type: ContentType,
    ahora: datetime | None = None,
) -> SincronizacionResultado:
    """Orquestador fino: llama a `inventory.scanner.escanear_directorio()` SIN modificarlo -- su
    contrato "solo lectura, nunca escribe" sigue siendo literalmente cierto -- y persiste el
    resultado con `sincronizar_items()`. De paso mantiene la fila de `libraries` para esta raíz."""
    momento = ahora if ahora is not None else datetime.now(UTC)
    raiz_resuelta = raiz.resolve()
    items = escanear_directorio(raiz_resuelta, library_id=library_id, content_type=content_type)
    _registrar_biblioteca(conn, library_id, str(raiz_resuelta), momento)
    return sincronizar_items(conn, items, momento)


def _item_desde_fila(fila: sqlite3.Row) -> InventoryItem:
    device_inode = None
    if _entero_opcional(fila, "device_id") is not None:
        device_inode = DeviceInode(
            device_id=_entero(fila, "device_id"),
            inode=_entero(fila, "inode"),
            reliable=bool(_entero(fila, "device_inode_reliable")),
        )

    full_sha256_computed_at_texto = _texto_opcional(fila, "full_sha256_computed_at")
    parent_id_texto = _texto_opcional(fila, "parent_id")
    relation_texto = _texto_opcional(fila, "relation_to_parent")

    return InventoryItem(
        id=uuid.UUID(_texto(fila, "id")),
        library_id=_texto(fila, "library_id"),
        authorized_root=_texto(fila, "authorized_root"),
        current_path=_texto(fila, "current_path"),
        extension=_texto(fila, "extension"),
        content_type=ContentType(_texto(fila, "content_type")),
        state=ItemState(_texto(fila, "item_state")),
        fingerprint=Fingerprint(
            size_bytes=_entero(fila, "size_bytes"),
            mtime=datetime.fromisoformat(_texto(fila, "mtime")),
            quick=_texto(fila, "fingerprint_quick"),
            full_sha256=_texto_opcional(fila, "full_sha256"),
            full_sha256_computed_at=(
                datetime.fromisoformat(full_sha256_computed_at_texto)
                if full_sha256_computed_at_texto is not None else None
            ),
        ),
        device_inode=device_inode,
        parent_id=uuid.UUID(parent_id_texto) if parent_id_texto is not None else None,
        relation_to_parent=RelationKind(relation_texto) if relation_texto is not None else None,
        discovered_at=datetime.fromisoformat(_texto(fila, "discovered_at")),
        updated_at=datetime.fromisoformat(_texto(fila, "updated_at")),
    )


def listar_items(
    conn: sqlite3.Connection,
    library_id: str | None = None,
    content_type: ContentType | None = None,
    state: ItemState | None = None,
) -> list[InventoryItem]:
    """Reconstruye `InventoryItem` reales desde la base de datos, en la misma forma que produce
    `inventory.scanner.escanear_directorio()` -- para que `reports/inventory_report.py` (sin
    cambios) se pueda reutilizar tal cual sobre el resultado de esta función."""
    condiciones = []
    parametros: list[str] = []
    if library_id is not None:
        condiciones.append("library_id = ?")
        parametros.append(library_id)
    if content_type is not None:
        condiciones.append("content_type = ?")
        parametros.append(content_type.value)
    if state is not None:
        condiciones.append("item_state = ?")
        parametros.append(state.value)

    sql = "SELECT * FROM inventory_items"
    if condiciones:
        sql += " WHERE " + " AND ".join(condiciones)
    sql += " ORDER BY current_path"

    filas = conn.execute(sql, parametros).fetchall()
    return [_item_desde_fila(fila) for fila in filas]


def actualizar_estado(
    conn: sqlite3.Connection, item_id: uuid.UUID, nuevo_estado: ItemState, ahora: datetime,
) -> None:
    """Única función de todo el proyecto con permiso de escribir `item_state` -- siempre valida
    la transición con `domain.states.transicion_permitida()` antes del `UPDATE` (regla explícita
    del plan y de CLAUDE.md: ninguna mutación sin pasar por la máquina de estados). Lanza
    `ValueError` si el item no existe o si la transición no está permitida -- nunca aplica el
    `UPDATE` en ninguno de esos dos casos."""
    fila = conn.execute(
        "SELECT item_state FROM inventory_items WHERE id = ?", (str(item_id),),
    ).fetchone()
    if fila is None:
        raise ValueError(f"No existe ningún item de inventario con id={item_id}")

    estado_actual = ItemState(_texto(fila, "item_state"))
    if not transicion_permitida(estado_actual, nuevo_estado):
        raise ValueError(
            f"Transición no permitida: {estado_actual.value} -> {nuevo_estado.value}"
        )

    conn.execute(
        "UPDATE inventory_items SET item_state = ?, updated_at = ? WHERE id = ?",
        (nuevo_estado.value, ahora.isoformat(), str(item_id)),
    )
    conn.commit()


# --- Fase 8: reconciliación catálogo <-> transacciones -------------------------------------------
#
# `reconciliar_transaccion()`/`reconciliar_reversion()` traducen el resultado REAL de
# `transactions/engine.py` (el único escritor real de archivos, invariante #2 de CLAUDE.md) a
# metadatos de catálogo -- nunca reimplementan ni fabrican ese resultado, solo leen `Journal`/
# `RollbackResult` tal cual los devuelve el motor. `current_path` es una columna libre (se puede
# escribir directamente), pero `item_state` solo se mueve a través de `actualizar_estado()`, que ya
# valida cada salto con `transicion_permitida()` -- igual que el resto de este módulo.


def _fila_por_ruta(conn: sqlite3.Connection, library_id: str, current_path: str) -> sqlite3.Row | None:
    fila: sqlite3.Row | None = conn.execute(
        "SELECT id, item_state FROM inventory_items WHERE library_id = ? AND current_path = ?",
        (library_id, current_path),
    ).fetchone()
    return fila


def _camino_de_estados(origen: ItemState, destino: ItemState) -> list[ItemState] | None:
    """Secuencia de estados intermedios (sin incluir `origen`) hasta `destino`, siguiendo solo
    transiciones que `transicion_permitida()` ya aprueba -- búsqueda en anchura sobre ese grafo, en
    vez de duplicar `_TRANSICIONES` (privado de `domain/states.py`). Devuelve `[]` si ya se está en
    destino, o `None` si destino no es alcanzable (p.ej. `origen` es un estado terminal distinto)."""
    if origen == destino:
        return []
    cola: deque[ItemState] = deque([origen])
    padres: dict[ItemState, ItemState] = {}
    visitados: set[ItemState] = {origen}
    while cola:
        actual = cola.popleft()
        for siguiente in ItemState:
            if siguiente in visitados or not transicion_permitida(actual, siguiente):
                continue
            padres[siguiente] = actual
            if siguiente == destino:
                camino = [siguiente]
                while camino[-1] != origen:
                    camino.append(padres[camino[-1]])
                camino.pop()  # quita el propio origen
                camino.reverse()
                return camino
            visitados.add(siguiente)
            cola.append(siguiente)
    return None


def _avanzar_estado(
    conn: sqlite3.Connection, item_id: uuid.UUID, estado_actual: ItemState,
    estado_objetivo: ItemState, ahora: datetime,
) -> None:
    """Recorre el camino legal (si existe) de `estado_actual` a `estado_objetivo`, llamando a
    `actualizar_estado()` en cada salto -- nunca un `UPDATE` directo de `item_state`. Si el
    objetivo no es alcanzable (p.ej. el item ya está en un estado terminal distinto, como
    `verified`/`rolled_back`), se deja `item_state` tal cual -- documentado como límite conocido,
    igual que `transactions/engine.py` documenta los suyos, en vez de forzar un estado falso o
    lanzar una excepción que ocultaría el resultado real ya escrito en disco."""
    camino = _camino_de_estados(estado_actual, estado_objetivo)
    if camino is None:
        return
    for siguiente in camino:
        actualizar_estado(conn, item_id, siguiente, ahora)


_ESTADOS_APLICACION_AMBIGUOS: frozenset[OperationStatus] = frozenset({
    OperationStatus.FALLIDA_VERIFICACION,  # puede haberse movido igualmente -- ver docstring abajo
    OperationStatus.PENDIENTE,             # el proceso murió antes de intentar esta operación
    OperationStatus.EN_APLICACION,         # el proceso murió a mitad del movimiento real
})


def _estado_objetivo_tras_aplicar(status: OperationStatus) -> ItemState:
    if status == OperationStatus.APLICADA:
        return ItemState.APPLIED
    if status in _ESTADOS_APLICACION_AMBIGUOS:
        # Invariante #8 de CLAUDE.md: ante ambigüedad, siempre needs_review humano -- nunca se
        # decide sin evidencia. `fallida_verificacion` en concreto puede significar tanto "nunca se
        # tocó el origen" (copia entre filesystems distintos que no llegó a publicarse) como "sí se
        # movió pero el hash tras mover no coincidía" (mismo filesystem, hardlink+unlink ya
        # irreversible) -- transactions/engine.py no lo distingue en el propio status, así que este
        # módulo tampoco inventa la respuesta.
        return ItemState.NEEDS_REVIEW
    # error_aplicacion / conflicto_destino / fuera_de_raiz / requiere_revision_manual / omitida --
    # en TODOS estos casos el origen nunca llegó a tocarse (ver transactions/engine.py:
    # _aplicar_operacion/_mover_archivo_verificado): el archivo real sigue en source_path.
    return ItemState.FAILED


def reconciliar_transaccion(
    conn: sqlite3.Connection, journal: Journal, library_id: str, ahora: datetime,
) -> None:
    """Reconcilia el catálogo SQLite con el resultado REAL de
    `transactions.engine.aplicar_plan()` -- lee las entradas del `Journal` tal cual las persistió
    el motor transaccional (nunca las reimplementa ni fabrica un resultado a mano). Por cada
    operación, busca la fila por `(library_id, current_path=source_path)` -- la ruta que el item
    tenía ANTES de esta transacción -- y, si existe:

    - `aplicada`: el archivo se movió y se verificó por hash dentro del propio motor. `current_path`
      pasa a `destination_path` y el estado avanza (vía `actualizar_estado()`, un salto legal cada
      vez) hasta `ItemState.APPLIED`. Deliberadamente NUNCA hasta `ItemState.VERIFIED`, aunque el
      motor ya verificó el hash: `VERIFIED` es terminal en `domain/states.py` (sin transiciones
      salientes), y dejaría sin camino legal una reversión posterior -- `APPLIED -> ROLLED_BACK` sí
      existe en el grafo de estados precisamente para este caso, `VERIFIED -> ROLLED_BACK` no.
    - Cualquier otro status: ver `_estado_objetivo_tras_aplicar()` -- `current_path` NUNCA se toca
      (el archivo no se movió, o es ambiguo si se movió), solo cambia `item_state`.

    Un item cuya `(library_id, source_path)` no está en el catálogo (nunca se hizo `catalog sync`
    sobre él, o se sincronizó bajo otra `library_id`) se ignora en silencio -- el catálogo SQLite es
    una vista derivada opcional del inventario real, reconciliar solo actualiza lo que ya conocía."""
    for entrada in journal.operations:
        fila = _fila_por_ruta(conn, library_id, entrada.source_path)
        if fila is None:
            continue
        item_id = uuid.UUID(_texto(fila, "id"))
        estado_actual = ItemState(_texto(fila, "item_state"))

        if entrada.status == OperationStatus.APLICADA:
            conn.execute(
                "UPDATE inventory_items SET current_path = ?, updated_at = ? WHERE id = ?",
                (entrada.destination_path, ahora.isoformat(), str(item_id)),
            )
            conn.commit()
            _avanzar_estado(conn, item_id, estado_actual, ItemState.APPLIED, ahora)
        else:
            objetivo = _estado_objetivo_tras_aplicar(entrada.status)
            _avanzar_estado(conn, item_id, estado_actual, objetivo, ahora)


def reconciliar_reversion(
    conn: sqlite3.Connection, rollback: RollbackResult, library_id: str, ahora: datetime,
) -> None:
    """Simétrica a `reconciliar_transaccion()`, para el resultado REAL de
    `transactions.engine.revertir_transaccion()`. Por cada operación de `rollback.operations` (solo
    las que llegaron a estar `aplicada` -- ver docstring de `revertir_transaccion`), busca la fila
    primero por su `current_path` POST-aplicación (`destination_path` de la entrada -- el caso
    normal, si `reconciliar_transaccion()` ya se llamó tras el `apply` correspondiente) y, si no la
    encuentra, por su `current_path` PRE-aplicación (`source_path` -- el caso de un `rollback --db`
    sobre una transacción cuyo `apply` nunca usó `--db`: el catálogo nunca llegó a registrar el
    movimiento, así que la ruta guardada ya es la correcta y solo hace falta ajustar el estado).

    - `revertida`: el archivo ya está de vuelta en `source_path`, verificado por hash dentro del
      propio motor. `current_path` vuelve a `source_path` (si hacía falta) y el estado avanza hasta
      `ItemState.ROLLED_BACK` (terminal, y transición directa válida desde `APPLIED`).
    - Cualquier otro resultado (`error_reversion`, o una guarda de symlink/hardlink detectada
      durante la propia reversión) es ambiguo sobre dónde está realmente el archivo -- nunca se
      asume una respuesta: pasa a `ItemState.NEEDS_REVIEW` (invariante #8 de CLAUDE.md),
      `current_path` NO se toca."""
    for entrada in rollback.operations:
        fila = _fila_por_ruta(conn, library_id, entrada.destination_path)
        ruta_ya_reconciliada = fila is not None
        if fila is None:
            fila = _fila_por_ruta(conn, library_id, entrada.source_path)
        if fila is None:
            continue
        item_id = uuid.UUID(_texto(fila, "id"))
        estado_actual = ItemState(_texto(fila, "item_state"))

        if entrada.status == OperationStatus.REVERTIDA:
            if ruta_ya_reconciliada:
                conn.execute(
                    "UPDATE inventory_items SET current_path = ?, updated_at = ? WHERE id = ?",
                    (entrada.source_path, ahora.isoformat(), str(item_id)),
                )
                conn.commit()
            _avanzar_estado(conn, item_id, estado_actual, ItemState.ROLLED_BACK, ahora)
        else:
            _avanzar_estado(conn, item_id, estado_actual, ItemState.NEEDS_REVIEW, ahora)
