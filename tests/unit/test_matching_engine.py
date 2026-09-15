from datetime import UTC, datetime

from alpardi_media_manager.domain.models import ContentType, Fingerprint, InventoryItem
from alpardi_media_manager.domain.states import ItemState
from alpardi_media_manager.matching.engine import (
    LocalEvidence,
    decidir_coincidencia,
    verificar_coincidencias_episodio,
)
from alpardi_media_manager.providers.models import ExternalId, SearchCandidate


def _candidato(
    title: str, year: str, entity_type: str = "movie",
    external_ids: list[ExternalId] | None = None, provider: str = "tmdb",
) -> SearchCandidate:
    return SearchCandidate(
        provider=provider, title_localized=title, entity_type=entity_type,
        year_or_date=year, external_ids=external_ids or [], score=0.0,
    )


def _eid(namespace: str, value: str) -> ExternalId:
    return ExternalId(namespace=namespace, value=value, source="test", validated_at=datetime.now(UTC))


# --- Camino feliz -----------------------------------------------------------------------------

def test_id_ya_presente_y_validado_por_un_candidato_es_matched():
    evidencia = LocalEvidence(parsed_title="Blade Runner", parsed_year=1982, external_id_namespace="tmdb", external_id_value="78")
    candidatos = [_candidato("Blade Runner", "1982", external_ids=[_eid("tmdb", "78")])]
    decision = decidir_coincidencia(evidencia, candidatos)
    assert decision.state == ItemState.MATCHED
    assert decision.score == 1.0


def test_titulo_y_ano_coincidentes_sin_id_es_matched():
    evidencia = LocalEvidence(parsed_title="7 minutos", parsed_year=2009)
    candidatos = [_candidato("7 minutos", "2009")]
    decision = decidir_coincidencia(evidencia, candidatos)
    assert decision.state == ItemState.MATCHED
    assert decision.candidate is not None
    assert decision.candidate.title_localized == "7 minutos"


def test_titulo_normalizado_ignora_acentos_y_mayusculas():
    evidencia = LocalEvidence(parsed_title="Pelicula Con Acentos", parsed_year=2020)
    candidatos = [_candidato("película con acentos", "2020")]
    decision = decidir_coincidencia(evidencia, candidatos)
    assert decision.state == ItemState.MATCHED


# --- Regla: un ID exacto de tipo incorrecto no se acepta --------------------------------------

def test_id_presente_pero_para_tipo_de_entidad_distinto_no_se_acepta():
    """El ID 'tmdb-78' existe entre los candidatos, pero como serie, no como película -- no debe
    aceptarse como si fuera la película correspondiente."""
    evidencia = LocalEvidence(
        parsed_title="Blade Runner", parsed_year=1982, entity_type="movie",
        external_id_namespace="tmdb", external_id_value="78",
    )
    candidatos = [_candidato("Blade Runner (serie)", "1982", entity_type="tv", external_ids=[_eid("tmdb", "78")])]
    decision = decidir_coincidencia(evidencia, candidatos)
    assert decision.state == ItemState.NEEDS_REVIEW
    assert "tipo_incorrecto" in decision.reasons[0]


# --- Regla: año desconocido no equivale a año coincidente --------------------------------------

def test_sin_ano_local_nunca_es_matched_automaticamente():
    evidencia = LocalEvidence(parsed_title="Titulo Cualquiera", parsed_year=None)
    candidatos = [_candidato("Titulo Cualquiera", "2015")]
    decision = decidir_coincidencia(evidencia, candidatos)
    assert decision.state == ItemState.NEEDS_REVIEW
    assert decision.candidate is None  # no se elige ninguno "por si acaso"


# --- Regla: no convertir null/vacío/ausente en el mismo estado ---------------------------------

def test_candidato_sin_year_or_date_no_cuenta_como_coincidencia():
    """Un candidato con year_or_date=None nunca debe tratarse como 'coincide' solo porque no
    contradice explícitamente -- ausencia de dato no es lo mismo que coincidencia."""
    evidencia = LocalEvidence(parsed_title="Algo", parsed_year=2020)
    candidato_sin_fecha = SearchCandidate(
        provider="tmdb", title_localized="Algo", entity_type="movie",
        year_or_date=None, external_ids=[], score=0.0,
    )
    decision = decidir_coincidencia(evidencia, [candidato_sin_fecha])
    assert decision.state == ItemState.NEEDS_REVIEW


# --- Regla: no sobrescribir un ID ya validado y bloqueado con un candidato "mejor" -------------

