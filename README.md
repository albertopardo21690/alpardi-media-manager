# AlpardiMedia Manager

Gestor multimedia conversacional para Plex, controlado íntegramente desde Claude Code (lenguaje
natural + CLI + servidor MCP local por `stdio`). Sin panel web, sin GUI, sin puerto propio
escuchando.

**Estado: Fase 2 (scaffold) en curso.** Ver `docs/DECISIONS.md` para las decisiones ya tomadas y
`docs/SOURCES.md` para las fuentes oficiales consultadas hasta ahora.

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
autorizado por Alberto (`AUTORIZO APLICAR PLAN <id> SOBRE <n> ELEMENTOS`, ver
`docs/ROLLBACK.md`) — nada de esto existe todavía en esta fase del scaffold.

## Estructura

Ver el árbol completo en el propio repositorio. Resumen de las carpetas con contenido real hasta
ahora:

- `src/alpardi_media_manager/domain/` — modelos de dominio y máquina de estados (probado).
- `src/alpardi_media_manager/providers/` — contrato común de proveedores (`base.py`, `models.py`),
  sin ningún adaptador concreto todavía (perfil B elegido, sin credenciales creadas aún).
- `config/` — ejemplos de configuración, todo desactivado por defecto (`enabled: false`).
- `docs/` — decisiones, fuentes consultadas, y el resto de documentación exigida por el encargo
  (en progreso).

## Seguridad, no negociable

- Nunca sube vídeos, imágenes familiares ni rutas privadas a ningún proveedor externo.
- Ningún proveedor queda activo sin credencial real Y consentimiento explícito por tipo de dato.
- Ninguna mutación sobre archivos reales sin plan inmutable + autorización explícita del usuario.
- Nunca borra — solo mueve a cuarentena, y solo tras autorización.
