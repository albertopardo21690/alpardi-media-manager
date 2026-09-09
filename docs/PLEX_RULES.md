# PLEX_RULES.md — reglas de nomenclatura y organización, con fuente oficial

Cada regla cita la fuente verificada en `docs/SOURCES.md`. Nada de este documento se aplica a un
archivo real sin pasar por un plan autorizado (`planning/` + `transactions/`) — esto es
documentación de referencia para ese planificador, no un script que se ejecuta solo.

## Servidor real de Alberto (verificado, no supuesto)

Plex Media Server **1.43.3.10828**, ADM 4.3.3.RWC1, Plex Pass activo, Plex Home activo, 25
bibliotecas (auditoría Fase 0, 2026-09-09). Cualquier regla con un mínimo de versión (p.ej.
`{edition-...}` desde v1.28.1) está cumplida en este servidor — confirmado, no asumido.

## Películas

Fuente: [Naming and organizing your Movie files](https://support.plex.tv/articles/naming-and-organizing-your-movie-media-files/) (verificado 2026-09-09 vía búsqueda — `support.plex.tv` devuelve 403 a fetch directo de agentes).

```text
Movies/
  Título (Año) {tmdb-ID}/
    Título (Año) {tmdb-ID}.ext
```

- Una película por carpeta. Año de estreno confirmado (no inferido de la fecha del archivo).
- `{tmdb-123}` o `{imdb-tt1234567}` solo cuando el ID está confirmado — nunca inventado.
- `{edition-Nombre}` para un montaje realmente distinto. **Disponible desde Plex Media Server
  v1.28.1** — el servidor real de Alberto lo soporta, confirmado.
- Varias resoluciones/códecs de la MISMA edición son **versiones**, no ediciones — se agrupan en
  la misma carpeta con sufijo técnico tras el título, sin tocar los identificadores.

## Series (incluye contenido personal/episódico)

Fuente: [Naming and Organizing Your TV Show Files](https://support.plex.tv/articles/naming-and-organizing-your-tv-show-files/) (verificado 2026-09-09 vía búsqueda).

```text
TV Shows/
  Serie (Año) {tmdb-ID}/
    Season 01/
      Serie (Año) - s01e01 - Título del episodio.ext
```

- `Season` literal, **incluso en contenido en español** — confirmado en la fuente oficial.
- Especiales: `Season 00` (alias `Specials`).
- Multi-episodio: `sXXeYY-eZZ`.
- Orden de episodios fijado explícitamente antes de renumerar (TMDb/TVDB emitido, TVDB DVD/
  absoluto) — nunca se asume que el número de un proveedor coincide con el orden ya usado en Plex.
- Colecciones personales con esquema propio (p.ej. Ceremonias Olímpicas, año como temporada) **se
  conservan tal cual** — nunca se les impone este patrón estándar sin que Alberto lo pida.

## NFO, arte, subtítulos, extras, música, formatos problemáticos

Reglas completas todavía por trasladar aquí desde el encargo original (§"Políticas exactas de
organización para Plex") — este documento se irá ampliando módulo a módulo, a medida que se
implemente cada analizador/política real en `parsers/` y `policies/`, no todo de golpe. Ver el
encargo original (`docs/SOURCES.md` lista las URLs pendientes de consultar antes de implementar
cada uno) para el detalle mientras tanto.
