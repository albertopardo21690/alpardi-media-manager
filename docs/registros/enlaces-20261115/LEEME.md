# Enlaces duros del NAS, 2026-11-15/16

- `plan-enlaces-20261115.json`: plan inmutable (huella `ff59eacfe18476d9`), 50 operaciones, 180,1 GB. Generado por
  `alpardi_media_manager.watch.enlazar generar` a partir de grupos confirmados con SHA-256 del fichero entero.
- `enlaces-20261115.jsonl`: diario de cada operación (inodos y fechas antes del enlace), 50 × `OK`.
- Autorizado por Alberto el 2026-11-15 para los pares `Ciclos`↔`Películas` y `Olimpiadas-Series`↔`VHS Digitalizados - Catalogo/Prueba`.
- **Revertir** (deja copias independientes por copia + renombrado; necesita espacio libre):
  `cd /opt/alpardi-media-manager && ./.venv/bin/python -m alpardi_media_manager.watch.enlazar revertir --max N`
  (el diario por defecto está en `/root/nas-dedupe/`; para usar este, `--diario docs/registros/enlaces-20261115/enlaces-20261115.jsonl`).
