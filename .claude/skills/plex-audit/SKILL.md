---
name: plex-audit
description: Auditoría de solo lectura del entorno real -- entorno, Plex, proveedores, y opcionalmente una biblioteca concreta. Combina varios comandos reales de solo lectura en un único informe. Nunca modifica nada.
argument-hint: "[raiz-de-biblioteca --library-id <id> --content-type <tipo>]"
---

Consolida varios comandos REALES de solo lectura en un único informe -- nunca inventes ningún
dato, y si un paso falla o no aplica (p.ej. no se ha dado ninguna raíz de biblioteca), dilo
explícitamente en el informe en vez de omitirlo en silencio.

```bash
cd /opt/alpardi-media-manager
./.venv/bin/alpardi-media doctor --json
./.venv/bin/alpardi-media plex inspect --json
./.venv/bin/alpardi-media providers status --json
# Si Alberto dio una raíz de biblioteca concreta en $ARGUMENTS:
./.venv/bin/alpardi-media inventory scan "<raiz>" --library-id "<id>" --content-type "<tipo>" --json
```

Estructura el informe cubriendo, con datos reales de los comandos anteriores (nunca supuestos):

1. **Entorno**: SO, versión de Python, binarios externos disponibles.
2. **Conectividad real**: Plex alcanzable (URL, código HTTP), NAS alcanzable por SSH.
3. **Bibliotecas de Plex**: cuántas hay, tipo de cada una, agente configurado.
4. **Proveedores**: cuáles están habilitados/deshabilitados y si tienen `credential_ref` (nunca
   secretos reales).
5. **Biblioteca inspeccionada** (si se dio una raíz): total de elementos, resumen por extensión.
6. **Riesgos u observaciones conocidas**: p.ej. degradación del NAS (`docs/TROUBLESHOOTING.md`),
   proveedores sin credenciales, contenido no interpretable en el escaneo.
7. **Qué NO se ha comprobado en esta pasada** (si algo se omitió por no tener datos suficientes).
8. **Decisiones pendientes de Alberto** relevantes para seguir (p.ej. activar un proveedor, elegir
   biblioteca piloto).
9. **Próximo paso recomendado** (normalmente `/plex-inventory` o `/plex-plan` sobre una biblioteca
   concreta que Alberto elija).

Termina siempre el informe, textualmente, con esta frase exacta:

> No he modificado todavía el sistema ni los archivos multimedia.

Y después detente a esperar la respuesta de Alberto -- esta skill nunca continúa por su cuenta
hacia `/plex-plan` ni ninguna otra acción sin que él lo pida explícitamente.
