---
name: plex-plan
description: Genera un plan de renombrado real (solo movie por ahora) y lo guarda como JSON. Nunca toca ningún archivo -- un plan es un dato inspeccionable, no una acción. Paso previo obligatorio antes de /plex-apply.
argument-hint: "<raiz> --library-id <id> --content-type movie [-o plan.json]"
---

```bash
cd /opt/alpardi-media-manager
./.venv/bin/alpardi-media plan rename "<raiz>" --library-id "<id>" --content-type movie -o "<ruta-plan.json>" --json
```

Guarda siempre el plan con `-o` en una ruta que puedas volver a nombrar a Alberto -- lo necesitarás
literalmente para `/plex-apply` después, en una invocación de proceso totalmente separada (el plan
vive en el JSON, no en memoria).

Muestra a Alberto:
- Cuántas operaciones propone y cuántos elementos se "saltaron" por no poder interpretar su nombre
  (nunca se inventa un título/año que el propio nombre no dijera ya).
- Cualquier conflicto detectado (`destination_exists`, `case_collision`, `invalid_chars`,
  `reserved_name`, `path_too_long`, `unicode_collision`) -- un plan con conflictos NO es seguro de
  aplicar, dilo explícitamente.
- La ruta donde se guardó el plan.
- **La frase de autorización exacta que hará falta para aplicarlo** (el propio JSON del plan trae
  `plan_id` y el número de operaciones -- la frase tiene el formato literal `AUTORIZO APLICAR PLAN
  <plan_id> SOBRE <n> ELEMENTOS`). Enséñasela a Alberto tal cual, pero la decisión de escribirla
  para autorizar de verdad es siempre suya, nunca la des por hecha ni la repitas tú como si fuera
  su autorización.

Esta skill nunca aplica el plan. Si Alberto decide seguir adelante, el siguiente paso es que ÉL
invoque `/plex-apply` -- esa skill no se puede invocar automáticamente por diseño.
