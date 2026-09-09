# CLAUDE.md — AlpardiMedia Manager

Gestor multimedia conversacional para Plex (tipo tinyMediaManager, sin copiarlo), controlado desde
Claude Code: CLI + skills + servidor MCP local por stdio. **Sin panel web, sin GUI, sin puerto
propio escuchando.** Responde a Alberto siempre en español de España.

Este fichero son las reglas PERMANENTES que nunca deben olvidarse. Todo lo demás vive en `docs/` —
léelo antes de decidir algo que estas reglas no cubran explícitamente.

## Invariantes que nunca se rompen

1. **Plex es el único servidor de reproducción.** Nunca se escribe en su base de datos SQLite —
   solo su API HTTP autenticada, con mínimo privilegio (`docs/PLEX_RULES.md`, `docs/SECURITY.md`).
2. **El motor transaccional (`transactions/engine.py`) es el ÚNICO sitio del proyecto con permiso
   real de escritura** sobre archivos multimedia. Ninguna otra capa —ni CLI, ni MCP, ni una skill—
   mueve, copia, borra o sobrescribe un archivo real por su cuenta.
3. **Ninguna mutación real sin: plan inmutable → preconditions → autorización humana explícita.**
   La frase de autorización es EXACTA, letra por letra: `AUTORIZO APLICAR PLAN <id> SOBRE <n>
   ELEMENTOS`. Nunca se infiere, nunca se completa, nunca se reutiliza si el inventario cambió.
   Claude nunca se autoautoriza a sí mismo.
4. **Nunca se borra automáticamente.** Solo cuarentena tras autorización explícita. Nunca se
   sobrescribe un destino que ya existe.
5. **El servidor MCP (`mcp/server.py`) es DELIBERADAMENTE de solo lectura.** `apply`, `rollback` y
   `backup create` solo existen como skills con `disable-model-invocation: true` — invocables solo
   por Alberto escribiendo el comando él mismo, nunca automáticamente por el modelo. Ver
   `docs/SECURITY.md` para el razonamiento completo antes de añadir una herramienta MCP nueva.
6. **Nunca se sube un archivo audiovisual/imagen real a un servicio externo.** Solo metadatos
   mínimos de emparejamiento, y solo con el consentimiento explícito por tipo de dato que exige
   `docs/PRIVACY-EGRESS.md`. Todos los proveedores están `enabled: false` por defecto — activar
   uno es siempre una decisión explícita de Alberto, nunca una inferencia del modelo.
7. **Nunca asumir un hecho del entorno que se puede verificar.** SO, rutas reales (¿existe un
   `Z:\` de Windows? ¿es realmente Linux al otro lado de un `current_path`?), versión real de
   Plex, límites reales de un proveedor — todo se comprueba, nunca se da por supuesto. Ver
   `docs/SOURCES.md` para las fuentes ya verificadas y su fecha.
8. **Ante ambigüedad o evidencia contradictoria, siempre `needs_review` humano** — nunca se decide
   por "la mayoría" ni por una puntuación de proveedor sin evidencia registrada
   (`matching/engine.py` documenta las 6 reglas innegociables).

## Dónde está cada cosa

| Pregunta | Documento |
|---|---|
| ¿Cómo están organizadas las capas y qué puede depender de qué? | `docs/ARCHITECTURE.md` |
| ¿Qué se decidió ya y por qué? | `docs/DECISIONS.md` |
| ¿Qué fuente oficial respalda esta regla de nombrado/API/hook? | `docs/SOURCES.md` |
| Reglas de nombrado/organización específicas de Plex | `docs/PLEX_RULES.md` |
| Secretos, privilegio mínimo, diseño del servidor MCP | `docs/SECURITY.md` |
| Qué sale a proveedores externos y con qué consentimiento | `docs/PRIVACY-EGRESS.md` |
| Cómo revertir una transacción aplicada | `docs/ROLLBACK.md` |
| Cómo restaurar/verificar un backup | `docs/BACKUP_RESTORE.md` |
| Matriz de proveedores, límites, atribución | `docs/PROVIDERS.md`, `docs/ATTRIBUTION.md` |
| Arrancar, comandos de verificación, hooks | `docs/OPERATIONS.md` |
| Problemas conocidos y su causa real | `docs/TROUBLESHOOTING.md` |

## Verificación obligatoria antes de dar por terminado cualquier cambio

```bash
cd /opt/alpardi-media-manager
./.venv/bin/ruff check src tests && ./.venv/bin/mypy src && ./.venv/bin/pytest -q
```

Los tests marcados `integration` (`pytest -m integration`) llaman de verdad al Plex y al NAS
reales de Alberto — nunca se sustituyen por mocks (regla explícita del encargo). Un fallo aislado
en `test_nas_real_es_alcanzable_por_ssh` puede ser el disco 1 del NAS degradándose (ver memoria de
sesión / `docs/TROUBLESHOOTING.md`), no necesariamente un bug de este cambio — compruébalo con
`ssh NASAlpardimedia echo ok` antes de asumir una cosa u otra.

## Disciplina de código

- Módulos pequeños, tipados (`mypy --strict`), con test real — nunca mockear lo que se puede
  probar de verdad contra el Plex/NAS reales de Alberto en `tests/integration/`.
- Cada capa solo importa de las que están por debajo en `docs/ARCHITECTURE.md`. En particular,
  `cli/` y `mcp/` son capas HERMANAS: ninguna importa de la otra — lo que necesitan ambas (config,
  diagnóstico, lógica de planificación/coincidencia) vive fuera de `cli/`.
- Cuando se verifica algo de Claude Code (frontmatter de skill, formato de hook, `.mcp.json`), la
  fuente es la documentación oficial vigente (`code.claude.com/docs/en/...`), registrada con fecha
  en `docs/SOURCES.md` — nunca una suposición de una versión anterior recordada de memoria.

## Skills (`.claude/skills/`)

Cada skill es un envoltorio fino sobre un comando real de la CLI — nunca reimplementa lógica en
prosa. `/plex-apply` y `/plex-rollback` llevan `disable-model-invocation: true` porque son las dos
únicas operaciones que mutan la colección multimedia real:

`/plex-doctor` `/plex-audit` `/plex-inventory` `/plex-search` `/plex-providers` `/plex-plan`
`/plex-apply` `/plex-rollback` `/plex-backup`

## Ecosistema real (verificado, no asumido)

VPS `srv1435603` (este host) — NAS `Alpardimedia` / `100.75.202.28` (servidor Plex real, disco 1
degradándose, ver `docs/TROUBLESHOOTING.md`) — PC Windows `Alpardimedia` / `100.108.43.100`, todos
conectados por Tailscale. Este proyecto corre en el VPS, nunca en el NAS (`docs/DECISIONS.md` #12).
