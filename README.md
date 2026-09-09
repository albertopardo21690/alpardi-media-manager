# AlpardiMedia Manager

Gestor multimedia conversacional para Plex, controlado íntegramente desde Claude Code (lenguaje
natural + CLI + servidor MCP local por `stdio`). Sin panel web, sin GUI, sin puerto propio
escuchando.

**Estado: Fases 0-4 completas.** Núcleo (dominio, inventario, políticas, coincidencias,
planificación, motor transaccional, adaptador Plex, informes), CLI real, servidor MCP de solo
lectura y las 9 skills de Claude Code, con hooks de seguridad reales. Queda Fase 5 (piloto real
con un lote pequeño, autorizado a mano) y los adaptadores concretos de proveedores (bloqueados
hasta que Alberto cree credenciales). Ver `docs/DECISIONS.md` para las decisiones ya tomadas,
`docs/SOURCES.md` para las fuentes oficiales consultadas, y `CLAUDE.md` para las reglas
permanentes del proyecto.

## Por qué existe

Reproduce el flujo funcional de tinyMediaManager (inventario, metadatos con trazabilidad,
generación de NFO, renombrado seguro, detección de duplicados/ediciones/versiones) orientado
específicamente a Plex, sin copiar su interfaz ni su implementación. Plex sigue siendo el único
servidor de reproducción — este proyecto nunca escribe directamente en su base de datos SQLite.

## Dónde vive y cómo accede a los datos

Corre en este VPS (`srv1435603`), con su base de datos SQLite 100% local aquí — nunca sobre una
ruta de red. El NAS (`Alpardimedia`, servidor Plex real) se accede por SSH/SFTP, nunca por
montaje SMB con SQLite encima. Motivo completo en `docs/DECISIONS.md` (decisión #12).

## Arranque rápido (desarrollo)

```bash
python3.14 -m venv .venv
./.venv/bin/pip install -e ".[dev]"
./.venv/bin/pytest
./.venv/bin/ruff check src tests
./.venv/bin/mypy src
```

Ningún comando de este proyecto escribe sobre bibliotecas de Plex reales sin un plan explícito
autorizado por Alberto (`AUTORIZO APLICAR PLAN <id> SOBRE <n> ELEMENTOS`, ver `docs/ROLLBACK.md`):
`alpardi-media plan rename` → `alpardi-media apply` es el único camino real, y solo tras esa frase
exacta.

## Uso desde Claude Code

Dentro de una sesión de Claude Code abierta en este directorio: `/plex-doctor`, `/plex-audit`,
`/plex-inventory`, `/plex-search`, `/plex-providers`, `/plex-plan`, `/plex-apply`, `/plex-rollback`,
`/plex-backup` (ver `.claude/skills/`). `/plex-apply` y `/plex-rollback` solo se pueden invocar
escribiendo el comando tú mismo — el modelo no puede invocarlos automáticamente
(`disable-model-invocation: true`, confirmado real).

## Estructura

Ver el árbol completo en el propio repositorio. Resumen de las carpetas con contenido real:

- `src/alpardi_media_manager/` — dominio, inventario, parsers, políticas, coincidencias,
  planificación, motor transaccional, adaptador Plex, informes, backup, CLI y servidor MCP.
  Todos probados (`docs/ARCHITECTURE.md` tiene el estado exacto de cada capa).
- `src/alpardi_media_manager/providers/` — contrato común de proveedores (`base.py`, `models.py`)
  + estado de configuración (`status.py`), sin ningún adaptador concreto todavía (perfil B
  elegido, sin credenciales creadas aún).
- `config/` — ejemplos de configuración, todo desactivado por defecto (`enabled: false`).
- `.claude/skills/`, `.claude/hooks/`, `.mcp.json` — integración real con Claude Code.
- `docs/` — decisiones, fuentes consultadas, y el resto de documentación exigida por el encargo.

## Seguridad, no negociable

- Nunca sube vídeos, imágenes familiares ni rutas privadas a ningún proveedor externo.
- Ningún proveedor queda activo sin credencial real Y consentimiento explícito por tipo de dato.
- Ninguna mutación sobre archivos reales sin plan inmutable + autorización explícita del usuario.
- Nunca borra — solo mueve a cuarentena, y solo tras autorización.
