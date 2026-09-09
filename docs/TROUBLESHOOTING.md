# TROUBLESHOOTING.md

Se rellena con problemas REALES encontrados según avanza el proyecto — nunca problemas
hipotéticos inventados de antemano.

## `doctor`/tests de integración reportan el NAS inalcanzable por SSH (confirmado real, intermitente)

Causa real conocida: el disco 1 del NAS Alpardimedia está fallando activamente (RAID0, sin
redundancia — ver la memoria de sesión `project_alpardios_nas_raid0_disk_failure`), y esto se
manifiesta como una degradación intermitente y progresiva de SSH (visto en vivo el 2026-09-09:
13s → 26s → 40s → timeout total, o directamente "Connection closed"), mientras el `ping` por
Tailscale sigue respondiendo (a veces con latencia anormalmente alta, ~1.4s vía relay en vez de
conexión directa). No es un bug del propio `check_nas_ssh_reachable` — comprobar a mano antes de
asumir lo contrario:

```bash
ping -c 2 100.75.202.28
ssh -o BatchMode=yes -o ConnectTimeout=5 NASAlpardimedia echo ok
```

Si ambos fallan o tardan de forma anómala, es el disco degradándose, no este proyecto. El test de
integración correspondiente (`test_nas_real_es_alcanzable_por_ssh`) está para detectar justo esto
— un fallo aislado ahí no bloquea el resto del trabajo, se reintenta más tarde.

## `check_nas_ssh_reachable` colgado indefinidamente (corregido, Fase 3)

`subprocess.run(["ssh", ...])` sin `stdin=subprocess.DEVNULL` hereda el stdin del proceso Python
y puede quedarse esperando una entrada interactiva que nunca llega, aunque un `ssh` manual tarde
menos de 1 segundo. Corregido con `stdin=subprocess.DEVNULL` + `-o BatchMode=yes`. Si vuelve a
verse un timeout sospechosamente exacto al límite configurado con un `ssh` manual instantáneo,
comprobar que esta combinación de flags sigue presente en `diagnostics/checks.py`.

## Un `ratingKey` de Plex que no existe devuelve HTML, no una lista JSON vacía (confirmado real)

`GET /library/metadata/<ratingKey>` para un id inexistente responde **HTTP 404 con cuerpo HTML**,
no un `MediaContainer` vacío como cabría asumir de la documentación. `plex/client.py` ya lo
traduce a un `ValueError` claro — si se añade una llamada nueva a la API de Plex, no asumir que
"no encontrado" siempre es una lista vacía sin comprobarlo primero contra el servidor real.
