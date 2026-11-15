#!/usr/bin/env bash
# Aviso tras cada ejecucion del vigilante de video del NAS. Solo avisa si hay ficheros NUEVOS o MODIFICADOS
# (no en la linea base, ni por duplicados, ni si no hay novedades) -> una alerta rara y util, no ruido diario.
# Usa el unico canal de alertas del sistema de recuperacion (/opt/claude-recovery/scripts/alert.sh).
set -euo pipefail
ESTADO="${WATCH_STATE_DIR:-/opt/alpardi-media-manager/data/watch}"
ALERT="${WATCH_ALERT_CMD:-/opt/claude-recovery/scripts/alert.sh}"
MSG="$(python3 -I - "$ESTADO/ultimo.json" <<'PY'
import json, sys
try:
    d = json.load(open(sys.argv[1], encoding="utf-8"))
except (OSError, ValueError):
    sys.exit(0)
if d.get("linea_base"):
    sys.exit(0)
n, m = d.get("nuevos", []), d.get("modificados", [])
if not n and not m:
    sys.exit(0)
partes = []
if n:
    partes.append(f"{len(n)} nuevo{'s' if len(n) != 1 else ''}")
if m:
    partes.append(f"{len(m)} modificado{'s' if len(m) != 1 else ''}")
ej = [x if len(x) <= 90 else x[:87] + "..." for x in (n + m)[:5]]
extra = f"\n... y {len(n) + len(m) - 5} más" if len(n) + len(m) > 5 else ""
print("Vigilante de vídeo del NAS: " + " y ".join(partes) + ".\n- " + "\n- ".join(ej) + extra + "\nInforme: /opt/alpardi-media-manager/data/watch/ultimo.md")
PY
)"
[ -n "$MSG" ] && "$ALERT" "$MSG"
exit 0
