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
