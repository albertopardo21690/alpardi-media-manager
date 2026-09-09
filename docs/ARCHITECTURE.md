# ARCHITECTURE.md

Arquitectura en capas, tal como exige el encargo (sección "Arquitectura mínima requerida"). Cada
capa solo puede depender de las que están por debajo en esta lista — nunca al revés.

```text
┌─────────────────────────────────────────────────────────────────┐
│ Claude Code: skills (.claude/skills/), reglas, hooks             │
├─────────────────────────────────────────────────────────────────┤
│ CLI (humana + --json)          │  MCP stdio (herramientas tipadas)│
├─────────────────────────────────────────────────────────────────┤
│ Informes y observabilidad (reports/) -- logs, métricas, diagnóstico│
│ Copia de seguridad (backup/) -- plans/journals/reports/config, nunca medios│
├─────────────────────────────────────────────────────────────────┤
│ Motor transaccional (transactions/) -- journal, aplicación, rollback│
│ Planificador (planning/) -- planes inmutables, nunca toca archivos │
├─────────────────────────────────────────────────────────────────┤
│ Adaptador Plex (plex/) -- API mínimo privilegio, nunca SQLite     │
│ Políticas Plex (policies/) -- plantillas de nombres/rutas/NFO     │
│ Motor de coincidencias (matching/) -- candidatos, evidencia, cola │
├─────────────────────────────────────────────────────────────────┤
│ Proveedores (providers/) -- adaptadores aislados, cada uno opt-in │
├─────────────────────────────────────────────────────────────────┤
│ Analizadores (parsers/) -- nombres, NFO, ffprobe, MediaInfo, etc. │
│ Inventario (inventory/) -- exploración incremental, sidecars      │
├─────────────────────────────────────────────────────────────────┤
│ Dominio (domain/) -- modelos puros, máquina de estados            │
├─────────────────────────────────────────────────────────────────┤
│ Base de datos: SQLite local a ESTA máquina (VPS) -- migrations/  │
└─────────────────────────────────────────────────────────────────┘
```

`mcp/server.py` expone deliberadamente MENOS que la CLI: solo las 6 herramientas de solo lectura
(`doctor`, `plex_libraries`, `inventory_scan`, `providers_status`, `match_check`,
`plan_rename_preview`). `apply`, `rollback` y `backup create` existen solo como skills con
`disable-model-invocation: true` que invocan la CLI real -- nunca como herramientas MCP, porque
una herramienta MCP SÍ es invocable por el propio modelo sin que Alberto escriba nada (ver
docs/SECURITY.md para el razonamiento completo).

## Por qué esta separación

- **`domain/` no importa nada de fuera de sí mismo.** Es la única capa que otros pueden asumir
  estable — cambiar cómo se guarda en SQLite o cómo se llama a TMDb nunca debe forzar a tocar
  `domain/models.py`. Ya probado con 22 tests sin ninguna dependencia de I/O.
- **`providers/` nunca escribe.** El contrato (`providers/base.py`) solo expone `search`, `get`,
  `find_by_external_id`, `healthcheck` — los cuatro de solo lectura. La escritura real (NFO,
  arte, renombrado) vive exclusivamente en `transactions/`, y solo tras un plan autorizado.
- **`planning/` produce planes inmutables sin tocar archivos.** Un plan es un dato, no una acción
  — se puede inspeccionar, comparar, cachear o descartar sin ningún efecto secundario.
- **`transactions/` es el único sitio del proyecto con permiso real de escritura** sobre rutas de
  medios, y solo dentro de una allowlist normalizada, resuelta tras seguir enlaces simbólicos
  (regla explícita del encargo para evitar escapar de las raíces autorizadas).
- **`plex/` nunca toca la base de datos SQLite de Plex directamente** — solo su API HTTP, con el
  token ya existente (`/root/.config/alpardios/plex.env`, reutilizado, no duplicado).

