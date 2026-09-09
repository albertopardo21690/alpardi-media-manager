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
