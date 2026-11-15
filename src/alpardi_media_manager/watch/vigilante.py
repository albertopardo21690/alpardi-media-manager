"""Vigilante de la biblioteca de vídeo del NAS -- SOLO LECTURA.

Qué hace (en cada ejecución):
  1. Toma una instantánea de los vídeos del NAS por SSH (`find` + `stat`; el NAS usa BusyBox, sin
     `-printf`), saltándose las carpetas privadas y las de entrada de proyectos.
  2. La compara con la instantánea anterior: ficheros nuevos, desaparecidos y modificados.
  3. Clasifica los nuevos (¿siguen el nombrado Plex de `parsers/filename.py`? ¿están en la bandeja
     de entrada?).
  4. Detecta duplicados de forma barata y segura: mismo tamaño + distinto inodo (los enlaces duros
     ya son duplicados resueltos y no cuentan), y huella SHA-256 de los primeros y últimos 4 MiB. La
     confirmación con SHA-256 del fichero entero es opcional y con presupuesto de GB.
  5. Escribe un informe Markdown/JSON en el directorio de estado del VPS.

Lo que NO hace, a propósito (invariantes de `CLAUDE.md`): no mueve, copia, renombra ni borra
NADA en el NAS, no toca Plex y no ejecuta ningún plan. Proponer una cuarentena o un renombrado
exige después un plan inmutable y la frase de autorización de Alberto (`docs/ROLLBACK.md`).
Las lecturas pesadas del NAS van con `nice -n 19 ionice -c3`.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path, PurePosixPath
from zoneinfo import ZoneInfo

from alpardi_media_manager.parsers.filename import (
    parsear_nombre_episodio,
    parsear_nombre_pelicula,
)

SSH_HOST = "NASAlpardimedia"
BASE = "/volume1/home/alpardimedia/Videos"
# Carpetas privadas/familiares o de uso interno: ni se listan ni se leen.
EXCLUIDAS = ("Zona privada", "Videos mensuales MJ", "Dedicatorias", "_admin", "_toolkit", "_incoming_*")
BANDEJA_ENTRADA = "_General_Inbox"
EXTENSIONES = ("mkv", "mp4", "avi", "m4v", "mov", "ts", "mpg", "wmv")
ESTABLE_S = 900          # un fichero modificado hace menos de 15 min puede estar copiándose: se espera
MIN_DUPLICADO = 50 * 2**20
BLOQUE = 4 * 2**20
DIR_ESTADO = Path("/opt/alpardi-media-manager/data/watch")
MADRID = ZoneInfo("Europe/Madrid")   # las horas siempre en hora de Madrid
_NICE = "nice -n 19 ionice -c3"


@dataclass(frozen=True)
class Fichero:
    inodo: int
    tam: int
    mtime: int
    ruta: str   # relativa a BASE, sin "./"

    @property
    def nombre_sin_ext(self) -> str:
        return PurePosixPath(self.ruta).stem

    @property
    def carpeta_raiz(self) -> str:
        partes = PurePosixPath(self.ruta).parts
        return partes[0] if len(partes) > 1 else "(raíz)"


@dataclass
class Diferencias:
    nuevos: list[Fichero] = field(default_factory=list)
    desaparecidos: list[str] = field(default_factory=list)
    modificados: list[Fichero] = field(default_factory=list)


@dataclass
class GrupoDuplicado:
    tam: int
    huella: str
    confirmado: bool                      # True = SHA-256 del fichero entero
    copias: list[list[Fichero]]           # una entrada por inodo distinto (enlaces duros agrupados)
    conservar: int = 0                    # índice sugerido dentro de `copias`
    motivo: str = ""

    @property
    def recuperable(self) -> int:
        return self.tam * (len(self.copias) - 1)

    @property
    def entre_bibliotecas(self) -> bool:
        """True si cada copia vive en una carpeta raíz distinta (p. ej. `Ciclos/` frente a `Películas/`):
        casi siempre es una copia intencionada para otra biblioteca de Plex, no un duplicado a borrar."""
        raices = [c[0].carpeta_raiz for c in self.copias]
        return len(set(raices)) == len(raices)


# ---------------------------------------------------------------------------- instantánea (NAS)
def comando_instantanea() -> str:
    podas = " -o ".join(f"-path './{e}'" for e in EXCLUIDAS)
    nombres = " -o ".join(f"-iname '*.{e}'" for e in EXTENSIONES)
    return (
        f"cd '{BASE}' && {_NICE} find . -mindepth 1 \\( {podas} \\) -prune -o "
        f"-type f \\( {nombres} \\) -exec stat -c '%i|%s|%Y|%n' {{}} +"
    )


def parsear_instantanea(texto: str) -> list[Fichero]:
    """Una línea por fichero: `inodo|tamaño|mtime|./ruta`. Las líneas mal formadas se ignoran."""
    salida: list[Fichero] = []
    for linea in texto.splitlines():
        p = linea.split("|", 3)
        if len(p) != 4 or not (p[0].isdigit() and p[1].isdigit() and p[2].isdigit()):
            continue
        ruta = p[3].removeprefix("./")
        salida.append(Fichero(int(p[0]), int(p[1]), int(p[2]), ruta))
    return salida


def _ssh(host: str, comando: str, entrada: bytes | None = None, timeout: int = 900) -> str:
    r = subprocess.run(
        ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15", host, comando],
        input=entrada, capture_output=True, timeout=timeout, check=False,
    )
    if r.returncode != 0:
        raise RuntimeError(f"ssh {host} falló ({r.returncode}): {r.stderr.decode(errors='replace')[:300]}")
    return r.stdout.decode("utf-8", errors="surrogateescape")


def tomar_instantanea(host: str) -> list[Fichero]:
    return parsear_instantanea(_ssh(host, comando_instantanea()))


# ---------------------------------------------------------------------------- lógica pura
def separar_estables(
    ficheros: list[Fichero], ahora: float, umbral: int = ESTABLE_S
) -> tuple[list[Fichero], list[Fichero]]:
    """(estables, en_copia). Un fichero tocado hace menos de `umbral` s se deja para la próxima vez."""
    estables = [f for f in ficheros if ahora - f.mtime >= umbral]
    en_copia = [f for f in ficheros if ahora - f.mtime < umbral]
    return estables, en_copia


def comparar(previa: dict[str, Fichero], actual: list[Fichero]) -> Diferencias:
    d = Diferencias()
    vistas = set()
    for f in actual:
        vistas.add(f.ruta)
        antes = previa.get(f.ruta)
        if antes is None:
            d.nuevos.append(f)
        elif antes.tam != f.tam:
            d.modificados.append(f)
    d.desaparecidos = sorted(r for r in previa if r not in vistas)
    return d


def candidatos_duplicados(ficheros: list[Fichero], minimo: int = MIN_DUPLICADO) -> list[list[Fichero]]:
    """Grupos de >=2 ficheros del mismo tamaño con >=2 inodos distintos (los enlaces duros no cuentan)."""
    por_tam: dict[int, list[Fichero]] = defaultdict(list)
    for f in ficheros:
        if f.tam >= minimo:
            por_tam[f.tam].append(f)
    return [g for g in por_tam.values() if len({f.inodo for f in g}) > 1]


def enlaces_duros_resueltos(ficheros: list[Fichero], minimo: int = MIN_DUPLICADO) -> int:
    """Grupos de mismo tamaño cuyos ficheros son todos el mismo inodo (duplicados ya resueltos)."""
    por_tam: dict[int, list[Fichero]] = defaultdict(list)
    for f in ficheros:
        if f.tam >= minimo:
            por_tam[f.tam].append(f)
    return sum(1 for g in por_tam.values() if len(g) > 1 and len({f.inodo for f in g}) == 1)


def sigue_nombrado_plex(nombre_sin_ext: str) -> bool:
    return (parsear_nombre_pelicula(nombre_sin_ext) is not None
            or parsear_nombre_episodio(nombre_sin_ext) is not None)


def sugerir_conservar(copias: list[list[Fichero]]) -> tuple[int, str]:
    """Sugerencia (siempre a validar por Alberto): nombre conforme a Plex > ruta más corta > más antiguo."""
    def clave(i: int) -> tuple[int, int, int]:
        f = min(copias[i], key=lambda x: (len(x.ruta), x.ruta))
        return (0 if sigue_nombrado_plex(f.nombre_sin_ext) else 1, len(f.ruta), f.mtime)
    mejor = min(range(len(copias)), key=clave)
    f = min(copias[mejor], key=lambda x: (len(x.ruta), x.ruta))
    if sigue_nombrado_plex(f.nombre_sin_ext) and any(
        not sigue_nombrado_plex(min(c, key=lambda x: len(x.ruta)).nombre_sin_ext)
        for i, c in enumerate(copias) if i != mejor
    ):
        return mejor, "su nombre sigue el nombrado Plex y el de las otras copias no"
    return mejor, "ruta más corta / más antigua (sin diferencia de nombrado)"


def agrupar_por_huella(
    candidatos: list[list[Fichero]], huellas: dict[str, str], confirmado: bool
) -> list[GrupoDuplicado]:
    """Une, dentro de cada grupo de tamaño, los ficheros con la misma huella (por inodo)."""
    grupos: list[GrupoDuplicado] = []
    for g in candidatos:
        por_huella: dict[str, dict[int, list[Fichero]]] = defaultdict(lambda: defaultdict(list))
        for f in g:
            h = huellas.get(f.ruta)
            if h:
                por_huella[h][f.inodo].append(f)
        for h, por_inodo in por_huella.items():
            if len(por_inodo) > 1:
                copias = [sorted(v, key=lambda x: x.ruta) for v in por_inodo.values()]
                gd = GrupoDuplicado(tam=g[0].tam, huella=h, confirmado=confirmado, copias=copias)
                gd.conservar, gd.motivo = sugerir_conservar(copias)
                grupos.append(gd)
    return sorted(grupos, key=lambda x: -x.recuperable)


def clasificar_nuevo(f: Fichero) -> str:
    if f.carpeta_raiz == BANDEJA_ENTRADA:
        return "en la bandeja de entrada: pendiente de clasificar"
    if sigue_nombrado_plex(f.nombre_sin_ext):
        return "nombre conforme a Plex"
    return "nombre sin el patrón Plex: revisar (posible plan de renombrado)"


# ---------------------------------------------------------------------------- huellas remotas
def huellas_remotas(host: str, rutas: list[str], completo: bool = False) -> dict[str, str]:
    """SHA-256 calculado EN el NAS (nice/ionice). `completo` = fichero entero; si no, 4 MiB inicio + 4 MiB final."""
    if not rutas:
        return {}
    lectura = ('sha256sum "$1"' if completo
               else f'{{ head -c {BLOQUE} "$1"; tail -c {BLOQUE} "$1"; }} | sha256sum')
    remoto = (f"cd '{BASE}' && {_NICE} xargs -0 -n1 sh -c "
              f"'printf \"%s\\t\" \"$1\"; {lectura} | cut -d\" \" -f1' _")
    entrada = b"\0".join(r.encode("utf-8", errors="surrogateescape") for r in rutas)
    salida = _ssh(host, remoto, entrada=entrada, timeout=3600)
    pedidas = set(rutas)
    huellas: dict[str, str] = {}
    for linea in salida.splitlines():
        ruta, _, h = linea.partition("\t")
        if ruta in pedidas and len(h) == 64:
            huellas[ruta] = h
    return huellas


# ---------------------------------------------------------------------------- estado en disco
def _cargar_json(p: Path, defecto: object) -> object:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return defecto


def _guardar_json(p: Path, datos: object) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(datos, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(p)


def cargar_instantanea(p: Path) -> dict[str, Fichero] | None:
    crudo = _cargar_json(p, None)
    if not isinstance(crudo, dict):
        return None
    return {r: Fichero(int(v[0]), int(v[1]), int(v[2]), r) for r, v in crudo.items()}


def guardar_instantanea(p: Path, ficheros: list[Fichero]) -> None:
    _guardar_json(p, {f.ruta: [f.inodo, f.tam, f.mtime] for f in ficheros})


# ---------------------------------------------------------------------------- informe
def _gb(n: int) -> str:
    return f"{n / 1e9:,.1f} GB".translate(str.maketrans(",.", ".,"))   # 1,234.5 -> 1.234,5


def generar_informe(
    *, ahora: datetime, total: int, tam_total: int, linea_base: bool, dif: Diferencias,
    en_copia: list[Fichero], grupos: list[GrupoDuplicado], duros: int,
) -> str:
    L: list[str] = [f"# Vigilante de vídeo del NAS — {ahora:%Y-%m-%d %H:%M}", ""]
    L.append(f"Solo lectura: no se ha movido, renombrado ni borrado nada. Vídeos vigilados: **{total}** "
             f"({_gb(tam_total)}); carpetas privadas excluidas.")
    L.append("")
    L.append("## Ficheros nuevos")
    if linea_base:
        L.append("Primera ejecución: se ha guardado la **línea base**. Los nuevos se listarán desde la próxima.")
    elif not dif.nuevos:
        L.append("Ninguno desde la última ejecución.")
    else:
        for f in sorted(dif.nuevos, key=lambda x: x.ruta):
            L.append(f"- `{f.ruta}` ({_gb(f.tam)}) — {clasificar_nuevo(f)}")
    if dif.modificados:
        L += ["", "## Modificados (cambió el tamaño)"] + [f"- `{f.ruta}`" for f in dif.modificados]
    if dif.desaparecidos:
        L += ["", "## Desaparecidos desde la última ejecución"] + [f"- `{r}`" for r in dif.desaparecidos[:50]]
        if len(dif.desaparecidos) > 50:
            L.append(f"- … y {len(dif.desaparecidos) - 50} más")
    if en_copia:
        L += ["", f"## En copia ahora mismo ({len(en_copia)})",
              "Modificados hace menos de 15 minutos; se evalúan en la próxima ejecución."]
        L += [f"- `{f.ruta}`" for f in en_copia[:20]]
    L += ["", "## Posibles duplicados"]
    mismas = [g for g in grupos if not g.entre_bibliotecas]
    entre = [g for g in grupos if g.entre_bibliotecas]
    L.append(f"Ya resueltos con enlaces duros (no cuentan): {duros} grupos. Pendientes: {len(grupos)} grupos.")
    L.append(f"- **Dentro de la misma biblioteca** (candidatos reales a cuarentena): {len(mismas)} grupos, "
             f"{_gb(sum(g.recuperable for g in mismas))}.")
    L.append(f"- **Entre bibliotecas distintas** (`Ciclos`, `VHS…`, `Películas`…; casi siempre copias "
             f"intencionadas): {len(entre)} grupos, {_gb(sum(g.recuperable for g in entre))}. Para ahorrar "
             "ese espacio sin quitar nada de ninguna biblioteca la vía es un **enlace duro**, no la cuarentena.")
    for titulo, lote in (("Dentro de la misma biblioteca", mismas), ("Entre bibliotecas distintas", entre)):
        if lote:
            L += ["", f"## {titulo}"]
        for g in lote:
            nivel = "confirmado (SHA-256 completo)" if g.confirmado else "muy probable (tamaño + 4 MiB inicio/final)"
            L += ["", f"### {_gb(g.tam)} — {nivel}"]
            for i, copia in enumerate(g.copias):
                marca = " ← sugerido como original" if i == g.conservar else ""
                enlazadas = " (enlazadas entre sí: mismo fichero)" if len(copia) > 1 else ""
                L.append(f"- {' / '.join(f'`{f.ruta}`' for f in copia)}{enlazadas}{marca}")
            L.append(f"  - Motivo de la sugerencia: {g.motivo}. A validar por Alberto.")
    L += ["", "## Qué falta para actuar"]
    L.append("- Mover duplicados a cuarentena, enlazarlos o renombrar requiere un **plan inmutable** y la frase "
             "exacta `AUTORIZO APLICAR PLAN <id> SOBRE <n> ELEMENTOS`. Hoy existe `plan rename`; "
             "`plan quarantine` y `plan hardlink` todavía no.")
    L.append("- Refresco de Plex: pendiente (falta el token de Plex en este VPS).")
    return "\n".join(L) + "\n"


# ---------------------------------------------------------------------------- ejecución
def ejecutar(
    *, host: str, estado: Path, confirmar_gb: float, ahora: float | None = None,
    instantanea: list[Fichero] | None = None,
) -> Path:
    t = time.time() if ahora is None else ahora
    todos = instantanea if instantanea is not None else tomar_instantanea(host)
    estables, en_copia = separar_estables(todos, t)
    previa = cargar_instantanea(estado / "instantanea.json")
    # primera ejecución = línea base: todo existía ya, no se declara «nuevo»
    dif = comparar(previa, estables) if previa is not None else Diferencias()

    cand = candidatos_duplicados(estables)
    cache_raw = _cargar_json(estado / "huellas.json", {})
    cache: dict[str, str] = cache_raw if isinstance(cache_raw, dict) else {}

    def clave(f: Fichero, modo: str) -> str:
        return f"{modo}|{f.ruta}|{f.tam}|{f.mtime}"

    pendientes = [f for g in cand for f in g if clave(f, "rapida") not in cache]
    if instantanea is None and pendientes:
        for ruta, h in huellas_remotas(host, [f.ruta for f in pendientes]).items():
            f = next(x for x in pendientes if x.ruta == ruta)
            cache[clave(f, "rapida")] = h
    rapidas = {f.ruta: cache[clave(f, "rapida")] for g in cand for f in g if clave(f, "rapida") in cache}
    grupos = agrupar_por_huella(cand, rapidas, confirmado=False)

    if confirmar_gb > 0 and instantanea is None:
        presupuesto = int(confirmar_gb * 1e9)
        for g in grupos:
            if g.recuperable == 0 or g.tam * sum(len(c) > 0 for c in g.copias) > presupuesto:
                continue
            rutas = [c[0] for c in g.copias]
            falta = [f for f in rutas if clave(f, "completa") not in cache]
            if falta:
                presupuesto -= g.tam * len(falta)
                for ruta, h in huellas_remotas(host, [f.ruta for f in falta], completo=True).items():
                    f = next(x for x in falta if x.ruta == ruta)
                    cache[clave(f, "completa")] = h
                _guardar_json(estado / "huellas.json", cache)   # por grupo: si se corta, no se pierde lo ya calculado
        completas = {c[0].ruta: cache[clave(c[0], "completa")] for g in grupos for c in g.copias
                     if clave(c[0], "completa") in cache}
        for g in grupos:
            hs = {completas.get(c[0].ruta) for c in g.copias}
            if None not in hs and len(hs) == 1:
                g.confirmado = True
    _guardar_json(estado / "huellas.json", cache)

    ahora_dt = datetime.fromtimestamp(t, MADRID)
    informe = generar_informe(
        ahora=ahora_dt, total=len(estables), tam_total=sum(f.tam for f in estables),
        linea_base=previa is None, dif=dif, en_copia=en_copia, grupos=grupos,
        duros=enlaces_duros_resueltos(estables),
    )
    carpeta = estado / "informes"
    carpeta.mkdir(parents=True, exist_ok=True)
    destino = carpeta / f"{ahora_dt:%Y-%m-%d_%H%M}.md"
    destino.write_text(informe, encoding="utf-8")
    (estado / "ultimo.md").write_text(informe, encoding="utf-8")
    _guardar_json(estado / "ultimo.json", {
        "generado": ahora_dt.isoformat(timespec="seconds"), "vigilados": len(estables),
        "linea_base": previa is None, "nuevos": [f.ruta for f in dif.nuevos],
        "desaparecidos": len(dif.desaparecidos), "modificados": [f.ruta for f in dif.modificados],
        "grupos_duplicados": len(grupos), "recuperable_bytes": sum(g.recuperable for g in grupos),
    })
    guardar_instantanea(estado / "instantanea.json", estables)   # al final: si algo falla, no se pierde la comparación
    return destino


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="alpardi-media-watch", description=__doc__.split("\n\n")[0])
    ap.add_argument("--host", default=SSH_HOST)
    ap.add_argument("--estado", type=Path, default=DIR_ESTADO)
    ap.add_argument("--confirmar-gb", type=float, default=0.0,
                    help="Presupuesto de GB para confirmar duplicados con SHA-256 completo (0 = no confirmar)")
    a = ap.parse_args(argv)
    try:
        destino = ejecutar(host=a.host, estado=a.estado, confirmar_gb=a.confirmar_gb)
    except (RuntimeError, subprocess.TimeoutExpired) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    print(f"Informe: {destino}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
