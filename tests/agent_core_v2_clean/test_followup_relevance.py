"""Follow-ups: a specific request picks the chunk that answers it, even if delivered.

QA (SIMP): "¿Cómo me registro por primera vez?" after a full access procedure
picked consumables chunks (novelty) and claimed registration was not documented.
"""

from app.agent_core_v2_clean.progressive_evidence import select_progressive_evidence
from app.agent_core_v2_clean.unified_evidence_authority import _primary_continuity_selection

TITLE = "IN0504 INSTRUCTIVO USO DASHBOARD ALPHA"
SOURCE = "sharepoint://alpha/in0504"
REGISTRATION = ("Si es su primera vez debe registrarse: recibirá un correo de invitación, seleccione sign in, "
                "ingrese su correo corporativo y el código de acceso para finalizar el registro.")
CONSUMABLES = "Sección consumibles: el color del indicador muestra el tóner restante y el tamaño las impresiones restantes."
MONITORS = "Sección monitores: distribución por estado y días sin reportar de cada monitor."
NAVIGATION = "Menú principal con dispositivos, consumibles y monitores; barra lateral de filtros por cliente."


def _row(i, text, semantic):
    return {"id": f"R{i}", "title": TITLE, "source": SOURCE, "page": "", "text": text,
            "semantic_fit": {"score": semantic}, "metadata": {"provider": "henkia_ke", "ordinal": i}}


def _retrieval(delivered, attempts=()):
    evidence = [_row(1, REGISTRATION, 0.20), _row(2, NAVIGATION, 0.30), _row(3, CONSUMABLES, 0.35), _row(4, MONITORS, 0.33)]
    return {"generation_evidence": evidence, "evidence": evidence,
            "evidence_verdict": {"status": "sufficient", "selected_evidence": evidence},
            "query": {"fields": {"current_message": "¿Cómo me registro por primera vez en el dashboard de Alpha?"}},
            "_answer_context": {"delivered_guidance": [{"action": x} for x in delivered]},
            "_case_context": {"attempts": [{"action": x} for x in attempts]}}


def _understanding(act):
    return {"user_act": act, "topic_relation": "same_topic", "intent": "procedural",
            "current_goal": "Registrar por primera vez en el dashboard de Alpha",
            "goal_updates": {"operation": "registrar", "subject": "Alpha"}, "canonical_subject": "Alpha"}


def test_specific_request_reuses_the_delivered_chunk_that_answers_it():
    out = select_progressive_evidence(_retrieval([REGISTRATION, NAVIGATION]), _understanding("request_elaboration"))
    texts = [x["text"] for x in out["generation_evidence"]]
    assert texts[0] == REGISTRATION, texts
    assert CONSUMABLES not in texts and MONITORS not in texts
    assert out["progressive_evidence_selection"]["request_driven"]


def test_reported_attempt_still_moves_to_new_chunks():
    out = select_progressive_evidence(_retrieval([REGISTRATION], attempts=[REGISTRATION]), _understanding("attempt_result"))
    texts = [x["text"] for x in out["generation_evidence"]]
    assert texts[0] != REGISTRATION
    assert not out["progressive_evidence_selection"]["request_driven"]


def test_title_alone_does_not_align_a_chunk_of_the_primary_document():
    candidates = [dict(_row(1, REGISTRATION, 0.20)), dict(_row(3, CONSUMABLES, 0.35))]
    out = {"query": {"fields": {"previous_evidence_role": "primary", "goal": "Registrar por primera vez en el dashboard",
                                "details": {"operation": "registrar", "subject": "Alpha"}, "subject": "Alpha"}},
           "_answer_context": {"source_identities": [SOURCE], "goal": "Acceder al dashboard de Alpha"}}
    verdict = _primary_continuity_selection(out, candidates, {"registro", "primera", "dashboard"})
    assert verdict is not None
    assert [x["text"] for x in verdict["selected_evidence"]][0] == REGISTRATION
    assert CONSUMABLES not in [x["text"] for x in verdict["selected_evidence"]]


def test_procedural_pack_keeps_a_chunk_that_answers_the_request_without_marker_verbs():
    from app.agent_core_v2_clean.procedural_answer import evidence_pack, request_terms

    registration = ("Acceda mediante el enlace web seguro enviado a su correo. Para ingresar por primera vez es necesario "
                    "realizar el registro con su cuenta de correo y el token code enviado al correo electrónico.")
    unrelated = "Ubicación física: información sobre dónde se encuentra cada equipo dentro de la sede del cliente."
    retrieval = {"evidence": [{"id": "R1", "title": TITLE, "text": registration}, {"id": "R2", "title": TITLE, "text": unrelated}]}
    terms = request_terms("¿Cómo me registro por primera vez en el dashboard de Alpha?", _understanding("request_elaboration"))
    packed = evidence_pack(retrieval, terms=terms)
    assert [x["id"] for x in packed] == ["R1"], (terms, packed)
    assert evidence_pack(retrieval) == []  # previous behavior: neither chunk has a marker verb
