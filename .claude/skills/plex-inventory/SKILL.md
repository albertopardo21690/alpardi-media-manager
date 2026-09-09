---
name: plex-inventory
description: Escanea una raíz de biblioteca real y lista el inventario de archivos encontrados (rutas, tamaños, huellas). Solo lectura -- nunca escribe nada, ni siquiera una caché.
argument-hint: "<raiz> --library-id <id> --content-type <movie|tv_show|tv_episode|...>"
---

Necesitas de Alberto (o ya conocidos de un `/plex-audit` reciente): la ruta raíz real a escanear,
un `--library-id` (puede ser cualquier identificador estable que Alberto elija, p.ej. el `key` real
de esa biblioteca en Plex si ya lo tienes de `/plex-doctor`/inspección de Plex), y el
`--content-type` (ver `domain/models.py` para los valores válidos -- `movie` es el único con
generación de nombres real conectada hoy, ver `docs/ARCHITECTURE.md`).

```bash
cd /opt/alpardi-media-manager
./.venv/bin/alpardi-media inventory scan "<raiz>" --library-id "<id>" --content-type "<tipo>" --json
```

Nunca inventes una ruta si Alberto no la ha dado -- pregúntasela si no la tienes. Presenta el
total de elementos encontrados y, si son pocos, la lista; si son muchos, un resumen (por
extensión, por tamaño total) en vez de volcarlo todo. Esta skill nunca modifica nada -- si Alberto
quiere proponer un renombrado real a partir de este inventario, la siguiente skill es
`/plex-plan`, nunca hagas el paso tú mismo con otra herramienta.
