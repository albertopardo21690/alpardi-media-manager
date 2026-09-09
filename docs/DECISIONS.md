# DECISIONS.md — registro de decisiones (Fase 0/1)

Fecha: 2026-09-09. Decisiones tomadas por Alberto durante la Fase 0/1, con la evidencia que las
respalda. No se relitigan sin que él lo pida explícitamente.

| # | Decisión | Elegido | Motivo/evidencia |
|---|---|---|---|
| 1 | Alcance inicial | Diseño para las 25 bibliotecas reales de Plex | Con el matiz obligatorio del propio encargo: la **ejecución** real (Fase 5) empieza igualmente con un lote piloto pequeño, no con las 25 de golpe |
| 2 | Estrategia de metadatos Plex | B — agente híbrido personalizado (NFO primero, Plex como complemento) | Requiere validación previa en una biblioteca de prueba antes de aplicarse a cualquier biblioteca real (regla no negociable del encargo) — pendiente de esa prueba |
| 3 | Idioma de títulos de archivo | Español | Coincide con la configuración real ya usada en la mayoría de bibliotecas (auditoría Plex del 4 de septiembre) |
| 4 | Idioma/país de metadatos | es-ES / ES | Confirmado por Alberto, coincide con el valor por defecto del propio encargo |
| 5 | Perfil de proveedores | B — Completo (TMDb + MusicBrainz/CAA + TVmaze + TheTVDB + Fanart.tv + OpenSubtitles) | Ninguno tiene credenciales todavía (verificado: no hay claves en `/root/.config/alpardios/`) — todos quedan `enabled: false` hasta que Alberto cree cada cuenta |
| 6 | Idiomas audio/subtítulos preferidos | Español, luego inglés | — |
| 7 | Tratamiento de ediciones/versiones | Nunca fusionar automáticamente | Evita que una edición real (director's cut, etc.) se trate como "misma película, mejor calidad" sin confirmación |
| 8 | Grado de automatización | Nunca sin aprobación explícita del usuario | Coincide con el motor de planes/transacciones exigido por el encargo (ninguna mutación sin `AUTORIZO APLICAR PLAN ...`) |
| 9 | Consentimientos de datos salientes | Sí a: moviehash a OpenSubtitles, descarga de imágenes, descarga de subtítulos. No preguntado/no aplica: sync de estado visto (Trakt no está en el perfil B) | — |
| 10 | Política de cuarentena | Mover a carpeta de cuarentena, nunca borrar | Regla explícita del encargo |
| 11 | Lote piloto (Fase 5) | 5-10 elementos de una biblioteca pequeña | Aún sin elegir la biblioteca concreta — se decide al llegar a la Fase 5 |
| 12 | Dónde corre el gestor | VPS (`/opt/alpardi-media-manager`), SQLite 100% local ahí; acceso al NAS por SSH/SFTP, nunca montaje SMB | El encargo prefiere por defecto correr "cerca de los datos" (NAS), pero el NAS tiene ahora mismo `sudo` roto (desde 2026-09-04) y un disco fallando de verdad (evidencia real en `dmesg`, ver auditoría Fase 0) — SQLite local en el VPS respeta igualmente la regla de fondo ("nunca SQLite sobre red compartida") sin depender de una máquina inestable |
| 13 | Python | 3.14.4 | Única versión realmente disponible en Ubuntu 26.04 sin añadir fuentes de paquetes nuevas (verificado: sin pyenv/uv, apt solo ofrece 3.14) |

## Contexto que sigue condicionando todo lo demás

- **Disco 1 del NAS activamente fallando** (RAID0, sin redundancia) — hay una copia de emergencia
  en marcha de otra sesión (verificada en Fase 0). Ninguna operación de escritura real sobre el
  NAS hasta que Alberto confirme que el disco se ha sustituido.
- **6 ficheros sin confirmar en `/opt/alpardi-os`** de la sesión de ASPACE (PROJ-010) — no se tocan
  desde este proyecto.
- Ya existe `/volume1/Docker/plex-setup/` en el NAS (proyecto de auditoría/backup/healthcheck de
  Plex de una sesión anterior) — complementario a este, no se duplica.
