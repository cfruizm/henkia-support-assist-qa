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


def test_scope_accepts_a_registered_product_named_by_the_understanding():
    from app.agent_core_v2_clean.scope_authority import reconcile_scope

    u = {"intent": "troubleshooting", "user_act": "new_request", "topic_relation": "new_topic", "domain_relevance": "in_scope",
         "canonical_subject": "Find-Me", "subject_origin": "current_message",
         "goal_updates": {"product": "PaperCut", "subject": "Find-Me", "symptom": "trabajos desaparecen antes de liberarlos"}}
    out, trace = reconcile_scope("Cambiando de tema, los trabajos de Find-Me desaparecen de la cola antes de liberarlos, ¿qué reviso?", u, {})
    assert out["domain_relevance"] == "in_scope", trace
    assert trace["reason"] != "independent_subject_without_printing_domain_evidence"
    unrelated = {**u, "canonical_subject": "Salesforce", "goal_updates": {"subject": "Salesforce", "operation": "exportar oportunidades"}}
    out, trace = reconcile_scope("¿Cómo exporto oportunidades en Salesforce?", unrelated, {})
    assert out["domain_relevance"] == "out_of_scope", trace


def test_followup_without_subject_continues_the_active_topic():
    from app.agent_core_v2_clean.scope_authority import reconcile_scope

    u = {"intent": "procedural", "user_act": "request_elaboration", "topic_relation": "same_topic", "domain_relevance": "in_scope",
         "canonical_subject": None, "reference_relation": "none", "goal_updates": {"operation": "registrar"}}
    before = {"active_subject": "SIMP", "subject_history": ["SIMP"]}
    out, trace = reconcile_scope("¿Cómo me registro por primera vez?", u, before)
    assert out["domain_relevance"] == "in_scope" and not out.get("needs_clarification"), trace
    # Without an active topic the same message still needs scope clarification.
    out, trace = reconcile_scope("¿Cómo me registro por primera vez?", u, {})
    assert trace["reason"] == "independent_request_without_domain_object_requires_scope_clarification", trace


def test_followup_value_request_activates_the_document_list():
    from app.agent_core_v2_clean.documented_fact_coverage import augment_exhaustive_numeric_evidence, followup_value_request

    table = "Puerto 443 TCP salida. Puerto 5222 TCP mensajería. Puerto 161 UDP SNMP. Puerto 3910 TCP impresoras."
    base = [{"id": "R1", "title": "SDS Requirements", "source": "sds.pdf", "page": "5", "text": "Requisitos de red: el monitor usa varios puertos de Internet e intranet."}]
    retrieval = {"generation_evidence": base, "evidence": base,
                 "diagnostic_evidence": base + [{"id": "D1", "title": "SDS Requirements", "source": "sds.pdf", "page": "6", "text": table}],
                 "evidence_verdict": {"selected_evidence": base},
                 "query": {"fields": {"user_act": "request_elaboration", "topic_relation": "same_topic"}}}
    assert followup_value_request(retrieval, "¿Y los puertos?")
    out, diag = augment_exhaustive_numeric_evidence(retrieval, "¿Y los puertos?")
    assert diag["activated"], diag
    assert any("5222" in x["text"] for x in out["generation_evidence"])
    new_topic = {**retrieval, "query": {"fields": {"user_act": "new_request", "topic_relation": "new_topic"}}}
    assert not followup_value_request(new_topic, "¿Y los puertos?")


