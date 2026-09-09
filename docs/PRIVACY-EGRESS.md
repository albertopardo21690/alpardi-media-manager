# PRIVACY-EGRESS.md — qué sale, hacia dónde, y con qué autorización

Tabla exacta del encargo, con el estado real de consentimiento de Alberto (`docs/DECISIONS.md`
#9). Ningún proveedor está activo todavía (`enabled: false` en `config/providers.example.yaml`),
así que **hoy no sale ningún dato hacia ninguno** — esta tabla es el contrato para cuando se
activen, no una descripción de tráfico ya ocurriendo.

| Dato saliente | Motivo | Proveedores posibles | ¿Obligatorio? | Consentimiento de Alberto |
|---|---|---|---|---|
| Título, año y tipo | Buscar candidatos | TMDb, TheTVDB, TVmaze, OMDb, AniList | Solo si no existe ID fiable | Implícito al activar perfil B |
| ID externo | Cruce exacto | TMDb, TVmaze, OpenSubtitles | Preferido cuando existe | Implícito al activar perfil B |
| Idioma y región | Localización/certificación | Fuentes de metadatos | Sí para resultados localizados | Implícito (es-ES/ES ya confirmado) |
| Hash OpenSubtitles (`moviehash`) y tamaño | Buscar edición concreta | OpenSubtitles | No, opt-in | **Sí, dado explícitamente** |
| Nombre técnico de release | Evaluar sincronía de subtítulos | OpenSubtitles | No, puede revelar procedencia | No preguntado todavía — tratar como no autorizado hasta confirmar |
| MBID/ISRC/Disc ID | Identificar música | MusicBrainz/CAA | Según caso | Implícito al activar perfil B (si hay bibliotecas de música) |
| Historial/progreso (estado visto) | Sincronizar cuenta | Trakt | Nunca por defecto | No aplica — Trakt no está en el perfil B elegido |
| Descarga de imágenes/arte | Completar bibliotecas | TMDb, Fanart.tv, TheTVDB | No, opt-in | **Sí, dado explícitamente** |
| Descarga de subtítulos | Completar bibliotecas | OpenSubtitles | No, opt-in | **Sí, dado explícitamente** |

## Reglas de minimización, siempre

- Nunca se envía la ruta completa de un archivo. Si un proveedor necesita un nombre, se deriva y
  se muestra una versión saneada antes de enviarla.
- Un `moviehash` no contiene el vídeo, pero es una huella del archivo — se trata como dato
  sensible pese al consentimiento ya dado; se sigue mostrando qué se va a enviar antes de cada uso
  real, no solo la primera vez.
- Contenido familiar/privado (vídeos personales, fotos) **nunca** se envía a ningún proveedor por
  defecto — ver tabla "Política por tipo de biblioteca y campo" del encargo original, fila
  "Vídeo/foto familiar".