def test_id_bloqueado_ignora_candidatos_con_mayor_similitud_de_titulo():
    """Aunque exista un candidato con título más parecido, si ya hay un ID bloqueado, ese ID
    manda -- nunca se cambia por popularidad/similitud de otro candidato."""
    evidencia = LocalEvidence(
        parsed_title="Titulo Local Distinto", parsed_year=1999,
        external_id_namespace="tmdb", external_id_value="999", locked=True,
    )
    candidato_bloqueado = _candidato("Titulo Real Del Id", "1999", external_ids=[_eid("tmdb", "999")])
    candidato_tentador = _candidato("Titulo Local Distinto", "1999")  # coincide MEJOR por texto
    decision = decidir_coincidencia(evidencia, [candidato_tentador, candidato_bloqueado])
    assert decision.state == ItemState.MATCHED
    assert decision.candidate is candidato_bloqueado
    assert decision.reasons == ("id_bloqueado_no_se_reconsidera",)


# --- Regla: si dos fuentes discrepan, needs_review, nunca por mayoría -------------------------

def test_dos_candidatos_igual_de_buenos_mismo_ano_da_needs_review():
    evidencia = LocalEvidence(parsed_title="Titulo Ambiguo", parsed_year=2010)
    candidatos = [
        _candidato("Titulo Ambiguo", "2010", provider="tmdb"),
        _candidato("Titulo Ambiguo", "2010", provider="tvmaze"),
    ]
    decision = decidir_coincidencia(evidencia, candidatos)
    assert decision.state == ItemState.NEEDS_REVIEW
    assert "ambiguos" in decision.reasons[0]


def test_similitud_de_titulo_baja_da_needs_review_no_falso_positivo():
    evidencia = LocalEvidence(parsed_title="Nombre Completamente Distinto", parsed_year=2010)
    candidatos = [_candidato("Otro Titulo Que No Se Parece", "2010")]
    decision = decidir_coincidencia(evidencia, candidatos)
    assert decision.state == ItemState.NEEDS_REVIEW


def test_sin_candidatos_es_needs_review():
    evidencia = LocalEvidence(parsed_title="Nada Que Encontrar", parsed_year=2020)
    decision = decidir_coincidencia(evidencia, [])
    assert decision.state == ItemState.NEEDS_REVIEW
    assert decision.candidate is None


# --- verificar_coincidencias_episodio -----------------------------------------------------------

def _item_episodio(path: str) -> InventoryItem:
    ahora = datetime.now(UTC)
    return InventoryItem(
        library_id="lib", authorized_root="/data", current_path=path, extension=".mkv",
        content_type=ContentType.TV_EPISODE,
        fingerprint=Fingerprint(size_bytes=1, mtime=ahora, quick="q"),
        discovered_at=ahora, updated_at=ahora,
    )


def test_verificar_coincidencias_episodio_nombre_no_interpretable_es_sin_interpretar():
    items = [_item_episodio("archivo_cualquiera_sin_patron.mkv")]
    resultados = verificar_coincidencias_episodio(items)
    assert resultados[0]["state"] == "sin_interpretar"
    assert resultados[0]["reasons"] == ["nombre_no_interpretable"]


def test_verificar_coincidencias_episodio_sin_ano_es_needs_review_pero_SI_se_evalua():
    """A diferencia de `proponer_operaciones_episodio` (que salta los episodios sin año),
    matching sí evalúa un episodio sin año -- no hace falta año para decidir needs_review, y
    `decidir_coincidencia` ya trata 'sin año' como 'no se puede confirmar automáticamente'."""
    items = [_item_episodio("Band of Brothers - s01e01 - Currahee.mkv")]
    resultados = verificar_coincidencias_episodio(items)
    assert len(resultados) == 1
    assert resultados[0]["state"] == ItemState.NEEDS_REVIEW.value
    assert resultados[0]["reasons"] == ["sin_ano_local_no_se_puede_confirmar_automaticamente"]


def test_verificar_coincidencias_episodio_con_ano_sin_proveedores_activos_es_needs_review():
    """Sin ningún proveedor activo (docs/DECISIONS.md #5), `candidatos` siempre es una lista
    vacía -- todo acaba en needs_review, igual que la versión de película."""
    items = [_item_episodio("Band of Brothers (2001) - s01e01 - Currahee.mkv")]
    resultados = verificar_coincidencias_episodio(items)
    assert resultados[0]["state"] == ItemState.NEEDS_REVIEW.value
    assert resultados[0]["reasons"] == ["ningun_candidato_con_ano_coincidente"]


def test_verificar_coincidencias_episodio_multi_episodio_evalua_todos_los_items():
    items = [
        _item_episodio("Band of Brothers (2001) - s01e01 - Currahee.mkv"),
        _item_episodio("ShowName (2020) - s02e05-e06.mkv"),
    ]
    resultados = verificar_coincidencias_episodio(items)
    assert len(resultados) == 2
    assert {r["path"] for r in resultados} == {
        "Band of Brothers (2001) - s01e01 - Currahee.mkv",
        "ShowName (2020) - s02e05-e06.mkv",
    }
