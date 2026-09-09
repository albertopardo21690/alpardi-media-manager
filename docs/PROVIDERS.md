# PROVIDERS.md — matriz de capacidades por proveedor

Se rellena una fila real por proveedor **cuando su adaptador exista de verdad y su `healthcheck`
haya pasado** — no antes. Un proveedor solo se marca `ready` si cumple las 8 condiciones del
encargo (términos/atribución registrados, credenciales no aparecen en salida, healthcheck +
búsqueda controlada funcionan, rate limiter y caché activos, capacidades declaradas = capacidades
reales, errores no se confunden con "sin resultados", una prueba demuestra que desactivarlo
impide el tráfico, consentimiento del usuario para los datos salientes relevantes).

| Proveedor | Estado | Adaptador | Capacidades implementadas | Autenticación | Licencia/atribución | Límites reales verificados | Última comprobación |
|---|---|---|---|---|---|---|---|
| TMDb | not_implemented | — | — | Bearer token (confirmado, `docs/SOURCES.md`) | — | — | 2026-09-09 (solo auth) |
| Plex Media Server | not_implemented | — | — | Token ya existente, reutilizado | — | — | — |
| TheTVDB v4 | not_implemented | — | — | — | — | — | — |
| TVmaze | not_implemented | — | — | — | — | — | — |
| Fanart.tv | not_implemented | — | — | — | — | — | — |
| OpenSubtitles | not_implemented | — | — | — | — | — | — |
| MusicBrainz + Cover Art Archive | not_implemented | — | — | — | — | — | — |
| AniList / AniDB / Trakt / Wikidata / TheSportsDB / OMDb | out_of_scope | — | — | — | — | — | No están en el perfil B elegido — no se implementan salvo que Alberto lo pida |

No hay ningún proveedor `ready` todavía. No inventar filas ni estados que no se hayan verificado
de verdad — actualizar esta tabla como parte del propio commit que añade cada adaptador.
