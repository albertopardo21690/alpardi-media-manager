---
name: plex-apply
description: Aplica un plan ya generado sobre archivos multimedia REALES -- exige la frase de autorización exacta letra por letra. Invocable SOLO por Alberto escribiendo /plex-apply él mismo, nunca por el modelo automáticamente.
disable-model-invocation: true
argument-hint: "--plan plan.json --root <raiz> --library-id <id> --content-type movie --authorize \"AUTORIZO APLICAR PLAN ... SOBRE N ELEMENTOS\""
---

**Esta es una de las dos únicas skills de todo el proyecto que mutan archivos reales.** Sigue esta
secuencia sin saltarte ningún paso:

1. Si no tienes ya el contenido del plan a la vista en esta conversación, muéstraselo a Alberto
   antes de aplicar nada (`cat` el JSON o vuelve a generar la vista previa) -- nunca apliques un
   plan que él no ha visto de verdad en esta conversación.
2. Confirma que la frase de autorización en `$ARGUMENTS` (o la que Alberto acaba de escribir) es
   EXACTAMENTE la que corresponde a ESE plan -- nunca la completes, nunca la infieras, nunca
   reutilices una frase de un plan anterior aunque se parezca. Si Alberto no ha dado la frase
   todavía, pídesela literal -- no continúes sin ella.
3. Ejecuta el comando real, pasando la frase tal cual la escribió Alberto:

```bash
cd /opt/alpardi-media-manager
./.venv/bin/alpardi-media apply --plan "<plan.json>" --root "<raiz>" --library-id "<id>" \
  --content-type movie --authorize "<frase-exacta-de-alberto>" --json
```

4. El propio comando revuelve a comprobar el inventario real en este instante -- si algo cambió
   desde que se generó el plan, lo rechazará como expirado. Eso es correcto, no un bug: no intentes
   "arreglarlo" reintentando con datos viejos, genera un plan nuevo con `/plex-plan` si hace falta.
5. Muestra el resultado real tal cual (`estado`, operaciones completadas/fallidas/omitidas,
   `transaction_id`). Si algo falló a mitad, dilo con claridad -- el motor ya deja el journal en
   un estado consistente y revertible, pero la decisión de revertir (`/plex-rollback`) es de
   Alberto, no la tomes tú por iniciativa propia salvo que te lo pida explícitamente.

Nunca construyas ni sugieras una frase de autorización "de ejemplo" que Alberto pudiera copiar sin
pensarlo -- la frase la escribe él, con la intención real de autorizar ESE plan concreto.
