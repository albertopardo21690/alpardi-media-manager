---
name: plex-providers
description: Qué proveedores de metadatos (TMDb, MusicBrainz, TVmaze...) están habilitados/deshabilitados según config/providers.yaml. Solo lectura, cero tráfico de red, nunca lee el valor de una credencial.
argument-hint: "[--config ruta] [--json]"
---

Ejecuta el comando real, nunca inventes ni recuerdes de una sesión anterior qué proveedores están
activos -- el estado puede haber cambiado.

```bash
cd /opt/alpardi-media-manager
./.venv/bin/alpardi-media providers status $ARGUMENTS
```

Si `config/providers.yaml` todavía no existe, el comando cae automáticamente a la plantilla
`config/providers.example.yaml` y lo dice explícitamente -- si eso ocurre, acláraselo a Alberto:
lo que ve es la plantilla, no una configuración real activa.

Mientras Alberto no haya creado credenciales (ver `docs/DECISIONS.md` #5), lo esperado y correcto
es que TODOS los proveedores aparezcan deshabilitados -- eso no es un error a corregir por tu
cuenta, es una decisión explícita suya. Nunca habilites un proveedor ni crees `config/providers.yaml`
sin que Alberto lo pida de forma explícita.
