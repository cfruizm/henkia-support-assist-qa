"""Offline checks: Henkia KE search across several knowledge bases.

The KE searches one base per request; one API key can read several bases.
HENKIA_KE_KB_IDS lists them; results are merged by score. requests.post is
replaced by a fake, so no network call is made.
"""

import app.knowledge_gateway.henkia_knowledge_engine as ke

BASE = {
    "KNOWLEDGE_COMPARE_ENABLED": True,
    "KNOWLEDGE_COMPARE_PROVIDER": "henkia_ke",
    "HENKIA_KE_BASE_URL": "https://ke.example.test/v1",
    "HENKIA_KE_API_KEY": "test-key",
    "HENKIA_KE_MAX_RESULTS": 3,
}


class _Response:
    def __init__(self, status, payload):
        self.status_code = status
        self.ok = 200 <= status < 300
        self._payload = payload
        self.text = ""

    def json(self):
        return self._payload


def _row(name, score):
    return {"file_id": name, "filename": name, "score": score,
            "attributes": {"document_uri": name, "chunk_id": f"{name}-c"},
            "content": [{"type": "text", "text": f"contenido de {name}"}]}


def _fake_post(responses, calls):
    def post(url, headers=None, json=None, timeout=None):
        kb = url.split("/vector_stores/")[1].split("/")[0]
        calls.append(kb)
        status, payload = responses[kb]
        return _Response(status, payload)
    return post


def _with_fake(responses, config):
    calls = []
    original = ke.requests.post
    ke.requests.post = _fake_post(responses, calls)
    try:
        return ke.search("¿pregunta?", config), calls
    finally:
        ke.requests.post = original


def test_kb_ids_accepts_list_string_and_legacy_single_id():
    assert ke._kb_ids({"HENKIA_KE_KB_IDS": ["a", "b", "a"]}) == ["a", "b"]
    assert ke._kb_ids({"HENKIA_KE_KB_IDS": "a, b; c"}) == ["a", "b", "c"]
    assert ke._kb_ids({"HENKIA_KE_KB_ID": "solo"}) == ["solo"]
    assert ke._kb_ids({"HENKIA_KE_KB_IDS": "", "HENKIA_KE_KB_ID": "solo"}) == ["solo"]


def test_two_bases_are_merged_by_score_with_provenance():
    responses = {
        "kb1": (200, {"data": [_row("impresion-a", 0.91), _row("impresion-b", 0.40)]}),
        "kb2": (200, {"data": [_row("simp-a", 0.75), _row("simp-b", 0.30)]}),
    }
    result, calls = _with_fake(responses, {**BASE, "HENKIA_KE_KB_IDS": ["kb1", "kb2"]})
    assert sorted(calls) == ["kb1", "kb2"]
    assert result.http_status == 200 and not result.error
    assert [r.source_name for r in result.results] == ["impresion-a", "simp-a", "impresion-b"]
    assert [r.knowledge_base_id for r in result.results] == ["kb1", "kb2", "kb1"]
    assert {b["knowledge_base_id"] for b in result.request_diagnostic["knowledge_bases"]} == {"kb1", "kb2"}


def test_one_failing_base_does_not_discard_the_other():
    responses = {
        "kb1": (200, {"data": [_row("impresion-a", 0.91)]}),
        "kb2": (503, {"error": {"type": "server_error"}}),
    }
    result, _ = _with_fake(responses, {**BASE, "HENKIA_KE_KB_IDS": "kb1,kb2"})
    assert result.http_status == 200 and not result.error
    assert [r.source_name for r in result.results] == ["impresion-a"]
    assert result.request_diagnostic["partial_failure"] is True


def test_all_bases_failing_returns_an_error():
    responses = {"kb1": (503, {}), "kb2": (503, {})}
    result, _ = _with_fake(responses, {**BASE, "HENKIA_KE_KB_IDS": ["kb1", "kb2"]})
    assert result.error and result.http_status == 503


def test_single_base_keeps_previous_behavior():
    responses = {"solo": (200, {"data": [_row("impresion-a", 0.9)]})}
    result, calls = _with_fake(responses, {**BASE, "HENKIA_KE_KB_ID": "solo"})
    assert calls == ["solo"] and result.knowledge_base_id == "solo"
    assert result.results[0].knowledge_base_id == "solo"
