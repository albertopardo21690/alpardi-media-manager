# OPERATIONS.md

## Arranque (desarrollo, hoy)

```bash
cd /opt/alpardi-media-manager
./.venv/bin/pytest && ./.venv/bin/ruff check src tests && ./.venv/bin/mypy src
```

## Despliegue real (pendiente, Fase 4/5)

`deploy/systemd/` y `deploy/docker/` existen como carpetas vacías en el scaffold — se rellenarán
cuando el motor tenga sentido ejecutarlo como servicio (escaneos incrementales programados). Hasta
entonces, todo se ejecuta manualmente desde la CLI o desde Claude Code, nunca como daemon.

## Ejecución cerca de los datos

Ver `docs/ARCHITECTURE.md` — el gestor corre en el VPS, accede al NAS por SSH/SFTP. Revisar esta
decisión (`docs/DECISIONS.md` #12) si el disco 1 del NAS se sustituye y el `sudo` se repara.

## Hooks de seguridad (`.claude/settings.json` + `.claude/hooks/`)

Dos hooks `PreToolUse`, probados con 22 tests reales (`tests/unit/test_hooks.py`, invocan el
script exactamente como lo hace Claude Code -- JSON por stdin, veredicto por código de salida):

- `pre_tool_use_bash_guard.py` (matcher `Bash`): bloquea `rm`, `mv`, `cp`, `rsync --delete` y
  `find -delete`/`find -exec rm` **siempre**, sin excepción de ruta -- la CLI real nunca necesita
  invocar estos verbos por shell (el motor transaccional usa llamadas de Python directas), así que
  bloquearlos sin excepción no le quita ninguna capacidad real, solo cierra el bypass. Tokeniza el
  comando entero de una vez y busca cada verbo como token exacto en cualquier posición -- un diseño
  anterior que dividía por `;` antes de tokenizar se rompía con `find -exec rm {} \;` (el `;` de
  escape de find se confundía con un separador de comandos); corregido y con test de regresión
  explícito para ese caso exacto.
- `pre_tool_use_media_write_guard.py` (matcher `Write|Edit`): bloquea escribir/editar directamente
  cualquier archivo con extensión de vídeo/audio/imagen/subtítulo, sin importar la ruta -- Write y
  Edit son para código y texto; cualquier operación real sobre un archivo multimedia pasa siempre
  por el motor transaccional.

Verificar que Claude Code los ha cargado: `/hooks` dentro de una sesión en este proyecto, o
`claude doctor` desde `/opt/alpardi-media-manager`. Límite conocido y documentado en el propio
docstring de cada script: es un análisis léxico best-effort, no un sandbox -- ver `docs/SECURITY.md`.
