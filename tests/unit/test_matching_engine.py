from datetime import UTC, datetime

from alpardi_media_manager.domain.states import ItemState
from alpardi_media_manager.matching.engine import LocalEvidence, decidir_coincidencia
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
