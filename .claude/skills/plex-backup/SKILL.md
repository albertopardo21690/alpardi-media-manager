---
name: plex-backup
description: Crea o verifica una copia de seguridad de plans/journals/reports/config reales de este proyecto -- NUNCA de la colección multimedia. Verificar siempre extrae de verdad, nunca confía en que el fichero exista sin más.
argument-hint: "create [-o backups/] | verify <archivo.tar.gz>"
---

Esta skill solo respalda datos OPERATIVOS del propio proyecto (planes, journals, informes,
`config/*.yaml` real) -- nunca la colección multimedia de Alberto (ver `docs/BACKUP_RESTORE.md`).
Un backup con 0 archivos es un resultado válido y esperado mientras no se haya aplicado ningún
plan real todavía -- no lo trates como un error.

**Crear:**
```bash
cd /opt/alpardi-media-manager
./.venv/bin/alpardi-media backup create --root . -o backups --json
```

**Verificar (regla no negociable de `docs/BACKUP_RESTORE.md`: nunca basta con que el fichero
exista)** -- hazlo siempre después de crear un backup que vaya a importar de verdad:
```bash
./.venv/bin/alpardi-media backup verify "<ruta-al-.tar.gz>" --json
```

Muestra a Alberto cuántos archivos y bytes se incluyeron, el sha256, y el resultado real de la
verificación. Si `backup verify` falla, dilo con claridad -- no repitas "backup creado
correctamente" si la verificación no lo ha confirmado de verdad.
