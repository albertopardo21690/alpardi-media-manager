"""Enlaces duros entre duplicados YA CONFIRMADOS del NAS (SHA-256 del fichero entero), por SSH.

IMPORTANTE -- por qué vive aquí y no en `transactions/engine.py`: el gestor aún no puede actuar sobre el NAS (no
hay backend SFTP). Alberto decidió el 2026-11-15, con los datos delante, hacerlo así, por SSH y con diario. Esta
herramienta NO sustituye al motor transaccional: solo hace UNA operación, de bajo riesgo y reversible, y lleva sus
propias garantías:

  * Alcance cerrado: solo grupos cuyas copias están en carpetas raíz distintas Y dentro de los pares autorizados
    (`PARES_AUTORIZADOS`). Nada de «misma biblioteca».
  * Plan inmutable en un fichero JSON con su huella; `--aplicar` exige ese fichero y el alcance exacto.
  * Antes de cada par se comprueban por SSH tamaño, mtime e inodo de ambos ficheros (el contenido es idéntico por el
    SHA-256 ya calculado; si algo cambió desde entonces, ese par se salta).
  * Nunca hay un instante sin fichero: se crea un enlace temporal junto al destino y se RENOMBRA encima (atómico).
  * No borra datos: la copia que desaparece tiene exactamente el mismo contenido que la que queda.
  * Diario JSONL de cada operación y `--revertir`, que vuelve a dejar copias independientes (copia + renombrado).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shlex
import sys
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from alpardi_media_manager.watch import vigilante as v

# pares de carpetas raíz entre las que Alberto autorizó enlazar (2026-11-15): cada grupo debe estar COMPLETO dentro de un par
PARES_AUTORIZADOS = (
    frozenset({"Ciclos", "Películas"}),
    frozenset({"Olimpiadas-Series", "VHS Digitalizados - Catalogo", "VHS Digitalizados - Peliculas",
               "VHS Digitalizados - Prueba", "VHS Digitalizados"}),
)
SUFIJO_TMP = ".alp-enlace-tmp"
SUFIJO_REV = ".alp-revertir-tmp"
DIARIO_DEFECTO = Path("/root/nas-dedupe/enlaces-20261115.jsonl")


@dataclass(frozen=True)
class Operacion:
    destino: str        # ruta (relativa a BASE) que pasará a ser un enlace al origen
    origen: str         # ruta (relativa a BASE) que se conserva
    tam: int
    mtime_destino: int
    mtime_origen: int
    inodo_destino: int
    inodo_origen: int


# ---------------------------------------------------------------------------- plan (lógica pura)
def grupos_confirmados(
    ficheros: list[v.Fichero], cache: dict[str, str]
) -> list[list[list[v.Fichero]]]:
    """Grupos (lista de copias; cada copia = lista de rutas del mismo inodo) con SHA-256 COMPLETO idéntico."""
    salida: list[list[list[v.Fichero]]] = []
    for g in v.candidatos_duplicados(ficheros):
        por_inodo: dict[int, list[v.Fichero]] = defaultdict(list)
        for f in g:
            por_inodo[f.inodo].append(f)
        por_hash: dict[str, list[list[v.Fichero]]] = defaultdict(list)
        for paths in por_inodo.values():
            h = next((cache[k] for f in paths if (k := f"completa|{f.ruta}|{f.tam}|{f.mtime}") in cache), None)
            if h:
                por_hash[h].append(sorted(paths, key=lambda x: x.ruta))
        salida += [copias for copias in por_hash.values() if len(copias) > 1]
    return salida


def en_alcance(copias: list[list[v.Fichero]]) -> bool:
    raices = [c[0].carpeta_raiz for c in copias]
    if len(set(raices)) != len(raices):      # dos copias en la misma carpeta raíz = «misma biblioteca»: fuera
        return False
    return any(set(raices) <= par for par in PARES_AUTORIZADOS)


def elegir_origen(copias: list[list[v.Fichero]]) -> int:
    """Se conserva el inodo que ya tiene más nombres; a igualdad, el que sigue el nombrado Plex; a igualdad, la ruta más corta."""
    def clave(i: int) -> tuple[int, int, int]:
        f = min(copias[i], key=lambda x: (len(x.ruta), x.ruta))
        return (-len(copias[i]), 0 if v.sigue_nombrado_plex(f.nombre_sin_ext) else 1, len(f.ruta))
    return min(range(len(copias)), key=clave)


def construir_plan(ficheros: list[v.Fichero], cache: dict[str, str]) -> list[Operacion]:
    plan: list[Operacion] = []
    for copias in grupos_confirmados(ficheros, cache):
        if not en_alcance(copias):
            continue
        i = elegir_origen(copias)
        o = min(copias[i], key=lambda x: (len(x.ruta), x.ruta))
        for j, paths in enumerate(copias):
            if j == i:
                continue
            for f in paths:
                plan.append(Operacion(f.ruta, o.ruta, f.tam, f.mtime, o.mtime, f.inodo, o.inodo))
    return sorted(plan, key=lambda op: (op.tam, op.destino))   # los pequeños primero: el primer lote es el menos arriesgado


def huella_plan(plan: list[Operacion]) -> str:
    return hashlib.sha256(json.dumps([asdict(o) for o in plan], sort_keys=True).encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------- scripts remotos
def _q(ruta: str) -> str:
    return shlex.quote("./" + ruta)       # «./» evita que un nombre que empiece por «-» se tome por una opción


def script_comprobar(op: Operacion) -> str:
    return (f'[ "$(stat -c "%s|%Y|%i" {_q(op.origen)} 2>/dev/null)" = "{op.tam}|{op.mtime_origen}|{op.inodo_origen}" ] || '
            f'{{ echo PRECOND_ORIGEN; exit 11; }}\n'
            f'[ "$(stat -c "%s|%Y|%i" {_q(op.destino)} 2>/dev/null)" = "{op.tam}|{op.mtime_destino}|{op.inodo_destino}" ] || '
            f'{{ echo PRECOND_DESTINO; exit 12; }}\n')


def script_enlazar(op: Operacion) -> str:
    tmp = shlex.quote("./" + op.destino + SUFIJO_TMP)
    return (script_comprobar(op)
            + f'[ ! -e {tmp} ] || {{ echo TMP_EXISTE; exit 13; }}\n'
            + f'ln {_q(op.origen)} {tmp} || {{ echo FALLA_LN; exit 14; }}\n'
            + f'[ "$(stat -c %i {tmp})" = "{op.inodo_origen}" ] || {{ rm -f {tmp}; echo INODO_DISTINTO; exit 15; }}\n'
            + f'mv -f {tmp} {_q(op.destino)} || {{ rm -f {tmp}; echo FALLA_MV; exit 16; }}\n'
            + f'[ "$(stat -c "%i|%s" {_q(op.destino)})" = "{op.inodo_origen}|{op.tam}" ] || {{ echo VERIF_FINAL; exit 17; }}\n'
            + 'echo OK\n')


def script_revertir(op: Operacion) -> str:
    """Deja `destino` como fichero independiente otra vez (copia + renombrado atómico)."""
    tmp = shlex.quote("./" + op.destino + SUFIJO_REV)
    return (f'[ "$(stat -c %i {_q(op.destino)} 2>/dev/null)" = "{op.inodo_origen}" ] || {{ echo NO_ESTA_ENLAZADO; exit 21; }}\n'
            + f'[ ! -e {tmp} ] || {{ echo TMP_EXISTE; exit 22; }}\n'
            + f'cp -p {_q(op.origen)} {tmp} || {{ rm -f {tmp}; echo FALLA_CP; exit 23; }}\n'
            + f'[ "$(stat -c %s {tmp})" = "{op.tam}" ] || {{ rm -f {tmp}; echo TAM_DISTINTO; exit 24; }}\n'
            + f'mv -f {tmp} {_q(op.destino)} || {{ rm -f {tmp}; echo FALLA_MV; exit 25; }}\n'
            + 'echo OK\n')


def _ssh_sh(host: str, base: str, cuerpo: str, timeout: int = 900) -> tuple[int, str]:
    import subprocess
    r = subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15", host, "sh", "-s"],
                       input=f"cd {shlex.quote(base)} || exit 10\n{cuerpo}".encode("utf-8", "surrogateescape"),
                       capture_output=True, timeout=timeout, check=False)
    return r.returncode, r.stdout.decode("utf-8", "replace").strip()


# ---------------------------------------------------------------------------- órdenes
def cargar_plan(p: Path) -> tuple[list[Operacion], str]:
    d = json.loads(p.read_text(encoding="utf-8"))
    plan = [Operacion(**o) for o in d["operaciones"]]
    if huella_plan(plan) != d["huella"]:
        raise SystemExit("ABORTO: el plan fue modificado después de generarse (la huella no coincide)")
    return plan, d["huella"]


def cmd_generar(a: argparse.Namespace) -> int:
    snap = v.cargar_instantanea(a.estado / "instantanea.json")
    cache_raw = json.loads((a.estado / "huellas.json").read_text(encoding="utf-8"))
    if snap is None:
        print("ERROR: no hay instantánea; ejecuta antes el vigilante", file=sys.stderr)
        return 1
    plan = construir_plan(list(snap.values()), cache_raw)
    out = {"generado": datetime.now(v.MADRID).isoformat(timespec="seconds"), "huella": huella_plan(plan),
           "operaciones": [asdict(o) for o in plan]}
    a.salida.parent.mkdir(parents=True, exist_ok=True)
    a.salida.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    ahorro = sum({o.inodo_destino: o.tam for o in plan}.values())    # cada inodo que desaparece libera su tamaño una vez
    print(f"Plan {out['huella']}: {len(plan)} operaciones sobre {len({o.origen for o in plan})} grupos; "
          f"ahorro aprox. {ahorro / 1e9:.1f} GB -> {a.salida}")
    return 0


def cmd_comprobar(a: argparse.Namespace) -> int:
    """Ensayo: SOLO lee (stat) y dice cuántas operaciones cumplirían las condiciones previas ahora mismo."""
    plan, h = cargar_plan(a.plan)
    ok = mal = 0
    for op in plan:
        rc, salida = _ssh_sh(a.host, a.base, script_comprobar(op) + "echo OK\n")
        if rc == 0:
            ok += 1
        else:
            mal += 1
            print(f"NO CUMPLE ({salida}): {op.destino}")
    print(f"Ensayo del plan {h}: {ok} cumplen, {mal} no.")
    return 0 if mal == 0 else 2


def _anotar(diario: Path, **campos: object) -> None:
    diario.parent.mkdir(parents=True, exist_ok=True)
    with diario.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"t": datetime.now(v.MADRID).isoformat(timespec="seconds"), **campos}, ensure_ascii=False) + "\n")


def cmd_aplicar(a: argparse.Namespace) -> int:
    plan, h = cargar_plan(a.plan)
    if a.autorizo != f"AUTORIZO ENLACES PLAN {h} SOBRE {len(plan)} OPERACIONES":
        print(f"ABORTO: falta la frase exacta: AUTORIZO ENLACES PLAN {h} SOBRE {len(plan)} OPERACIONES", file=sys.stderr)
        return 3
    hechas = {(j["destino"]) for j in _leer_diario(a.diario) if j.get("resultado") == "OK" and j.get("accion") == "enlazar"}
    pendientes = [op for op in plan if op.destino not in hechas][: a.max]
    ok = fallos = 0
    for op in pendientes:
        rc, salida = _ssh_sh(a.host, a.base, script_enlazar(op))
        res = "OK" if rc == 0 and salida.endswith("OK") else (salida.splitlines() or [f"rc={rc}"])[-1]
        _anotar(a.diario, accion="enlazar", plan=h, resultado=res, **asdict(op))
        if res == "OK":
            ok += 1
        else:
            fallos += 1
            print(f"SALTADO ({res}): {op.destino}")
            if fallos >= 3:
                print("ABORTO: 3 fallos seguidos; se para para revisar", file=sys.stderr)
                break
    print(f"Aplicadas {ok}, falladas/saltadas {fallos}; pendientes del plan: {len(plan) - len(hechas) - ok}. Diario: {a.diario}")
    return 0 if fallos == 0 else 4


def _leer_diario(p: Path) -> list[dict[str, object]]:
    try:
        return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]
    except OSError:
        return []


def cmd_revertir(a: argparse.Namespace) -> int:
    hechas = [j for j in _leer_diario(a.diario) if j.get("accion") == "enlazar" and j.get("resultado") == "OK"]
    ya = {j["destino"] for j in _leer_diario(a.diario) if j.get("accion") == "revertir" and j.get("resultado") == "OK"}
    ok = 0
    for j in hechas[::-1][: a.max]:
        if j["destino"] in ya:
            continue
        op = Operacion(str(j["destino"]), str(j["origen"]), int(str(j["tam"])), int(str(j["mtime_destino"])),
                       int(str(j["mtime_origen"])), int(str(j["inodo_destino"])), int(str(j["inodo_origen"])))
        rc, salida = _ssh_sh(a.host, a.base, script_revertir(op))
        res = "OK" if rc == 0 and salida.endswith("OK") else (salida.splitlines() or [f"rc={rc}"])[-1]
        _anotar(a.diario, accion="revertir", resultado=res, destino=op.destino)
        ok += res == "OK"
        if res != "OK":
            print(f"NO REVERTIDO ({res}): {op.destino}")
    print(f"Revertidas {ok}.")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="alpardi-media-enlazar", description=__doc__.split("\n\n")[0])
    ap.add_argument("--host", default=v.SSH_HOST)
    ap.add_argument("--base", default=v.BASE)
    sub = ap.add_subparsers(dest="orden", required=True)
    g = sub.add_parser("generar", help="Genera el plan inmutable a partir de lo confirmado por el vigilante")
    g.add_argument("--estado", type=Path, default=v.DIR_ESTADO)
    g.add_argument("--salida", type=Path, default=Path("/root/nas-dedupe/plan-enlaces-20261115.json"))
    for nombre, ayuda in (("comprobar", "Ensayo de solo lectura"), ("aplicar", "Aplica el plan (exige la frase exacta)"),
                          ("revertir", "Vuelve a dejar copias independientes")):
        s = sub.add_parser(nombre, help=ayuda)
        s.add_argument("--plan", type=Path, default=Path("/root/nas-dedupe/plan-enlaces-20261115.json"))
        s.add_argument("--diario", type=Path, default=DIARIO_DEFECTO)
        if nombre != "comprobar":
            s.add_argument("--max", type=int, default=5, help="Operaciones por ejecución (lotes pequeños)")
        if nombre == "aplicar":
            s.add_argument("--autorizo", default="", help="Frase exacta de autorización")
    a = ap.parse_args(argv)
    return {"generar": cmd_generar, "comprobar": cmd_comprobar, "aplicar": cmd_aplicar, "revertir": cmd_revertir}[a.orden](a)


if __name__ == "__main__":
    raise SystemExit(main())
