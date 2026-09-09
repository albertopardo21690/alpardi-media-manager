# SECURITY.md

## Secretos

- Ningún secreto real en git — `.env` está en `.gitignore`, solo `.env.example` (sin valores) va
  al repo.
- El token de Plex se **reutiliza** del ya existente en `/root/.config/alpardios/plex.env`
  (permisos 600) — no se duplica ni se copia a un fichero nuevo.
- Credenciales de proveedores: referencias `keyring://alpardi-media/<nombre>` en
  `config/providers.example.yaml` — nunca la clave real en el YAML.
- Ningún log, informe, fixture de test o mensaje de Claude debe mostrar un secreto. Redactar
  siempre (`***`) antes de imprimir cabeceras de autenticación.

## Mínimo privilegio

- El adaptador Plex nunca escribe en su base de datos SQLite — solo su API HTTP autenticada.
- El motor transaccional es el único componente con permiso de escritura sobre rutas de medios,
  limitado a una allowlist normalizada resuelta tras seguir enlaces simbólicos.
- Ningún comando puede recibir una ruta arbitraria como argumento directo para una operación con
  efectos — solo IDs de plan ya validados (regla explícita del encargo).

## Datos salientes (ver `docs/PRIVACY-EGRESS.md` para la tabla completa)

Ningún proveedor recibe tráfico mientras `enabled: false` (todos lo están hoy). Antes de activar
cualquiera, se muestra qué dato sale y con qué motivo, y se pide consentimiento explícito por tipo
de dato (no se deduce un consentimiento de otro). Nunca se envían archivos audiovisuales, imágenes
familiares ni rutas completas — solo lo mínimo necesario (título saneado, IDs, hash de huella
cuando el usuario lo autorice explícitamente).

## Claude Code

- `/plex-apply` y `/plex-rollback` llevan `disable-model-invocation: true` (confirmado como
  mecanismo real vigente, ver `docs/SOURCES.md`) — invocables solo por Alberto escribiendo el
  comando él mismo, nunca automáticamente por el modelo. Son las dos únicas skills que mutan la
  colección multimedia real.
- Los hooks `PreToolUse` bloquean `rm`, `mv`, `cp`, `rsync --delete`, `find -delete` y escrituras
  directas sobre raíces multimedia vía `Bash`, salvo la ruta controlada por el motor transaccional
  con un plan autorizado — la regla vive en código (`.claude/settings.json` + script del hook), no
  solo en instrucciones de texto. Ver `docs/OPERATIONS.md` para el detalle probado.
- **Decisión de diseño del servidor MCP (`mcp/server.py`)**: expone solo 6 herramientas
  DELIBERADAMENTE de solo lectura (`doctor`, `plex_libraries`, `inventory_scan`,
  `providers_status`, `match_check`, `plan_rename_preview`) — ninguna escribe un byte en disco, ni
  siquiera un plan. `apply`, `rollback` y `backup create` NUNCA se exponen como herramientas MCP:
  a diferencia de una skill con `disable-model-invocation: true`, una herramienta MCP SÍ es
  invocable por el propio modelo sin que Alberto escriba nada — exponer una operación mutadora ahí
  habría abierto exactamente el camino de autoautorización que el encargo prohíbe. Esas tres
  operaciones solo existen como skills gestionadas por Alberto, que a su vez llaman a la CLI real.
  Probado con una prueba de integración real (`tests/integration/test_mcp_server_real.py`) que
  confirma la lista de herramientas expuestas y que ninguna herramienta prohibida aparece nunca.

## Incidente relevante de este mismo entorno (contexto, no un fallo de este proyecto)

El NAS Alpardimedia tiene `sudo` roto desde 2026-09-04 y un disco fallando activamente desde
2026-09-08 — por eso este proyecto corre en el VPS, no en el NAS (ver `docs/DECISIONS.md` #12).
