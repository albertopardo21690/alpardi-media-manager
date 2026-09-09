---
name: plex-search
description: Evalúa el estado de coincidencia LOCAL de cada elemento de una biblioteca (solo movie por ahora) -- sin llamar todavía a ningún proveedor externo, porque ninguno está activo. Solo lectura.
argument-hint: "<raiz> --library-id <id> --content-type movie"
---

Ejecuta el comando real -- este comando SOLO evalúa evidencia local (nombre de archivo parseado,
ID ya presente), nunca consulta TMDb ni ningún otro proveedor porque ninguno está activo todavía
(ver `docs/DECISIONS.md` #5, comprobable con `/plex-providers`).

```bash
cd /opt/alpardi-media-manager
./.venv/bin/alpardi-media match check "<raiz>" --library-id "<id>" --content-type movie --json
```

**Antes de mostrar el resultado, explica siempre por qué casi todo aparece como `needs_review` o
`sin_interpretar`**: con la lista de candidatos de proveedor vacía (porque no hay ninguno activo),
el motor de coincidencias (`matching/engine.py`) nunca puede confirmar una coincidencia por
diseño -- eso es correcto y esperado, no un fallo de esta skill ni del proyecto. Si Alberto quiere
coincidencias reales contra TMDb u otro proveedor, el paso previo real es activarlo (decisión
explícita suya, nunca automática) -- indícaselo, no lo actives tú.

Nunca inventes un título/año/ID que el propio nombre de archivo no contenga ya.
