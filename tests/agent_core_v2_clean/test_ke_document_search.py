"""Offline checks for KE-05: search inside one KE document (rag.filters.document_uri).

No network: requests.post and the fetchers are replaced by fakes.
"""

from copy import deepcopy

import app.knowledge_gateway.henkia_knowledge_engine as ke
from app.agent_core_v2_clean.documented_answer import KE_SAME_DOCUMENT_FETCHER
from app.knowledge_gateway.agent_core_shadow import (
    EXPANDED_CHUNK_LIMIT,
    apply_ke_document_order,
    document_queries,
    execute,
    ke_document_fetcher,
)
from tests.agent_core_v2_clean.test_ke_multi_base import BASE, _Response
from tests.agent_core_v2_clean.test_ke_shadow_isolation import _result

URI = "sharepoint://simp/in0504"


def _ke(item_id, ordinal, chunk=None):
    return {"id": item_id, "title": "IN0504.pdf", "source": URI, "page": "", "text": f"Fragmento {ordinal}",
            "metadata": {"provider": "henkia_ke", "ordinal": ordinal, "chunk_id": chunk or f"c{ordinal}",
                         "knowledge_base_id": "kb2"}}


def _accepted(items):
    return {"generation_evidence": items, "evidence": items,
            "evidence_verdict": {"status": "sufficient", "selected_evidence": items}}


def test_search_document_sends_document_filter_and_query_list():
    sent = {}

    def post(url, headers=None, json=None, timeout=None):
        sent.update(url=url, json=json)
        return _Response(200, {"data": []})
    original = ke.requests.post
    ke.requests.post = post
    try:
        result = ke.search_document(["¿Cómo accedo?", "Acceder al dashboard"], {**BASE, "HENKIA_KE_KB_IDS": "kb1,kb2"}, "kb2", URI, 12)
    finally:
        ke.requests.post = original
    assert sent["url"].endswith("/vector_stores/kb2/search")
    assert sent["json"]["rag"] == {"filters": {"document_uri": [URI]}}
    assert sent["json"]["query"] == ["¿Cómo accedo?", "Acceder al dashboard"]
    assert sent["json"]["max_num_results"] == 12
    assert result.http_status == 200 and result.results == []


def test_document_queries_use_message_and_goal_once():
    result = {"understanding": {"current_goal": "Acceder al dashboard del SIMP"}}
    assert document_queries("¿Cómo accedo?", result) == ["¿Cómo accedo?", "Acceder al dashboard del SIMP"]
    assert document_queries("x", {"understanding": {"current_goal": "x"}}) == ["x"]


def test_same_document_chunks_are_added_deduplicated_capped_and_ordered():
    calls = []

    def fetch(query, source, k):
        calls.append((query, source, k))
        rows = [_ke(f"KE{i}", i) for i in (2, 51, 3, 30)] + [_ke(f"KE{i}", 100 + i) for i in range(20)]
        return {"ok": True, "evidence": rows}
    out = apply_ke_document_order(_accepted([_ke("R1", 51), _ke("R2", 3)]), fetch, ["q1", "q2"])
    exp = out["procedural_expansion"]
    ordinals = [x["metadata"]["ordinal"] for x in out["generation_evidence"]]
    assert calls == [(["q1", "q2"], URI, 12)]
    assert exp["adapter"] == "henkia_ke_document_filter" and exp["document_search"]["fetched"]
    assert len(ordinals) == EXPANDED_CHUNK_LIMIT and ordinals == sorted(ordinals)
    assert ordinals.count(51) == 1 and ordinals.count(3) == 1 and 2 in ordinals
    assert [x["id"] for x in out["generation_evidence"]] == [f"R{i}" for i in range(1, EXPANDED_CHUNK_LIMIT + 1)]


def test_failed_document_search_keeps_accepted_chunks():
    def broken(query, source, k):
        raise TimeoutError("ke down")
    out = apply_ke_document_order(_accepted([_ke("R1", 8), _ke("R2", 3)]), broken, ["q"])
    assert [x["metadata"]["ordinal"] for x in out["generation_evidence"]] == [3, 8]
    assert out["procedural_expansion"]["ok"] and out["procedural_expansion"]["adapter"] == "henkia_ke_ordinal_order"
    assert out["procedural_expansion"]["document_search"]["reason"] == "fetch_error"


def test_fetcher_only_searches_bases_seen_in_the_turn():
    assert ke_document_fetcher({}, [{"source": URI, "metadata": {"provider": "local"}}]) is None
    fetch = ke_document_fetcher({}, [_ke("R1", 1)])
    assert fetch("q", "sharepoint://other", 5)["errors"] == ["unknown_document"]


def test_ke_route_exposes_its_fetcher_only_while_it_runs():
    seen = {}
    result = _result(topic_relation="new_topic", user_act="new_request")
    for row in result["knowledge_comparison"]["normalized_result"]["results"]:
        row["knowledge_base_id"] = "kb1"

    def runner(res, message, config, session, budget, store):
        seen["fetcher"] = KE_SAME_DOCUMENT_FETCHER.get()
        res = deepcopy(res)
        res["answer"] = {"text": "x [R1]", "mode": "documented_answer"}
        return res, {"skipped": True}, {"skipped": True}
    execute(result, "Requisitos de HP SDS", {}, {}, None, {"answer_context": {}}, runner)
    assert callable(seen["fetcher"])
    assert KE_SAME_DOCUMENT_FETCHER.get() is None


def test_route_summary_keeps_document_reads_after_compaction():
    from app.agent_core_v2_clean.runtime_memory import _compact_ke_shadow
    from app.knowledge_gateway.agent_core_shadow import _route_summary

    route_result = {"answer": {"text": "x", "mode": "documented_answer"},
                    "documented_answer": {"validation": {"exhaustive_evidence_expansion": {
                        "activated": True, "reason": "same_document_diagnostic_fragments_added",
                        "fetched_count": 8, "added_count": 5, "selected_document": "doc"}}}}
    retrieval = {"procedural_expansion": {"document_search": {"fetched": True, "fetched_count": 12, "added_count": 2}}}
    block = _compact_ke_shadow({"ke_route": _route_summary(route_result, retrieval)})
    reads = block["ke_route"]["document_reads"]
    assert reads["procedure"]["added_count"] == 2
    assert reads["exhaustive_list"] == {"activated": True, "reason": "same_document_diagnostic_fragments_added",
                                        "fetched_count": 8, "added_count": 5}
    assert "documented_answer" not in block["ke_route"]
