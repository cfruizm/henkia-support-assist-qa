"""Offline checks: the KE shadow route must never use local Chroma evidence.

The KE-03 campaign showed shadow answers citing local documents (with pages)
because the shadow reused the published route's answer context. The shadow
now keeps its own context (store["ke_shadow_answer_context"]).
"""

from copy import deepcopy

from app.knowledge_gateway.agent_core_shadow import (
    SHADOW_CONTEXT_KEY,
    build_shadow_retrieval,
    execute,
    isolation_report,
)

KE_TEXT = (
    "HP SDS Monitor requiere .NET 4.5, acceso a Internet o a un proxy HTTP y red IPv4. "
    "Los puertos 443 y 5222 deben estar permitidos en el firewall para la comunicacion."
)
LOCAL_TEXT = (
    "Documento local de Chroma: la consola de administracion usa el puerto 29 de ejemplo "
    "y requiere revisar la conectividad entre el servidor y los dispositivos."
)


def _local_item(item_id="R1"):
    return {
        "id": item_id,
        "title": "Administrator Guide - Local Product",
        "source": "/content/knowledge_base_pdfs/LOCAL/admin_guide.pdf",
        "page": "29",
        "text": LOCAL_TEXT,
        "metadata": {"product": "local_product", "page_label": "29"},
    }


def _ke_rows():
    return [
        {
            "source_name": "HP SDS Manager - System Requirements.pdf",
            "document_uri": "tenants/henkia/kb/test/HP SDS Manager - System Requirements.pdf",
            "file_id": "file-1",
            "chunk_id": "c1",
            "ordinal": 3,
            "content": KE_TEXT,
            "score": 0.82,
        },
        {
            "source_name": "HP SDS Manager - System Requirements.pdf",
            "document_uri": "tenants/henkia/kb/test/HP SDS Manager - System Requirements.pdf",
            "file_id": "file-1",
            "chunk_id": "c2",
            "ordinal": 4,
            "content": KE_TEXT + " Tambien se documentan certificados y listas de revocacion.",
            "score": 0.78,
        },
    ]


def _local_context():
    return {
        "canonical_subject": "HP SDS",
        "source_identities": ["/content/knowledge_base_pdfs/LOCAL/admin_guide.pdf"],
        "cited_evidence": [_local_item("R1")],
        "active_document_evidence_ledger": [_local_item("R1")],
    }


def _result(topic_relation="same_topic", user_act="follow_up"):
    local = [_local_item("R1"), _local_item("R2")]
    return {
        "understanding": {
            "intent": "requirements",
            "user_act": user_act,
            "topic_relation": topic_relation,
            "canonical_subject": "HP SDS",
            "reference_relation": "current_subject",
            "current_goal": "Requisitos de HP SDS",
        },
        "decision": {"action": "defer_to_retrieval"},
        "topic_boundary": {"relation": topic_relation, "previous_evidence_role": "eligible"},
        "answer": {"text": "Respuesta publicada [R1].", "mode": "documented_answer"},
        "retrieval": {
            "enabled": True,
            "ok": True,
            "query": {"text": "requisitos HP SDS", "fields": {"topic_relation": topic_relation, "user_act": user_act}},
            "evidence": local,
            "generation_evidence": local,
            "diagnostic_evidence": local,
            "evidence_verdict": {"status": "sufficient", "accepted": True, "selected_evidence": local},
            "_answer_context": _local_context(),
            "_case_context": {"attempts": [], "observations": []},
        },
        "knowledge_comparison": {
            "query": "requisitos HP SDS",
            "normalized_result": {"http_status": 200, "error": None, "results": _ke_rows()},
        },
    }


def _fake_answer_runner(result, message, config, session, budget, store):
    """Stand-in for Agent Core _answers: cites the first evidence item."""
    result = deepcopy(result)
    evidence = list(result["retrieval"].get("evidence") or [])
    cited = evidence[0]["id"] if evidence else "R1"
    result["answer"] = {"text": f"Respuesta de la sombra con evidencia KE [{cited}].", "mode": "documented_answer"}
    return result, {"skipped": True}, {"skipped": True}


def test_shadow_retrieval_drops_local_evidence_and_local_context():
    retrieval = build_shadow_retrieval(_result(), "¿Y los puertos?", answer_context={}, continuity={})
    report = isolation_report(retrieval)
    assert report["isolated"], report
    assert all(item["metadata"]["provider"] == "henkia_ke" for item in retrieval["evidence"])
    assert "Administrator Guide" not in str(retrieval.get("_answer_context"))


def test_isolation_report_flags_local_items():
    report = isolation_report({"evidence": [_local_item()], "_answer_context": _local_context()})
    assert not report["isolated"]
    assert report["non_ke_item_count"] == 2


def test_execute_keeps_its_own_context_and_never_touches_the_published_one():
    store = {"answer_context": _local_context()}
    published_context = deepcopy(store["answer_context"])

    first = _result(topic_relation="new_topic", user_act="new_request")
    block1 = execute(first, "Requisitos de HP SDS", {}, {}, None, store, _fake_answer_runner)
    assert block1["executed"], block1
    assert block1["context"]["source"] == "none"
    assert block1["isolation"]["isolated"], block1["isolation"]
    assert store["answer_context"] == published_context
    ledger = store[SHADOW_CONTEXT_KEY].get("active_document_evidence_ledger") or store[SHADOW_CONTEXT_KEY].get("cited_evidence")
    assert ledger and all(item["metadata"].get("provider") == "henkia_ke" for item in ledger)

    second = _result(topic_relation="same_topic", user_act="follow_up")
    block2 = execute(second, "¿Y los puertos?", {}, {}, None, store, _fake_answer_runner)
    assert block2["executed"], block2
    assert block2["context"]["source"] == "ke_shadow_ledger"
    assert block2["isolation"]["isolated"], block2["isolation"]
    assert store["answer_context"] == published_context
    assert block2["affects_publication"] is False and block2["production_changed"] is False


def test_execute_skips_without_touching_contexts_when_ke_fails():
    store = {"answer_context": _local_context()}
    result = _result()
    result["knowledge_comparison"]["normalized_result"] = {"http_status": None, "error": {"code": "read_timeout"}}
    block = execute(result, "¿Y los puertos?", {}, {}, None, store, _fake_answer_runner)
    assert block["executed"] is False and block["skip_reason"] == "ke_provider_not_evaluable"
    assert SHADOW_CONTEXT_KEY not in store
