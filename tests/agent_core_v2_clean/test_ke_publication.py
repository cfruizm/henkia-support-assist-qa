"""Offline checks for KE-04: KE answers published as a complement.

KNOWLEDGE_PUBLISH_MODE=off keeps the KE route observational. With "complement",
the KE answer replaces the local answer only when the local answer used no
documentation and the KE answer is documented and isolated.
"""

from copy import deepcopy

from app.knowledge_gateway.agent_core_shadow import (
    apply_ke_document_order,
    complement_decision,
    execute,
    publish_mode,
)
from tests.agent_core_v2_clean.test_ke_shadow_isolation import _result


class _Memory:
    class _Goal:
        status = "needs_verification"

    def __init__(self):
        self.pending_goal = self._Goal()

    def to_dict(self):
        return {"pending_goal": {"status": self.pending_goal.status}}


def _ke_item(item_id, ordinal):
    return {"id": item_id, "title": "IN0504 Instructivo.pdf", "source": "sharepoint://simp/in0504",
            "page": "", "text": f"Fragmento {ordinal}", "metadata": {"provider": "henkia_ke", "ordinal": ordinal}}


def _runner(mode, documented=True):
    def run(result, message, config, session, budget, store):
        result = deepcopy(result)
        evidence = list(result["retrieval"].get("evidence") or [])
        cited = evidence[0]["id"] if evidence else "R1"
        result["answer"] = {"text": f"Procedimiento KE [{cited}].", "mode": mode,
                            "documented_evidence_used": documented, "knowledge_used": True}
        return result, {"skipped": True}, {"skipped": True}
    return run


def _internal_result():
    result = _result(topic_relation="new_topic", user_act="new_request")
    result["answer"] = {"text": "Orientación complementaria interna.", "mode": "controlled_internal_knowledge",
                        "documented_evidence_used": False, "knowledge_used": True}
    return result


def test_publish_mode_defaults_to_off_and_rejects_unknown_values():
    assert publish_mode({}) == "off"
    assert publish_mode({"KNOWLEDGE_PUBLISH_MODE": "Complement"}) == "complement"
    assert publish_mode({"KNOWLEDGE_PUBLISH_MODE": "replace"}) == "off"


def test_single_ke_document_is_put_in_ordinal_order_and_enabled_for_procedures():
    selected = [_ke_item("R1", 51), _ke_item("R2", 3), _ke_item("R3", 8)]
    retrieval = {"generation_evidence": selected, "evidence": selected,
                 "evidence_verdict": {"status": "sufficient", "selected_evidence": selected}}
    out = apply_ke_document_order(retrieval)
    exp = out["procedural_expansion"]
    assert exp["ok"] and exp["ordered"] and exp["same_document_only"]
    assert [x["metadata"]["ordinal"] for x in out["generation_evidence"]] == [3, 8, 51]
    assert [x["id"] for x in out["generation_evidence"]] == ["R1", "R2", "R3"]
    assert out["evidence_verdict"]["evidence_ids"] == ["R1", "R2", "R3"]


def test_two_ke_documents_or_rejected_verdict_keep_expansion_closed():
    other = dict(_ke_item("R2", 1), source="sharepoint://simp/other")
    two = {"generation_evidence": [_ke_item("R1", 2), other], "evidence_verdict": {"status": "sufficient"}}
    assert apply_ke_document_order(two)["procedural_expansion"]["reason"] == "ke_multiple_documents"
    none = {"generation_evidence": [], "evidence_verdict": {"status": "insufficient"}}
    assert not apply_ke_document_order(none)["procedural_expansion"]["enabled"]


def test_complement_rules():
    internal = {"mode": "controlled_internal_knowledge", "documented_evidence_used": False, "text": "x"}
    documented = {"mode": "procedural_documented_answer", "documented_evidence_used": True, "text": "y [R1]"}
    degraded = {"mode": "documented_degraded_reference", "documented_evidence_used": True, "text": "z"}
    route = {"evidence_status": "sufficient"}
    iso = {"isolated": True}
    assert complement_decision("complement", internal, documented, route, iso)["applied"]
    assert complement_decision("off", internal, documented, route, iso)["reason"] == "not_mode_complement"
    assert complement_decision("complement", documented, documented, route, iso)["reason"] == "not_local_not_documented"
    assert complement_decision("complement", internal, degraded, route, iso)["reason"] == "not_ke_documented"
    assert complement_decision("complement", internal, documented, route, {"isolated": False})["reason"] == "not_ke_isolated"


