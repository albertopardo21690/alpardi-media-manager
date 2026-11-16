"""Pruebas de la lógica pura de enlazar.py (plan, alcance, scripts remotos). La parte SSH se prueba aparte, con ficheros de prueba en el NAS."""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest

from alpardi_media_manager.watch import enlazar as e
from alpardi_media_manager.watch.vigilante import Fichero

GB = 10**9


def f(ruta: str, inodo: int, tam: int = 2 * GB, mtime: int = 1_700_000_000) -> Fichero:
    return Fichero(inodo=inodo, tam=tam, mtime=mtime, ruta=ruta)


def cache_para(*pares: tuple[Fichero, str]) -> dict[str, str]:
    return {f"completa|{x.ruta}|{x.tam}|{x.mtime}": h for x, h in pares}


A = f("Ciclos/Tom Hanks/peliculas/Forrest Gump (1994).mp4", 1)
B = f("Películas/Forrest Gump (1994)/Forrest Gump (1994).mp4", 2)


def test_solo_entran_grupos_con_sha256_completo_identico() -> None:
    assert e.grupos_confirmados([A, B], {}) == []                                   # sin huella completa: nada
    assert e.grupos_confirmados([A, B], cache_para((A, "h1"), (B, "h2"))) == []     # huellas distintas: nada
    assert len(e.grupos_confirmados([A, B], cache_para((A, "h"), (B, "h")))) == 1


def test_plan_ciclos_peliculas_conserva_el_nombrado_plex_y_enlaza_el_otro() -> None:
    plan = e.construir_plan([A, B], cache_para((A, "h"), (B, "h")))
    assert len(plan) == 1
    # ambos siguen el nombrado «Título (Año)»; gana la ruta más corta (Ciclos/…/X.mp4 es más larga que Películas/X/X.mp4 aquí no):
    assert {plan[0].origen, plan[0].destino} == {A.ruta, B.ruta}
    assert plan[0].tam == 2 * GB and plan[0].inodo_origen != plan[0].inodo_destino


def test_misma_biblioteca_queda_fuera_del_alcance() -> None:
    a = f("Cursos/M10/a.mp4", 1)
    b = f("Cursos/M11/a.mp4", 2)
    assert e.construir_plan([a, b], cache_para((a, "h"), (b, "h"))) == []
    # «El difunto es un vivo»: dos copias en Ciclos + una en Películas -> hay dos en la misma raíz -> fuera
    c1 = f("Ciclos/P/El difunto es un vivo (1956).mp4", 3)
    c2 = f("Ciclos/P/El difunto es un vivo (1941).mp4", 4)
    c3 = f("Películas/El difunto es un vivo (1941)/El difunto es un vivo (1941).mp4", 5)
    assert e.construir_plan([c1, c2, c3], cache_para((c1, "h"), (c2, "h"), (c3, "h"))) == []


def test_bibliotecas_no_autorizadas_quedan_fuera() -> None:
    a = f("Series/S/a.mkv", 1)
    b = f("Películas/P/a.mkv", 2)
    assert e.construir_plan([a, b], cache_para((a, "h"), (b, "h"))) == []


def test_vhs_olimpiadas_enlaza_al_inodo_que_ya_tiene_mas_nombres() -> None:
    vhs = [f(f"{d}/Barcelona 92/Ceremonia.mp4", 10, 13 * GB) for d in
           ("VHS Digitalizados - Catalogo", "VHS Digitalizados - Peliculas", "VHS Digitalizados - Prueba")]
    oly = f("Olimpiadas-Series/Barcelona 92/Season 1/Barcelona 92 S01E01 - Ceremonia.mp4", 11, 13 * GB)
    plan = e.construir_plan([*vhs, oly], cache_para((vhs[0], "h"), (oly, "h")))
    assert [o.destino for o in plan] == [oly.ruta] and plan[0].inodo_origen == 10   # Olimpiadas pasa a enlace al inodo de las 3 rutas VHS


