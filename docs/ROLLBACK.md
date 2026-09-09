# ROLLBACK.md

## Revertir el scaffold (Fase 2) por completo

Nada de esto ha tocado `/opt/video-studio`, el NAS, ni ninguna biblioteca real de Plex — es
seguro borrarlo sin ningún otro efecto:

```bash
rm -rf /opt/alpardi-media-manager
```

El repositorio remoto (`github.com/albertopardo21690/alpardi-media-manager`) queda intacto salvo
que Alberto lo borre él mismo desde GitHub.

## Revertir un commit concreto del scaffold

```bash
cd /opt/alpardi-media-manager
git log --oneline          # localizar el commit
git revert <hash>          # revierte con un commit nuevo, no reescribe historia
git push
```

## Revertir una transacción real sobre medios (motor transaccional, todavía no implementado)

Cuando exista el motor transaccional (`transactions/`), cada plan aplicado generará un journal
con el `transaction_id` correspondiente. El comando previsto:

```bash
alpardi-media rollback --transaction <id>
```

revertirá operación por operación en orden inverso, verificando hashes antes de dar la reversión
por buena. **Esto todavía no existe** — se documenta aquí el contrato esperado para que, cuando se
implemente, el comportamiento real coincida con lo prometido en este documento (no al revés).