def test_execute_off_keeps_local_answer():
    result = _internal_result()
    store = {"answer_context": {}, "memory": _Memory()}
    block = execute(result, "Requisitos de HP SDS", {}, {}, None, store, _runner("documented_answer"))
    assert block["executed"] and not block["publication"]["applied"]
    assert result["answer"]["mode"] == "controlled_internal_knowledge"
    assert block["published_provider"] == "local_chroma" and not block["visible_to_user"]


def test_execute_complement_publishes_documented_ke_answer():
    result = _internal_result()
    memory = _Memory()
    store = {"answer_context": {}, "memory": memory}
    config = {"KNOWLEDGE_PUBLISH_MODE": "complement"}
    block = execute(result, "Requisitos de HP SDS", config, {}, None, store, _runner("documented_answer"))
    assert block["publication"]["applied"], block["publication"]
    assert result["answer"]["mode"] == "documented_answer"
    assert result["answer"]["retrieval_provider"] == "henkia_ke"
    assert result["local_answer_replaced"]["mode"] == "controlled_internal_knowledge"
    assert all(x["metadata"]["provider"] == "henkia_ke" for x in result["retrieval"]["evidence"])
    assert block["published_provider"] == "henkia_ke" and block["visible_to_user"]
    assert memory.pending_goal.status == "complete"


def test_execute_complement_never_replaces_a_documented_local_answer():
    result = _result()  # local answer is documented
    result["answer"]["documented_evidence_used"] = True
    store = {"answer_context": {}}
    block = execute(result, "¿Y los puertos?", {"KNOWLEDGE_PUBLISH_MODE": "complement"}, {}, None, store,
                    _runner("documented_answer"))
    assert not block["publication"]["applied"]
    assert result["answer"]["text"] == "Respuesta publicada [R1]."


def test_numbered_heading_after_long_list_is_not_split():
    from app.agent_core_v2_clean.visible_answer import format_visible_answer

    bullets = "\n".join(f"*   **Elemento {i}:** descripción extensa del componente número {i} del tablero [R5]." for i in range(8))
    raw = f"**2. Navegación**\nLa interfaz se organiza así [R5]:\n{bullets}\n\n**3. Sección Dispositivos**\nEsta sección muestra equipos [R6]."
    text, _ = format_visible_answer(raw, "procedural_documented_answer", "documented_only", "stop")
    assert "### 3. Sección Dispositivos" in text, text
    assert "\n\n### 3." in text and "### 3.\n" not in text
    assert format_visible_answer(text, "procedural_documented_answer", "documented_only", "stop")[0] == text


def test_sharepoint_ke_document_links_the_internal_library():
    from app.agent_core_v2_clean import source_access_policy
    from app.agent_core_v2_clean.source_footer import compact_sources
    from app.knowledge_gateway.agent_core_shadow import ke_evidence_rows

    rows = ke_evidence_rows({"results": [{"source_name": "IN0504.pdf", "document_uri": "sharepoint://b!x/01ABC",
                                          "content": "Acceso al tablero", "ordinal": 3}]})
    assert rows[0]["metadata"]["source_access"] == "internal_sharepoint"
    source_access_policy.configure_source_access({"internal_document_library_url": "https://example.sharepoint.com/lib"})
    try:
        rows[0]["id"] = "R1"
        footer = compact_sources(rows, ["R1"])
        assert "](https://example.sharepoint.com/lib) (biblioteca interna)" in footer, footer
    finally:
        source_access_policy.configure_source_access({})


def test_runtime_memory_keeps_provider_of_carried_evidence():
    from app.agent_core_v2_clean.runtime_memory import _compact_evidence

    row = _compact_evidence({"id": "R1", "title": "IN0504.pdf", "text": "x",
                             "metadata": {"provider": "henkia_ke", "source_access": "internal_sharepoint", "chunk_id": "c1"}})
    assert row["metadata"] == {"provider": "henkia_ke", "source_access": "internal_sharepoint"}


def test_packed_evidence_footer_recovers_internal_link_from_retrieval():
    from app.agent_core_v2_clean import source_access_policy
    from app.agent_core_v2_clean.source_footer import compact_sources, with_source_metadata

    full = {"id": "R1", "title": "IN0504.pdf", "source": "sharepoint://b!x/01ABC", "text": "x",
            "metadata": {"provider": "henkia_ke", "source_access": "internal_sharepoint"}}
    packed = [{"id": "R1", "title": "IN0504.pdf", "page": "", "source": "sharepoint://b!x/01ABC", "text": "x"}]
    source_access_policy.configure_source_access({"internal_document_library_url": "https://example.sharepoint.com/lib"})
    try:
        assert "](https://example.sharepoint.com/lib)" not in compact_sources(packed, ["R1"])
        footer = compact_sources(with_source_metadata(packed, {"generation_evidence": [full]}), ["R1"])
        assert "](https://example.sharepoint.com/lib) (biblioteca interna)" in footer, footer
        other = with_source_metadata(packed, {"generation_evidence": [dict(full, title="Otro.pdf")]})
        assert "metadata" not in other[0]
    finally:
        source_access_policy.configure_source_access({})


