# Cursos de ILERNA: duplicados por el fallo de comillas de la sincronización, 2026-11-16

**Causa:** `C:\Scripts\ilerna-sync\daily-sync.ps1` (PC, tarea `AlpardiOS-IlernaSync`, 21:00) pasaba a `ssh` rutas con espacios con
comillas dobles escapadas; PowerShell 5.1 las pierde, así que listaba/creaba la carpeta corta (`Cursos/M10`) en vez de
`Cursos/M10 Desarrollo web entorno cliente` y subía TODOS los vídeos locales cada noche. El 15-nov: 37 subidos; los nombres
sin prefijo «Mnn » duplicaron 9 episodios y Plex los fundió como «versiones» del mismo episodio.
**Arreglo (PC, autorizado):** comillas simples, regla «ya está si coincide el nombre O el tamaño exacto», salvaguarda si no se
puede listar, `-DryRun`. Original en `daily-sync.ps1.bak-20261116` (en el PC).
**Limpieza (autorizada):**
- `cuarentena-20261116.jsonl`: 9 copias (SHA-256 completo idéntico a la que se queda) movidas por renombrado a
  `Videos/_cuarentena_duplicados_20261116/Cursos/<módulo>/`. Para deshacer: `mv` de vuelta a la misma ruta de `Cursos/<módulo>/`.
- `carpetas-vacias-20261116.log`: 13 carpetas VACÍAS creadas por el mismo fallo, borradas con `rmdir` (solo si vacías).
- Comprobación en Plex: episodios con más de una versión, 9 → 0 (M09 3, M10 14, M11 14 episodios).

## Actualización (16-nov, tarde): destino nuevo del script
Alberto movió M09/M10/M11 de `Videos/Cursos` al archivo oficial de ILERNA
(`Documentos/Estudios/FP/Centros/ILERNA Online/ILERNA FP/Desarrollo de Aplicaciones Web a distancia DAW Online/4 Semestre 1S 2627/<módulo>/`):
videotutorías en `Videotutorías/Season 1` y material suelto en `Recursos`. `daily-sync.ps1` se adaptó: sube ahí (nombre «Mnn … - SnnEnn - …»
→ `Videotutorías/Season 1`; el resto → `Recursos`), NUNCA crea carpetas de módulo (si falta, lo omite y lo anota) y compara por nombre O tamaño
en todo el módulo. Copias en el PC: `daily-sync.ps1.bak-20261116` (original) y `.bak2-20261116` (versión intermedia).
Prueba en seco: 0 de 37 por subir (9 reconocidos por tamaño con otro nombre). Clasificación: 7/7.
Además, 5 enlaces duros más (4 operaciones + la cuarentena de «El difunto es un vivo (1956)»): `plan-enlaces-20261116.json`, `enlaces-20261116.jsonl`.

## Actualización (16-nov, noche)
- Primera ejecución real del `daily-sync.ps1` corregido (21:00:44): «subidos 0 video(s) nuevo(s)». No recreó carpetas en `Cursos`; Plex «ILERNA FP» (sección 35): M09 3, M10 14, M11 14 episodios.
- `push_to_nas.ps1` (reescrito a las 15:55 por otra sesión) tenía TRES defectos: (1) guardado en UTF-8 sin BOM → PowerShell 5.1 lo lee como ANSI y la tilde de
  «Videotutorías» sale como `Ã­` (bytes c3 83 c2 ad en vez de c3 ad), creando carpetas rotas; (2) comillas dobles escapadas en los `mkdir` (carpetas basura sueltas
  en el home del NAS); (3) las mismas comillas en los `ls`, así que el listado de lo ya existente salía vacío. Arreglado (autorizado): comillas simples en las 5 líneas
  `ssh`, y BOM UTF-8. Copia propia `.bak2-20261116` (la `.bak-20261116` es de la otra sesión). Verificado por AST: la tilde del literal vale 237 (í).
- Borradas con `rmdir` 5 carpetas vacías basura (`Sostenibilidad`, `aplicada`, `al`, `sistema`, `productivo` en el home de admin; 3 subcarpetas vacías de `productivo`).
- LECCIÓN: un script .ps1 con acentos debe guardarse CON BOM, o construir los caracteres con `[char]0xNN`. Nunca fiarse de cómo SE VE una tilde en la salida del PC (CP850): comparar bytes.