## Dónde vive físicamente

Ver `docs/DECISIONS.md` #12: todo el proyecto (código + SQLite) corre en el VPS
(`/opt/alpardi-media-manager`), nunca en el NAS mientras su disco 1 siga fallando. El acceso a los
archivos reales del NAS es por SSH/SFTP (`NASAlpardimedia`, ya configurado en
`~/.ssh/config`), nunca por montaje SMB — así SQLite nunca atraviesa una red, cumpliendo la regla
de fondo del encargo aunque no se ejecute literalmente "en el NAS".

## Estado real de cada capa (actualizar en cada incremento)

| Capa | Estado | Módulos con código real |
|---|---|---|
| `domain/` | Núcleo probado | `models.py`, `states.py` |
| `providers/` | Contrato probado, sin adaptadores concretos; estado de configuración (`enabled`/`credential_ref`, solo lectura del YAML, cero red) probado | `base.py`, `models.py`, `status.py` |
| `inventory/` | Núcleo probado (huellas, sidecars, escáner con protección anti-symlink) | `fingerprint.py`, `sidecars.py`, `scanner.py` |
| `parsers/` | Interpretación de nombres probada | `filename.py` |
| `policies/` | Generación de nombres probada (nunca renombra) | `naming.py` |
| `matching/` | Motor de coincidencias probado, las 6 reglas innegociables cubiertas; ahora conectado a la CLI (`match check`) con lista de candidatos vacía mientras no haya proveedores activos -- todo resulta honestamente `needs_review`, nunca una coincidencia inventada | `engine.py` |
| `planning/` | Planes inmutables + detección de conflictos + frase de autorización, probado | `plan.py` |
| `transactions/` | Motor de aplicación probado (132 tests en el proyecto), revisado adversarialmente por 4 ángulos de seguridad independientes (2026-09-09): 14 hallazgos, los 4 críticos corregidos + 7 más (11/14 en total); 3 de severidad baja/media documentados como límite conocido en el propio docstring del módulo, no ocultados | `engine.py` |
| `plex/` | Adaptador solo lectura probado (unitario + integración real contra el Plex de Alberto) | `models.py`, `client.py` |
| `reports/` | Informes probados (Markdown/JSON/CSV): plan, resultado de aplicación/reversión, inventario | `plan_report.py`, `transaction_report.py`, `inventory_report.py` |
| `cli/` | `doctor`, `plex inspect`, `inventory scan`, `export`, `rollback`, `plan rename`, `apply`, `providers status`, `match check`, `backup create`/`backup verify` -- todos reales y probados (unit + integración real contra Plex/NAS). `plan rename`/`apply` son dos invocaciones de proceso separadas que solo comparten el plan como JSON en disco (`planning/plan.py`: `guardar_plan`/`cargar_plan`), tal como pasa en el uso real. v1 solo cubre películas (`content_type=movie`); TV/música quedan para un incremento posterior | `main.py`, `checks.py`, `config.py` |
| `backup/` | Copia de `plans/`/`journals/`/`reports/`/`config/*.yaml` reales (nunca de los medios) con sha256 + verificación real (extrae de verdad, no solo comprueba que el fichero existe); probado | `engine.py` |
| `mcp/` | Servidor stdio real, 6 herramientas DELIBERADAMENTE de solo lectura (nunca `apply`/`rollback`/`backup create` -- ver docs/SECURITY.md); probado con una prueba de integración real que habla el protocolo MCP de verdad con el SDK oficial (subprocess + `ClientSession`) | `server.py` |
| `.claude/hooks/` | 2 hooks `PreToolUse` reales (bloqueo de Bash peligroso + escritura directa sobre extensiones multimedia), probados con 22 tests que invocan los scripts tal cual los invoca Claude Code | `pre_tool_use_bash_guard.py`, `pre_tool_use_media_write_guard.py` |
| `.claude/skills/` | En marcha | — |
