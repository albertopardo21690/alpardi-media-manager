---
name: plex-doctor
description: Diagnóstico de entorno de AlpardiMedia Manager -- Python, binarios externos (ffprobe/ffmpeg/mediainfo), y si Plex y el NAS son alcanzables de verdad ahora mismo. Solo lectura.
argument-hint: "[--json]"
---

Ejecuta el diagnóstico real de entorno, nunca lo simules ni infieras el resultado.

```bash
cd /opt/alpardi-media-manager
./.venv/bin/alpardi-media doctor $ARGUMENTS
```

Presenta cada comprobación (`python`, `ffprobe`, `ffmpeg`, `mediainfo`, `plex`, `nas_ssh`) con su
estado real. Si `nas_ssh` falla, antes de reportarlo como un problema del propio proyecto, recuerda
que el NAS Alpardimedia tiene un historial real de degradación intermitente por un disco fallando
(ver `docs/TROUBLESHOOTING.md`) -- compara con `ssh NASAlpardimedia echo ok` a mano si hace falta
más contexto, pero reporta el resultado real de `doctor` tal cual, sin suavizarlo.

Esta skill es puramente informativa -- no propone ni ejecuta ningún cambio.
