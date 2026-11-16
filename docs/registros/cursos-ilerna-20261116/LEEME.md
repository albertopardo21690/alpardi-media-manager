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
