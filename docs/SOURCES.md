# SOURCES.md — fuentes oficiales consultadas

Registro obligatorio (encargo §"Fuentes de verdad"): URL, fecha de consulta, qué se verificó, y
regla concreta aplicada en el diseño. Las fuentes marcadas "pendiente" no bloquean el scaffold
inicial porque no hay todavía contenido real de ese tipo (anime, deportes) o proveedor activo
(perfil elegido: B, ver `docs/DECISIONS.md`) — se consultarán antes de activar cada proveedor
concreto, no antes.

## Plex — reglas de nomenclatura

| Fuente | Fecha | Qué se verificó | Regla aplicada |
|---|---|---|---|
| [Naming and organizing your Movie files](https://support.plex.tv/articles/naming-and-organizing-your-movie-media-files/) | 2026-09-09 (vía búsqueda, `support.plex.tv` bloquea fetch directo de agentes — ya conocido de auditorías anteriores de este mismo proyecto) | Patrón `/Movies/MovieName (year)/MovieName (year) – Split_Name.ext`; `{edition-...}` disponible desde Plex Media Server **v1.28.1+** | Servidor real de Alberto es 1.43.3.10828 (verificado en Fase 0) — **por encima del mínimo, ediciones soportadas de verdad**, no una suposición |
| [Naming and Organizing Your TV Show Files](https://support.plex.tv/articles/naming-and-organizing-your-tv-show-files/) | 2026-09-09 (vía búsqueda) | `Season NN` literal (incluso en español); especiales en `Season 00`/`Specials`; multi-episodio `sXXeYY-eZZ`; recomienda año en carpeta y archivo | Confirma el patrón ya usado por el propio superprompt — sin contradicción |
| Multiple Editions (películas y series) | **Pendiente de confirmar el límite exacto de longitud/caracteres de `{edition-...}`** | — | No aplicar ediciones a ninguna biblioteca real hasta confirmarlo con una prueba en biblioteca temporal (regla explícita del encargo) |

## TMDb

| Fuente | Fecha | Qué se verificó | Regla aplicada |
|---|---|---|---|
| [Authentication](https://developer.themoviedb.org/docs/authentication-application) | 2026-09-09 | `Authorization: Bearer <token>` (API Read Access Token) es equivalente en capacidades a `api_key` por query string, sin diferencia funcional | El adaptador TMDb usará **Bearer token**, nunca `api_key` en URL (evita que quede en logs/caché de query string) |

## Claude Code — integración

| Fuente | Fecha | Qué se verificó | Regla aplicada |
|---|---|---|---|
| [Skills](https://code.claude.com/docs/en/skills) | 2026-09-09 | `disable-model-invocation: true` en el frontmatter YAML de `SKILL.md` es el mecanismo real y vigente para que una skill sea invocable solo por el usuario (`/comando`), nunca por el modelo automáticamente; además su descripción ni siquiera se carga en el contexto de Claude | `/plex-apply`, `/plex-rollback` y cualquier skill con efectos llevarán este flag — confirmado, no asumido |

## Pendientes de consulta (no bloquean el scaffold inicial)

- TheTVDB v4, Fanart.tv, OpenSubtitles REST API: se consultarán en el momento de implementar cada
  adaptador (perfil B elegido por Alberto, ninguno activo todavía — `enabled: false` por defecto).
- MusicBrainz/Cover Art Archive: se consultará cuando se implemente el adaptador de música (P0 solo
  si hay bibliotecas de música en el lote piloto).
- AniList/AniDB/Trakt/Wikidata/TheSportsDB/OMDb/IMDb: no se consultan todavía — ninguno forma parte
  del perfil B aprobado ni hay contenido confirmado que los necesite hoy.
- `code.claude.com/docs/en/mcp` y `.../hooks-guide`: se consultarán antes de escribir el servidor
  MCP y los hooks reales (Fase 4), no antes.
- Recursos locales de películas/series, NFO, subtítulos, extras, `.plexignore`, ISO/VIDEO_TS: se
  consultarán cuando se diseñen esos módulos concretos en Fase 3, para no bloquear el scaffold con
  una consulta masiva de 20+ URLs de golpe.
