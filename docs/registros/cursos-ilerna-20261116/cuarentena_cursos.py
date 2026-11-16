"""Cuarentena de episodios de Cursos repetidos por el fallo de comillas de la sincronizacion de ILERNA (2026-11-16).
Mueve (renombra, mismo volumen) a Videos/_cuarentena_duplicados_20261116/ la copia SIN prefijo «Mnn » cuando en la misma
carpeta hay otra, CON prefijo, con el MISMO SHA-256 completo. Nada se borra. Uso: --dry | --apply"""
import json, re, shlex, subprocess, sys
from datetime import datetime
H = "NASAlpardimedia"; BASE = "/volume1/home/alpardimedia/Videos"; Q = "_cuarentena_duplicados_20261116"
DIARIO = "/root/nas-dedupe/cuarentena-20261116.jsonl"
MODS = ["M09 Sostenibilidad aplicada al sistema productivo", "M10 Desarrollo web entorno cliente", "M11 Desarrollo web entorno servidor"]
def ssh(cmd, timeout=900):
    r = subprocess.run(["ssh", "-o", "BatchMode=yes", H, cmd], capture_output=True, timeout=timeout)
    return r.returncode, r.stdout.decode("utf-8", "replace").strip()
plan = []
for m in MODS:
    rc, out = ssh(f"cd {shlex.quote(BASE + '/Cursos/' + m)} && find . -maxdepth 1 -type f -name '*.mp4' -exec stat -c '%s|%i|%Y|%n' {{}} +")
    files = [l.split("|", 3) for l in out.splitlines() if l.count("|") >= 3]
    por_tam = {}
    for s, i, y, n in files: por_tam.setdefault(s, []).append((i, y, n[2:] if n.startswith("./") else n))
    for s, g in por_tam.items():
        if len(g) != 2 or int(s) < 1048576: continue
        con = [x for x in g if re.match(r"^M\d\d ", x[2])]; sin = [x for x in g if not re.match(r"^M\d\d ", x[2])]
        if len(con) == 1 and len(sin) == 1 and con[0][0] != sin[0][0]:
            plan.append({"modulo": m, "tam": int(s), "conservar": con[0][2], "apartar": sin[0][2], "inodo": int(sin[0][0]), "mtime": int(sin[0][1])})
print(f"candidatos por prefijo+tamano: {len(plan)}")
ok = []
for p in plan:
    d = shlex.quote(BASE + "/Cursos/" + p["modulo"])
    rc, out = ssh(f"cd {d} && sha256sum -- {shlex.quote(p['conservar'])} {shlex.quote(p['apartar'])} | cut -c1-64")
    h = out.split()
    p["sha"] = h[0] if len(h) == 2 and h[0] == h[1] else None
    print(("IDENTICO " if p["sha"] else "DISTINTO  "), f"{p['tam']/1e6:7.1f} MB | {p['modulo'][:3]} | {p['apartar'][:60]}  <=>  {p['conservar'][:40]}")
    if p["sha"]: ok.append(p)
print(f"verificados idénticos por SHA-256 completo: {len(ok)} de {len(plan)}")
if "--apply" not in sys.argv: sys.exit(0)
if len(ok) != len(plan): print("ABORTO: hay candidatos no idénticos; no se mueve nada"); sys.exit(2)
for p in ok:
    src = BASE + "/Cursos/" + p["modulo"] + "/" + p["apartar"]; dst_dir = BASE + "/" + Q + "/Cursos/" + p["modulo"]
    cmd = (f'[ "$(stat -c %i:%s:%Y {shlex.quote(src)})" = "{p["inodo"]}:{p["tam"]}:{p["mtime"]}" ] || {{ echo PRECOND; exit 11; }}\n'
           f'mkdir -p {shlex.quote(dst_dir)} && [ ! -e {shlex.quote(dst_dir + "/" + p["apartar"])} ] || {{ echo DESTINO_EXISTE; exit 12; }}\n'
           f'mv {shlex.quote(src)} {shlex.quote(dst_dir + "/" + p["apartar"])} && [ -f {shlex.quote(dst_dir + "/" + p["apartar"])} ] && [ ! -e {shlex.quote(src)} ] && echo OK')
    rc, out = ssh(cmd)
    res = "OK" if rc == 0 and out.endswith("OK") else (out.splitlines() or [f"rc={rc}"])[-1]
    with open(DIARIO, "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"t": datetime.now().isoformat(timespec="seconds"), "accion": "cuarentena", "resultado": res, **p}, ensure_ascii=False) + "\n")
    print(res, "|", p["apartar"][:70])