def test_value_followup_leaves_a_document_without_the_values():
    from app.agent_core_v2_clean.unified_evidence_authority import _primary_continuity_selection

    procedure = {"id": "R1", "title": "DA0403 Instalar monitor SDS", "source": "sp://da0403", "page": "",
                 "text": "Para instalar el monitor SDS ejecute el instalador y registre el equipo en el portal."}
    table = {"id": "R2", "title": "HP SDS Manager System Requirements", "source": "kb://sds-req", "page": "",
             "text": "Puertos requeridos: 443 TCP salida, 5222 TCP mensajería, 161 UDP SNMP, 3910 TCP impresoras."}
    out = {"query": {"fields": {"previous_evidence_role": "primary", "user_act": "request_elaboration",
                                "current_message": "¿Y los puertos?", "goal": "Conocer los puertos de HP SDS Monitor"}},
           "_answer_context": {"source_identities": ["sp://da0403"], "goal": "Requisitos de HP SDS Monitor"}}
    assert _primary_continuity_selection(out, [procedure, table], {"puertos"}) is None
    # When the active document has the values, continuity keeps it.
    with_values = dict(procedure, text="Puertos del monitor: 443 TCP y 5222 TCP.")
    assert _primary_continuity_selection(out, [with_values, table], {"puertos"}) is not None


def test_value_followup_sees_other_documents_outside_the_candidate_pool():
    from app.agent_core_v2_clean.unified_evidence_authority import _primary_continuity_selection

    procedure = {"id": "R1", "title": "DA0403 Instalar monitor SDS", "source": "sp://da0403", "page": "",
                 "text": "Para instalar el monitor SDS ejecute el instalador y registre el equipo en el portal."}
    table = {"id": "D2", "title": "HP SDS Manager System Requirements", "source": "kb://sds-req", "page": "",
             "text": "Puerto 443 TCP salida, Puerto 161 UDP SNMP, Puerto 427 UDP SLP."}
    out = {"query": {"fields": {"previous_evidence_role": "primary", "user_act": "request_elaboration",
                                "current_message": "¿Y los puertos?"}},
           "_answer_context": {"source_identities": ["sp://da0403"]}, "diagnostic_evidence": [procedure, table]}
    assert _primary_continuity_selection(out, [procedure], {"puertos"}) is None


def test_value_followup_verdict_selects_the_document_with_the_table():
    from app.agent_core_v2_clean.unified_evidence_authority import apply_unified_evidence_verdict

    procedure = {"id": "R1", "title": "DA0403 Instalar monitor SDS", "source": "sp://da0403", "page": "",
                 "text": "Requisitos para instalar el monitor SDS: sistema operativo Windows y acceso a Internet.",
                 "semantic_fit": {"score": 0.4}}
    table = {"id": "D2", "title": "HP SDS Manager System Requirements", "source": "kb://sds-req", "page": "4",
             "text": "Puertos requeridos para el monitor SDS: Puerto 443 TCP salida, Puerto 161 UDP SNMP, Puerto 427 UDP SLP, Puerto 5222 TCP.",
             "semantic_fit": {"score": 0.35}}
    retrieval = {"ok": True, "generation_evidence": [procedure], "evidence": [procedure], "diagnostic_evidence": [procedure, table],
                 "query": {"fields": {"previous_evidence_role": "primary", "user_act": "request_elaboration", "topic_relation": "same_topic",
                                      "current_message": "¿Y los puertos?", "goal": "Requisitos para instalar HP SDS Monitor",
                                      "details": {"subject": "HP SDS Monitor", "operation": "instalar"}, "intent": "requirements"}},
                 "_answer_context": {"source_identities": ["sp://da0403"], "goal": "Requisitos para instalar HP SDS Monitor"}}
    understanding = {"intent": "requirements", "user_act": "request_elaboration", "topic_relation": "same_topic",
                     "current_goal": "Conocer los puertos requeridos por HP SDS Monitor", "canonical_subject": "HP SDS Monitor",
                     "goal_updates": {"subject": "HP SDS Monitor", "focus": "puertos"}}
    verdict = apply_unified_evidence_verdict(retrieval, "¿Y los puertos?", understanding)["evidence_verdict"]
    sources = {x["source"] for x in verdict.get("selected_evidence") or []}
    assert "kb://sds-req" in sources, verdict.get("reason")