def test_primary_rules():
    route, iso = {"evidence_status": "sufficient"}, {"isolated": True}
    local_doc = {"mode": "documented_answer", "documented_evidence_used": True, "text": "local [R1]"}
    local_internal = {"mode": "controlled_internal_knowledge", "documented_evidence_used": False, "text": "x"}
    clarification = {"mode": "material_clarification", "documented_evidence_used": False, "text": "¿Cuál?"}
    ke_doc = {"mode": "procedural_documented_answer", "documented_evidence_used": True, "text": "ke [R1]"}
    ke_partial = {"mode": "procedural_documented_answer_partial", "documented_evidence_used": True, "text": "ke [R1]"}
    ke_degraded = {"mode": "documented_degraded_reference", "documented_evidence_used": True, "text": "z"}
    assert complement_decision("primary", local_doc, ke_doc, route, iso)["reason"] == "ke_primary_over_documented_local"
    assert complement_decision("primary", local_internal, ke_doc, route, iso)["reason"] == "ke_primary_over_undocumented_local"
    assert complement_decision("primary", local_doc, ke_degraded, route, iso)["reason"] == "not_ke_documented"
    assert complement_decision("primary", clarification, ke_doc, route, iso)["reason"] == "not_local_replaceable"
    assert complement_decision("primary", local_doc, ke_partial, route, iso)["reason"] == "not_ke_not_less_complete"
    assert complement_decision("primary", local_internal, ke_partial, route, iso)["applied"]
    assert complement_decision("primary", local_doc, ke_doc, {"evidence_status": "insufficient"}, iso)["reason"] == "not_ke_evidence_accepted"
    assert complement_decision("primary", local_doc, ke_doc, route, {"isolated": False})["reason"] == "not_ke_isolated"


def test_publish_mode_accepts_primary():
    assert publish_mode({"KNOWLEDGE_PUBLISH_MODE": "primary"}) == "primary"


def test_execute_primary_replaces_a_documented_local_answer():
    result = _result()
    result["answer"]["documented_evidence_used"] = True
    memory = _Memory()
    block = execute(result, "¿Y los puertos?", {"KNOWLEDGE_PUBLISH_MODE": "primary"}, {}, None,
                    {"answer_context": {}, "memory": memory}, _runner("documented_answer"))
    assert block["publication"]["applied"] and block["publication"]["reason"] == "ke_primary_over_documented_local"
    assert result["answer"]["retrieval_provider"] == "henkia_ke"
    assert result["local_answer_replaced"]["mode"] == "documented_answer"


def test_execute_primary_keeps_local_when_ke_is_not_documented():
    result = _result()
    result["answer"]["documented_evidence_used"] = True
    block = execute(result, "¿Y los puertos?", {"KNOWLEDGE_PUBLISH_MODE": "primary"}, {}, None,
                    {"answer_context": {}}, _runner("controlled_internal_knowledge", documented=False))
    assert not block["publication"]["applied"] and block["publication"]["reason"] == "not_ke_documented"
    assert result["answer"]["text"] == "Respuesta publicada [R1]."


def test_fenced_code_inside_a_list_stays_closed():
    from app.agent_core_v2_clean.visible_answer import format_visible_answer

    raw = ("**2. Crear la cola**\nPasos:\n\n*   **Linux:**\n    1. Instale CUPS:\n        ```bash\n        sudo apt update\n"
           "        sudo apt install cups\n        ```\n    2. Agregue la impresora:\n        ```bash\n        sudo lpadmin -p Find-Me -E\n"
           "        ```\n\n**3. Configurar en PaperCut**\nInicie sesión en la consola [R4].")
    text, _ = format_visible_answer(raw, "procedural_documented_answer", "documented_only", "stop")
    assert "        ```bash\n        sudo apt update\n        sudo apt install cups\n        ```" in text, text
    assert "        `sudo lpadmin -p Find-Me -E`" in text
    assert "### 3. Configurar en PaperCut" in text
    assert text.count("```") % 2 == 0
