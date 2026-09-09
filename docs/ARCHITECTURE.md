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
| `providers/` | Contrato probado, sin adaptadores concretos | `base.py`, `models.py` |
| `inventory/`, `parsers/`, `matching/`, `policies/`, `planning/`, `transactions/`, `plex/`, `reports/` | Solo esqueleto (`__init__.py` vacío) | — |
| `cli/` | `doctor` real y probado (unit + integración real contra Plex/NAS) | `main.py`, `checks.py`, `config.py` |
| `mcp/` | No empezado | — |
| `.claude/skills/`, `.claude/hooks/` | No empezado | — |
