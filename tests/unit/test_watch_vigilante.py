"""Pruebas del vigilante de solo lectura: lógica pura (sin SSH) + ejecución completa con instantánea simulada."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from alpardi_media_manager.watch import vigilante as v
from alpardi_media_manager.watch.vigilante import Fichero

MB = 2**20
AHORA = 1_800_000_000.0


def f(ruta: str, tam: int = 100 * MB, inodo: int = 1, mtime: int = 1_700_000_000) -> Fichero:
    return Fichero(inodo=inodo, tam=tam, mtime=mtime, ruta=ruta)


def test_parsear_instantanea_ignora_lineas_malformadas() -> None:
    txt = "10|1000|1700000000|./Series/a b.mkv\nbasura\n11|x|1|./mal.mkv\n12|5|6|./Pelis/x|y.mp4\n"
    r = v.parsear_instantanea(txt)
    assert [x.ruta for x in r] == ["Series/a b.mkv", "Pelis/x|y.mp4"]   # el «|» en el nombre se conserva
    assert r[0].inodo == 10 and r[0].tam == 1000


def test_comando_instantanea_excluye_privadas_y_solo_lee() -> None:
    c = v.comando_instantanea()
    assert "Zona privada" in c and "-prune" in c and "stat -c" in c
    for peligroso in (" rm ", " mv ", " cp ", "-delete", "-exec rm"):
        assert peligroso not in c


def test_separar_estables_deja_en_copia_los_recientes() -> None:
    nuevo = f("A/nuevo.mkv", mtime=int(AHORA) - 60)
    viejo = f("A/viejo.mkv", mtime=int(AHORA) - 7200)
    est, copia = v.separar_estables([nuevo, viejo], AHORA)
    assert est == [viejo] and copia == [nuevo]


def test_comparar_nuevos_modificados_desaparecidos() -> None:
    previa = {"a.mkv": f("a.mkv", tam=1), "b.mkv": f("b.mkv", tam=2), "c.mkv": f("c.mkv", tam=3)}
    actual = [f("a.mkv", tam=1), f("b.mkv", tam=99), f("d.mkv", tam=4)]
    d = v.comparar(previa, actual)
    assert [x.ruta for x in d.nuevos] == ["d.mkv"]
    assert [x.ruta for x in d.modificados] == ["b.mkv"]
    assert d.desaparecidos == ["c.mkv"]


def test_enlaces_duros_no_son_candidatos_a_duplicado() -> None:
    duros = [f("Series/x.mkv", inodo=7), f("Sagas/x.mkv", inodo=7)]   # mismo inodo = ya deduplicado
    reales = [f("Series/y.mkv", tam=300 * MB, inodo=8), f("Otra/y.mkv", tam=300 * MB, inodo=9)]
    assert v.candidatos_duplicados(duros) == []
    assert v.enlaces_duros_resueltos(duros) == 1
    assert len(v.candidatos_duplicados(duros + reales)) == 1


def test_umbral_minimo_de_tamano() -> None:
    chicos = [f("a.mkv", tam=MB, inodo=1), f("b.mkv", tam=MB, inodo=2)]
    assert v.candidatos_duplicados(chicos) == []


def test_agrupar_por_huella_separa_mismo_tamano_distinto_contenido() -> None:
    a, b, c = f("a.mkv", inodo=1), f("b.mkv", inodo=2), f("c.mkv", inodo=3)
    cand = v.candidatos_duplicados([a, b, c])
    grupos = v.agrupar_por_huella(cand, {"a.mkv": "H1", "b.mkv": "H1", "c.mkv": "H2"}, confirmado=False)
    assert len(grupos) == 1 and {x[0].ruta for x in grupos[0].copias} == {"a.mkv", "b.mkv"}
    assert grupos[0].recuperable == 100 * MB and not grupos[0].confirmado


def test_sugerencia_prefiere_nombre_plex() -> None:
    bueno = f("Películas/Blade Runner (1982)/Blade Runner (1982).mkv", inodo=1)
    malo = f("Descargas/br.final.1080p.mkv", inodo=2)
    i, motivo = v.sugerir_conservar([[malo], [bueno]])
    assert i == 1 and "nombrado Plex" in motivo


def test_clasificar_nuevo() -> None:
    assert "bandeja" in v.clasificar_nuevo(f("_General_Inbox/x.mkv"))
    assert "conforme" in v.clasificar_nuevo(f("Películas/Alien (1979)/Alien (1979).mkv"))
    assert "revisar" in v.clasificar_nuevo(f("Series/Show/show.s01e01.720p.mkv"))


def test_ejecutar_linea_base_y_segunda_pasada(tmp_path: Path) -> None:
    viejo = int(AHORA) - 86_400
    base = [f("Series/S/S (2020) - s01e01.mkv", inodo=1, mtime=viejo)]
    v.ejecutar(host="x", estado=tmp_path, confirmar_gb=0, ahora=AHORA, instantanea=base)
    ult = json.loads((tmp_path / "ultimo.json").read_text(encoding="utf-8"))
    assert ult["linea_base"] is True and ult["nuevos"] == []

    segunda = [*base,
               f("_General_Inbox/peli.mkv", inodo=2, mtime=viejo),
               f("_General_Inbox/copiando.mkv", inodo=3, mtime=int(AHORA) - 30)]
    destino = v.ejecutar(host="x", estado=tmp_path, confirmar_gb=0, ahora=AHORA + 5, instantanea=segunda)
    ult = json.loads((tmp_path / "ultimo.json").read_text(encoding="utf-8"))
    assert ult["linea_base"] is False and ult["nuevos"] == ["_General_Inbox/peli.mkv"]
    texto = destino.read_text(encoding="utf-8")
    assert "copiando.mkv" in texto and "En copia ahora mismo" in texto
    assert "no se ha movido, renombrado ni borrado nada" in texto
    # el que estaba en copia no entra en la instantánea: aparecerá como nuevo cuando esté estable
    guardada = json.loads((tmp_path / "instantanea.json").read_text(encoding="utf-8"))
    assert "_General_Inbox/copiando.mkv" not in guardada


def test_informe_muestra_duplicados_y_ahorro() -> None:
    a, b = f("A/x.mkv", tam=2 * 10**9, inodo=1), f("B/x.mkv", tam=2 * 10**9, inodo=2)
    g = v.agrupar_por_huella([[a, b]], {"A/x.mkv": "h", "B/x.mkv": "h"}, confirmado=False)
    txt = v.generar_informe(ahora=datetime(2026, 11, 15, 12, 0, tzinfo=ZoneInfo("Europe/Madrid")), total=2, tam_total=4 * 10**9,
                            linea_base=False, dif=v.Diferencias(), en_copia=[], grupos=g, duros=3)
    assert "2,0 GB" in txt and "muy probable" in txt and "sugerido como original" in txt
    assert "plan quarantine" in txt


def test_entre_bibliotecas_se_separa_de_la_misma_biblioteca() -> None:
    a, b = f("Ciclos/Actor/peliculas/X.mp4", inodo=1), f("Películas/X/X.mp4", inodo=2)
    c, d = f("Series/S/a.mkv", tam=200 * MB, inodo=3), f("Series/S/b.mkv", tam=200 * MB, inodo=4)
    cand = v.candidatos_duplicados([a, b, c, d])
    huellas = {"Ciclos/Actor/peliculas/X.mp4": "h", "Películas/X/X.mp4": "h",
               "Series/S/a.mkv": "k", "Series/S/b.mkv": "k"}
    grupos = v.agrupar_por_huella(cand, huellas, confirmado=False)
    por_tipo = {g.entre_bibliotecas for g in grupos}
    assert por_tipo == {True, False}
    txt = v.generar_informe(ahora=datetime(2026, 11, 15, 12, 0, tzinfo=ZoneInfo("Europe/Madrid")), total=4,
                            tam_total=1, linea_base=False, dif=v.Diferencias(), en_copia=[], grupos=grupos, duros=0)
    assert "Dentro de la misma biblioteca" in txt and "enlace duro" in txt
