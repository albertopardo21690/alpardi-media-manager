"""Servidor MCP local por stdio -- superficie DELIBERADAMENTE de solo lectura.

Decisión de seguridad explícita (ver docs/SECURITY.md): las herramientas MCP son invocables por
el propio modelo sin que Alberto escriba ningún comando -- justo lo contrario de una skill con
`disable-model-invocation: true`. Por eso este servidor NUNCA expone `apply`, `rollback` ni
`backup create`: cualquiera de esos, si viviera aquí, dejaría que Claude aplicara un cambio real
sobre la colección multimedia sin que Alberto tuviera que teclear `/plex-apply` -- justo lo que el
encargo prohíbe explícitamente ("Claude nunca puede autoautorizarse"). Esas operaciones solo
existen como skills con `disable-model-invocation: true` en `.claude/skills/`, que a su vez
invocan la CLI real -- nunca esta capa.

Todas las herramientas de aquí son de solo lectura DE VERDAD: ninguna escribe un byte en disco (ni
siquiera un plan en `plans/` -- `plan_rename_preview` genera el plan en memoria y lo devuelve, no
lo guarda; guardarlo para poder aplicarlo después es cosa de la skill `/plex-plan`, que llama a la
CLI real).

Vive en `mcp/` (no en `cli/`) y solo importa desde capas por debajo en ARCHITECTURE.md -- nunca
desde `cli/`, que es su capa hermana (mismo motivo por el que `proponer_operaciones_pelicula`,
`verificar_coincidencias_pelicula`, `run_all_checks` y la resolución de config viven fuera de
`cli/`, ver commits anteriores de esta misma Fase 4)."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from alpardi_media_manager.config import leer_plex_token, nas_ssh_host, plex_base_url
from alpardi_media_manager.diagnostics.checks import run_all_checks
from alpardi_media_manager.domain.models import ContentType
from alpardi_media_manager.inventory.scanner import escanear_directorio
from alpardi_media_manager.matching.engine import verificar_coincidencias_pelicula
from alpardi_media_manager.planning.plan import (
    calcular_inventory_hash,
    generar_plan_renombrado,
    proponer_operaciones_pelicula,
    serializar_plan,
)
from alpardi_media_manager.plex.client import PlexClient
from alpardi_media_manager.providers.status import leer_estado_proveedores

_SOLO_LECTURA_LOCAL = ToolAnnotations(
    read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False,
)
_SOLO_LECTURA_RED = ToolAnnotations(
    read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=True,
)

server = MCPServer(
    "alpardimedia-manager",
    instructions=(
        "Gestor multimedia para Plex. Todas las herramientas de aquí son de SOLO LECTURA -- "
        "nunca escriben ni modifican nada, ni siquiera un plan en disco. Proponer un renombrado "
        "real y guardarlo (/plex-plan), aplicarlo (/plex-apply) o revertirlo (/plex-rollback) "
        "son siempre skills que Alberto debe invocar escribiendo el comando él mismo -- nunca "
        "herramientas de este servidor."
    ),
)


def _content_type_o_error(content_type: str) -> ContentType:
    try:
        return ContentType(content_type)
    except ValueError as e:
        validos = ", ".join(t.value for t in ContentType)
        raise ValueError(f"content_type inválido: '{content_type}'. Válidos: {validos}") from e


def _raiz_o_error(root: str) -> Path:
    ruta = Path(root)
    if not ruta.is_dir():
        raise ValueError(f"La raíz no existe o no es un directorio: {ruta}")
    return ruta


@server.tool(annotations=_SOLO_LECTURA_RED)
def doctor() -> dict[str, Any]:
    """Diagnóstico de entorno: versión de Python, binarios externos (ffprobe/ffmpeg/mediainfo), y
    alcanzabilidad real de Plex y del NAS por SSH. Solo lectura, sin escribir nada."""
    resultados = run_all_checks(
        plex_base_url=plex_base_url(), plex_token=leer_plex_token(), nas_ssh_host=nas_ssh_host(),
    )
    return {"checks": [{"name": r.name, "status": r.status.value, "detail": r.detail} for r in resultados]}


@server.tool(annotations=_SOLO_LECTURA_RED)
async def plex_libraries() -> dict[str, Any]:
    """Lista las bibliotecas reales configuradas en el servidor Plex de Alberto. Solo lectura --
    nunca pide un escaneo/refresco ni toca la base de datos SQLite de Plex."""
    token = leer_plex_token()
    if not token:
        raise RuntimeError("Sin token de Plex disponible (ver docs/SECURITY.md)")
    async with PlexClient(plex_base_url(), token) as cliente:
        bibliotecas = await cliente.listar_bibliotecas()
    return {
        "libraries": [
            {
                "key": b.key, "type": b.type, "title": b.title,
                "agent": b.agent, "scanner": b.scanner, "language": b.language,
            }
            for b in bibliotecas
        ],
    }


@server.tool(annotations=_SOLO_LECTURA_LOCAL)
def inventory_scan(root: str, library_id: str, content_type: str) -> dict[str, Any]:
    """Escanea una raíz de biblioteca autorizada y devuelve el inventario real de archivos
    encontrados. Nunca escribe nada -- ni siquiera crea un fichero de caché."""
    tipo = _content_type_o_error(content_type)
    ruta = _raiz_o_error(root)
    items = escanear_directorio(ruta, library_id=library_id, content_type=tipo)
    return {
        "total": len(items),
        "items": [
            {"path": item.current_path, "size_bytes": item.fingerprint.size_bytes, "state": item.state.value}
            for item in items
        ],
    }


@server.tool(annotations=_SOLO_LECTURA_LOCAL)
def providers_status(config_path: str = "config/providers.yaml") -> dict[str, Any]:
    """Qué proveedores de metadatos están habilitados/deshabilitados según config/providers.yaml
    (o su plantilla si todavía no existe una configuración real). Nunca hace tráfico de red ni lee
    el valor de ninguna credencial -- solo si existe una referencia configurada."""
    try:
        estado = leer_estado_proveedores(Path(config_path))
    except FileNotFoundError as e:
        raise RuntimeError(str(e)) from e
    return {
        "config_path": str(estado.config_path),
        "is_template": estado.is_template,
        "providers": [
            {"provider": p.provider, "enabled": p.enabled, "has_credential_ref": p.has_credential_ref}
            for p in estado.providers
        ],
    }


@server.tool(annotations=_SOLO_LECTURA_LOCAL)
def match_check(root: str, library_id: str, content_type: str) -> dict[str, Any]:
    """Evalúa el estado de coincidencia LOCAL de cada elemento (solo movie por ahora) -- sin
    llamar a ningún proveedor todavía (ninguno está activo, ver providers_status). Con la lista de
    candidatos vacía, todo elemento aparece honestamente como needs_review/sin_interpretar: eso es
    correcto y esperado hasta activar al menos un proveedor, nunca un error."""
    if content_type != "movie":
        raise ValueError("match_check de momento solo soporta content_type='movie'")
    ruta = _raiz_o_error(root)
    items = escanear_directorio(ruta, library_id=library_id, content_type=ContentType.MOVIE)
    resultados = verificar_coincidencias_pelicula(items)
    return {"total": len(resultados), "results": resultados}


@server.tool(annotations=_SOLO_LECTURA_LOCAL)
def plan_rename_preview(root: str, library_id: str, content_type: str) -> dict[str, Any]:
    """Genera una VISTA PREVIA de un plan de renombrado (solo movie por ahora) -- nunca lo guarda
    en disco ni toca ningún archivo real. Para guardarlo de verdad y poder aplicarlo después, usa
    la skill /plex-plan (que sí escribe el plan.json, siempre invocada por Alberto)."""
    if content_type != "movie":
        raise ValueError("plan_rename_preview de momento solo soporta content_type='movie'")
    ruta = _raiz_o_error(root)
    items = escanear_directorio(ruta, library_id=library_id, content_type=ContentType.MOVIE)
    operaciones, saltados = proponer_operaciones_pelicula(items)
    inventory_hash = calcular_inventory_hash(items)
    plan = generar_plan_renombrado(operaciones, inventory_hash, authorized_root=ruta)
    resultado = serializar_plan(plan)
    resultado["skipped_unparseable"] = saltados
    return resultado


def main() -> None:
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
