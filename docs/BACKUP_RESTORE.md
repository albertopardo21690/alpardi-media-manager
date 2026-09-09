# BACKUP_RESTORE.md

## Estado actual (Fase 2 — solo código, sin datos reales todavía)

El único "backup" real necesario hoy es el propio repositorio Git, porque no existe todavía base
de datos con inventario real, ni credenciales, ni ninguna transacción aplicada:

- Repo: `github.com/albertopardo21690/alpardi-media-manager` (privado).
- Cada commit significativo se pushea inmediatamente — ver `git log`.

## Qué habrá que respaldar cuando el sistema esté en uso real (todavía no implementado)

Según el encargo, en producción el backup deberá incluir:

- Código y configuración del proyecto → ya cubierto por git.
- Base de datos SQLite (`data/alpardi_media_manager.sqlite3`) y sus migraciones.
- Planes, journals e informes (`reports/`, `plans/`, `journals/` — hoy en `.gitignore` a
  propósito, pueden contener nombres de archivo privados).
- Configuración de Claude Code creada por el proyecto (`.claude/`).
- Snapshot lógico del estado de Plex relevante antes de cada lote aplicado.

**No se copiará nunca la colección multimedia completa como "backup"** sin calcular antes la
capacidad necesaria y pedir permiso explícito — regla directa del encargo, y coherente con el
incidente ya documentado en `infra/backup-video-studio.sh` de AlpardiOS (fuga real de ~63GB a
Drive por una lista de exclusión mal hecha, corregida el 2026-09-07) — este proyecto usará el
mismo patrón de lista de INCLUSIÓN explícita, no de exclusión, cuando llegue el momento.

## Verificación de una copia (regla no negociable)

Una copia no cuenta como verificada hasta que se restaura en una ruta temporal, se abre, y se
valida su hash o integridad lógica — nunca basta con que el archivo de backup exista.