def test_plan_ordena_primero_los_pequenos_y_la_huella_detecta_cambios(tmp_path: Path) -> None:
    peq_a, peq_b = f("Ciclos/x/p.mp4", 1, 100 * 2**20), f("Películas/p/p.mp4", 2, 100 * 2**20)
    plan = e.construir_plan([A, B, peq_a, peq_b], cache_para((A, "h"), (B, "h"), (peq_a, "k"), (peq_b, "k")))
    assert plan[0].tam < plan[1].tam
    ruta = tmp_path / "plan.json"
    ruta.write_text(json.dumps({"huella": e.huella_plan(plan), "operaciones": [o.__dict__ for o in plan]}), encoding="utf-8")
    assert e.cargar_plan(ruta)[1] == e.huella_plan(plan)
    d = json.loads(ruta.read_text(encoding="utf-8"))
    d["operaciones"][0]["destino"] = "Otro/fichero.mp4"
    ruta.write_text(json.dumps(d), encoding="utf-8")
    with pytest.raises(SystemExit):
        e.cargar_plan(ruta)


def op(destino: str, origen: str) -> e.Operacion:
    return e.Operacion(destino, origen, 123, 1700000000, 1700000001, 11, 22)


def test_scripts_remotos_no_borran_ni_mueven_nada_fuera_de_su_temporal() -> None:
    s = e.script_enlazar(op("Ciclos/x/a b.mp4", "Películas/a b/a b.mp4"))
    borrados = re.findall(r"rm -f ('[^']*')", s)
    assert borrados and s.count("rm -f") == len(borrados)                       # todo `rm` lleva un argumento entre comillas...
    assert all(b.endswith(e.SUFIJO_TMP + "'") for b in borrados)                 # ...y es siempre el temporal propio
    assert "mv -f './Ciclos/x/a b.mp4.alp-enlace-tmp' './Ciclos/x/a b.mp4'" in s            # renombrado atómico encima del destino
    assert "ln './Películas/a b/a b.mp4' './Ciclos/x/a b.mp4.alp-enlace-tmp'" in s
    assert "PRECOND_ORIGEN" in s and "PRECOND_DESTINO" in s


def test_rutas_con_comillas_y_guiones_se_escapan_bien() -> None:
    s = e.script_enlazar(op("Ciclos/-raro/it's.mp4", "Películas/it's/it's.mp4"))
    assert "./Ciclos/-raro/it" in s and "'\"'\"'" in s    # la comilla simple se cierra y reabre de forma segura


def test_script_sintaxis_valida_en_sh() -> None:
    for s in (e.script_enlazar(op("a b/c.mp4", "d/e.mp4")), e.script_revertir(op("a b/c.mp4", "d/e.mp4")),
              e.script_comprobar(op("x.mp4", "y.mp4"))):
        r = subprocess.run(["sh", "-n"], input=s.encode(), capture_output=True, check=False)
        assert r.returncode == 0, r.stderr.decode()


def test_aplicar_exige_la_frase_exacta(tmp_path: Path) -> None:
    plan = e.construir_plan([A, B], cache_para((A, "h"), (B, "h")))
    p = tmp_path / "plan.json"
    p.write_text(json.dumps({"huella": e.huella_plan(plan), "operaciones": [o.__dict__ for o in plan]}), encoding="utf-8")
    rc = e.main(["aplicar", "--plan", str(p), "--diario", str(tmp_path / "d.jsonl"), "--autorizo", "si, adelante"])
    assert rc == 3 and not (tmp_path / "d.jsonl").exists()


def test_misma_raiz_solo_si_se_autoriza_explicitamente_y_excluir_la_saca() -> None:
    a = f("Sagas Cinematograficas/Clases grabadas/a.mp4", 1, 2 * GB)
    b = f("Sagas Cinematograficas/Master/b.mp4", 2, 2 * GB)
    cache = cache_para((a, "h"), (b, "h"))
    assert e.construir_plan([a, b], cache) == []                                                    # por defecto: fuera
    assert len(e.construir_plan([a, b], cache, frozenset({"Sagas Cinematograficas"}))) == 1         # autorizada
    assert e.construir_plan([a, b], cache, frozenset({"Cursos"})) == []                              # otra raíz: sigue fuera
    assert e.construir_plan([a, b], cache, frozenset({"Sagas Cinematograficas"}),
                            ("Sagas Cinematograficas/Master/",)) == []                               # excluida por prefijo
