"""Capa "Base de datos" del diagrama de `docs/ARCHITECTURE.md` -- la más baja de todas. Sin
ningún import de `domain/` a propósito: conectar, migrar y hacer un checkpoint consistente para
backup son operaciones de infraestructura pura, ajenas a qué significan las columnas.

`persistence/catalog.py` (una capa por encima, sí puede importar `domain/`) es quien traduce
entre `InventoryItem` y las filas que este módulo sabe abrir/migrar.
"""
from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

# Mismo patrón que policies/naming.py::RUTA_POLITICAS_DEFECTO -- ruta calculada relativa a la
# ubicación del propio paquete, no al cwd desde el que se invoque la CLI.
RUTA_MIGRACIONES_DEFECTO = Path(__file__).parent.parent.parent.parent / "migrations"


def abrir_conexion(
    ruta: Path,
    auto_migrar: bool = True,
    migrations_dir: Path = RUTA_MIGRACIONES_DEFECTO,
) -> sqlite3.Connection:
    """Abre (o crea) la base de datos SQLite en `ruta`. Activa WAL + claves foráneas en CADA
    conexión (no son "pegajosas" por conexión salvo journal_mode, que sí es una propiedad del
    fichero -- pero se reafirma igualmente para que el comportamiento no dependa de qué conexión
    lo activó primero) y usa `sqlite3.Row` como row_factory para que el código de arriba pueda
    leer columnas por nombre en vez de por posición."""
    ruta.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(ruta)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    if auto_migrar:
        aplicar_migraciones(conn, migrations_dir)
    return conn


def aplicar_migraciones(
    conn: sqlite3.Connection, migrations_dir: Path = RUTA_MIGRACIONES_DEFECTO,
) -> list[int]:
    """Aplica, en orden, cada `NNNN_descripcion.sql` de `migrations_dir` que todavía no conste en
    `schema_migrations` -- idempotente: una segunda llamada sobre una base ya migrada no repite
    ningún `CREATE TABLE` (fallaría) ni nada en general. Devuelve las versiones recién aplicadas.

    Deliberadamente no crea `schema_migrations` por su cuenta -- esa tabla la crea la propia
    migración 0001 (`CREATE TABLE IF NOT EXISTS`), una única fuente de verdad para su DDL."""
    existe_tabla_control = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'schema_migrations'"
    ).fetchone()
    aplicadas_previas: set[int] = set()
    if existe_tabla_control is not None:
        aplicadas_previas = {
            int(fila[0]) for fila in conn.execute("SELECT version FROM schema_migrations")
        }

    aplicadas_ahora: list[int] = []
    for ruta_sql in sorted(migrations_dir.glob("*.sql")):
        version = int(ruta_sql.stem.split("_", 1)[0])
        if version in aplicadas_previas:
            continue
        descripcion = ruta_sql.stem.split("_", 1)[1].replace("_", " ")
        conn.executescript(ruta_sql.read_text(encoding="utf-8"))
        conn.execute(
            "INSERT INTO schema_migrations (version, applied_at, description) VALUES (?, ?, ?)",
            (version, datetime.now(UTC).isoformat(), descripcion),
        )
        conn.commit()
        aplicadas_ahora.append(version)
    return aplicadas_ahora


def checkpoint_para_backup(origen: Path, destino: Path) -> None:
    """Produce un snapshot consistente de un solo fichero (sin `-wal`/`-shm`) con `VACUUM INTO`
    (verificado real con SQLite 3.46.1, la versión de este proyecto). Nunca se empaqueta el
    `.sqlite3` vivo directamente para backup -- en modo WAL, el dato más reciente puede estar solo
    en el fichero `-wal`, todavía no volcado al fichero principal."""
    destino.parent.mkdir(parents=True, exist_ok=True)
    if destino.exists():
        destino.unlink()
    conn = sqlite3.connect(origen)
    try:
        conn.execute("VACUUM INTO ?", (str(destino),))
    finally:
        conn.close()
