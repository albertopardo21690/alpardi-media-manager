"""Adaptador Plex: API autenticada de mínimo privilegio, SOLO LECTURA en esta fase -- nunca
escribe en Plex (ni pide un escaneo/refresco) y nunca accede directamente a su base de datos
SQLite (regla no negociable del encargo). Disparar escaneos/refrescos es una operación "con
efectos" reservada para una skill/comando explícito más adelante (Fase 4), no para este adaptador.

El parseo de las respuestas está separado de las llamadas HTTP a propósito: las funciones
`_parsear_*` son puras (dict -> modelo) y se prueban con JSON sintético; las llamadas reales al
servidor de Alberto se prueban aparte, en tests/integration/, contra el Plex real.
"""
from __future__ import annotations

from types import TracebackType
from typing import Any, Self

import httpx

from alpardi_media_manager.plex.models import PlexItemSnapshot, PlexLibrary, PlexLibraryLocation


def _parsear_biblioteca(d: dict[str, Any]) -> PlexLibrary:
    return PlexLibrary(
        key=d["key"],
        type=d["type"],
        title=d["title"],
        agent=d["agent"],
        scanner=d["scanner"],
        language=d["language"],
        uuid=d["uuid"],
        updated_at=d["updatedAt"],
        created_at=d["createdAt"],
        scanned_at=d.get("scannedAt", 0),
        locations=[
            PlexLibraryLocation(id=loc["id"], path=loc["path"])
            for loc in d.get("Location", [])
        ],
    )


def _parsear_item(d: dict[str, Any]) -> PlexItemSnapshot:
    rutas = [
        part["file"]
        for media in d.get("Media", [])
        for part in media.get("Part", [])
        if "file" in part
    ]
    return PlexItemSnapshot(
        rating_key=d["ratingKey"],
        key=d["key"],
        guid=d.get("guid"),
        type=d["type"],
        title=d["title"],
        year=d.get("year"),
        added_at=d["addedAt"],
        updated_at=d["updatedAt"],
        view_count=d.get("viewCount", 0),
        view_offset=d.get("viewOffset"),
        last_viewed_at=d.get("lastViewedAt"),
        user_rating=d.get("userRating"),
        collections=[c["tag"] for c in d.get("Collection", [])],
        locked_fields=[f["name"] for f in d.get("Field", []) if f.get("locked")],
        file_paths=rutas,
    )


class PlexClient:
    """Cliente mínimo, de solo lectura. `token` nunca se imprime, nunca se registra en logs --
    solo se usa para construir la petición HTTP real."""

    def __init__(self, base_url: str, token: str, http_client: httpx.AsyncClient | None = None) -> None:
        self._base_url = base_url.rstrip("/")
        self._token = token
        self._client = http_client or httpx.AsyncClient(timeout=15.0)
        self._propio_cliente = http_client is None

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None,
    ) -> None:
        await self.cerrar()

    async def cerrar(self) -> None:
        if self._propio_cliente:
            await self._client.aclose()

    async def _get(self, path: str, **params: str) -> dict[str, Any]:
        respuesta = await self._client.get(
            f"{self._base_url}{path}",
            params={**params, "X-Plex-Token": self._token},
            headers={"Accept": "application/json"},
        )
        respuesta.raise_for_status()
        data: dict[str, Any] = respuesta.json()
        return data

    async def listar_bibliotecas(self) -> list[PlexLibrary]:
        data = await self._get("/library/sections")
        return [_parsear_biblioteca(d) for d in data["MediaContainer"].get("Directory", [])]

    async def snapshot_biblioteca(self, section_key: str) -> list[PlexItemSnapshot]:
        """Instantánea de TODOS los elementos de una biblioteca -- pensada para llamarse antes de
        aplicar un lote (regla del encargo: "Exporta antes del lote... snapshot lógico del estado
        Plex")."""
        data = await self._get(f"/library/sections/{section_key}/all")
        return [_parsear_item(d) for d in data["MediaContainer"].get("Metadata", [])]

    async def snapshot_item(self, rating_key: str) -> PlexItemSnapshot:
        # Verificado contra el servidor real (2026-09-09): un ratingKey inexistente da un 404
        # HTML, no una lista vacía en JSON -- se traduce a un error claro en vez de dejar escapar
        # la excepción de httpx sin contexto sobre qué ratingKey falló.
        try:
            data = await self._get(f"/library/metadata/{rating_key}")
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                raise ValueError(f"No existe ningún elemento de Plex con ratingKey={rating_key}") from e
            raise
        items = data["MediaContainer"].get("Metadata", [])
        if not items:
            raise ValueError(f"No existe ningún elemento de Plex con ratingKey={rating_key}")
        return _parsear_item(items[0])

    async def hay_sesiones_activas(self) -> bool:
        """Regla del encargo: "Evita saturar Plex durante reproducción activa; detecta sesiones si
        la API lo permite" -- se consulta antes de cualquier operación pesada (escaneo, lote
        grande), nunca se asume que no hay nadie viendo nada."""
        data = await self._get("/status/sessions")
        tamano: int = data["MediaContainer"].get("size", 0)
        return tamano > 0
