import csv
import io
import json
from datetime import UTC, datetime
from pathlib import Path

from alpardi_media_manager.domain.models import ContentType, Fingerprint, InventoryItem
from alpardi_media_manager.inventory.scanner import escanear_directorio
from alpardi_media_manager.reports.inventory_report import (
    inventario_a_csv,
    inventario_a_json,
    inventario_a_markdown,
)


def _item(path: str = "a.mkv", size: int = 1234) -> InventoryItem:
    ahora = datetime.now(UTC)
    return InventoryItem(
        library_id="lib-1", authorized_root="/data", current_path=path, extension=".mkv",
        content_type=ContentType.MOVIE,
        fingerprint=Fingerprint(size_bytes=size, mtime=ahora, quick="abc123"),
        discovered_at=ahora, updated_at=ahora,
    )


def test_markdown_vacio():
    md = inventario_a_markdown([])
    assert "0 elementos" in md
    assert "Sin elementos" in md


def test_markdown_con_items():
    md = inventario_a_markdown([_item("Pelicula (2020)/Pelicula (2020).mkv")])
    assert "1 elementos" in md
    assert "Pelicula (2020)/Pelicula (2020).mkv" in md
    assert "movie" in md
    assert "discovered" in md


def test_json_estructura_y_reproducible():
    items = [_item("a.mkv"), _item("b.mkv", size=999)]
    j1 = inventario_a_json(items)
    j2 = inventario_a_json(items)
    assert j1 == j2

    datos = json.loads(j1)
    assert datos["total"] == 2
    assert datos["items"][0]["path"] == "a.mkv"
    assert datos["items"][1]["size_bytes"] == "999"


def test_csv_tiene_cabecera_y_una_fila_por_item():
    items = [_item("a.mkv"), _item("b.mkv")]
    csv_texto = inventario_a_csv(items)
    filas = list(csv.DictReader(io.StringIO(csv_texto)))
    assert len(filas) == 2
    assert filas[0]["path"] == "a.mkv"
    assert filas[1]["path"] == "b.mkv"
    assert set(filas[0].keys()) == {"id", "library_id", "path", "content_type", "state", "size_bytes", "extension"}


def test_reporte_de_un_escaneo_real_de_directorio_sintetico(tmp_path: Path):
    """No usa fixtures inventadas a mano -- exporta el resultado de un escaneo REAL (con
    ficheros sintéticos, nunca contenido de Alberto) para comprobar que ambos módulos encajan."""
    carpeta = tmp_path / "Pelicula (2020)"
    carpeta.mkdir()
    (carpeta / "Pelicula (2020).mkv").write_bytes(b"contenido de prueba")

    items = escanear_directorio(tmp_path, library_id="lib-movies", content_type=ContentType.MOVIE)
    assert len(items) == 1

    md = inventario_a_markdown(items)
    j = inventario_a_json(items)
    csv_texto = inventario_a_csv(items)

    assert "Pelicula (2020)/Pelicula (2020).mkv" in md
    assert json.loads(j)["total"] == 1
    assert "Pelicula (2020)/Pelicula (2020).mkv" in csv_texto
