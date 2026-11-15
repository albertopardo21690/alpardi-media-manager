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

## Vigilante de vídeo del NAS (solo lectura, desde 2026-11-15)

Módulo `alpardi_media_manager.watch` + `deploy/systemd/alpardimedia-watch.{service,timer}` (instalados en
`/etc/systemd/system/`; ejecución diaria a las 05:40 hora de Madrid, `Persistent=true`).

- **Qué hace:** instantánea de los vídeos del NAS por SSH (`find`+`stat`; el NAS usa BusyBox, sin `-printf`),
  salta las carpetas privadas (`Zona privada`, `Videos mensuales MJ`, `Dedicatorias`, `_admin`, `_toolkit`,
  `_incoming_*`), detecta nuevos/desaparecidos/modificados, clasifica los nuevos (¿siguen el nombrado Plex?
  ¿están en `_General_Inbox`?) y busca duplicados: mismo tamaño + distinto inodo + SHA-256 de los primeros y
  últimos 4 MiB. Los enlaces duros (mismo inodo) no cuentan: son duplicados ya resueltos.
- **Qué NO hace:** no mueve, renombra ni borra nada, no toca Plex. Un fichero tocado hace menos de 15 min se
  considera «en copia» y se evalúa en la siguiente ejecución.
- **Duplicados entre bibliotecas:** `Ciclos/<actor>/`, `VHS Digitalizados - Catalogo/Prueba/Peliculas`… repiten
  películas a propósito; el informe los separa de los de «misma biblioteca». Para ahorrar ese espacio sin quitar
  nada la vía es un enlace duro (como en la limpieza del 26-oct), no la cuarentena.
- **Salida:** `data/watch/ultimo.md` / `ultimo.json` / `informes/AAAA-MM-DD_HHMM.md` (no van a git).
  `instantanea.json` es la línea base; si se borra, la siguiente ejecución crea una nueva (sin avisos de «nuevos»).
- **Manual:** `./.venv/bin/python -m alpardi_media_manager.watch [--confirmar-gb N]`. `--confirmar-gb` añade SHA-256
  del fichero entero a los grupos pequeños hasta ese presupuesto de GB (lectura pesada del NAS; `nice`/`ionice`).
- **Pendiente (no implementado):** `plan quarantine` y `plan hardlink` (hoy solo existe `plan rename`); refresco
  de Plex (falta el token en este VPS y Plex no responde desde aquí); aviso al terminar.
- **Restaurar:** copiar `deploy/systemd/alpardimedia-watch.*` a `/etc/systemd/system/`,
  `systemctl daemon-reload && systemctl enable --now alpardimedia-watch.timer`.

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

## Verificación real de la integración con Claude Code (Fase 4, 2026-09-09)

Comandos oficiales usados para confirmar que Claude Code carga de verdad `CLAUDE.md`, las 9
skills y el servidor MCP -- no solo que los ficheros existen con el formato correcto:

```bash
cd /opt/alpardi-media-manager
CLAUDE_PROJECT_DIR="$(pwd)" claude doctor        # confirma .mcp.json y settings.json válidos
CLAUDE_PROJECT_DIR="$(pwd)" claude mcp list      # confirma que "alpardimedia-manager" aparece
CLAUDE_PROJECT_DIR="$(pwd)" claude -p "..." --strict-mcp-config   # ver resultado real abajo
```

Resultados reales obtenidos (versión de Claude Code instalada: 2.1.258):

- `claude doctor`: sin `CLAUDE_PROJECT_DIR` puesto a mano avisa de que `.mcp.json` referencia esa
  variable (correcto -- Claude Code la define solo dentro de una sesión real); con la variable
  puesta, "No installation issues found."
- `claude mcp list`: `alpardimedia-manager` aparece como `⏸ Pending approval (run 'claude' to
  approve)` -- exactamente el comportamiento documentado para un servidor de proyecto nuevo
  (aprobación interactiva la primera vez, ver `docs/SOURCES.md`). Alberto debe aprobarlo una vez
  al abrir una sesión real aquí.
- `claude -p` pidiendo listar las skills disponibles: devolvió las 7 skills normales
  (`plex-audit`, `plex-backup`, `plex-doctor`, `plex-inventory`, `plex-plan`, `plex-providers`,
  `plex-search`) -- **`plex-apply` y `plex-rollback` NO aparecieron**, confirmando en vivo (no
  solo por documentación) que `disable-model-invocation: true` hace que su descripción ni
  siquiera llegue al contexto del modelo.
- `claude -p` preguntando por una regla concreta de `CLAUDE.md` (el único componente con permiso
  real de escritura, y el formato exacto de la frase de autorización): respondió correctamente
  con datos que solo puede tener si `CLAUDE.md` se cargó de verdad.

Repetir esta pasada si se añade/quita una skill o se cambia `.mcp.json`/`settings.json` -- no dar
por hecho que Claude Code los recoge solo porque el fichero tiene el formato correcto.
