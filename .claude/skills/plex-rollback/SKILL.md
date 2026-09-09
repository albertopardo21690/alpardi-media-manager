---
name: plex-rollback
description: Revierte una transacción ya aplicada, moviendo los archivos reales de vuelta a su estado anterior. Invocable SOLO por Alberto escribiendo /plex-rollback él mismo, nunca por el modelo automáticamente.
disable-model-invocation: true
argument-hint: "--transaction <id> --root <raiz>"
---

**Esta es la otra de las dos únicas skills de todo el proyecto que mutan archivos reales.**

```bash
cd /opt/alpardi-media-manager
./.venv/bin/alpardi-media rollback --transaction "<transaction_id>" --root "<raiz>" --json
```

Si Alberto no tiene a mano el `transaction_id`, estará en el resultado de la aplicación original
(`/plex-apply` lo muestra) o en el nombre del fichero de journal correspondiente -- pregúntaselo
antes de adivinar uno.

Muestra el resultado real (`completa`, operaciones revertidas/con error). Si la reversión queda
incompleta, dilo con total claridad y sin suavizarlo -- el motor transaccional deja constancia
exacta en el journal de qué se revirtió de verdad y qué no; nunca des una reversión por completa
sin que el propio resultado lo confirme.
