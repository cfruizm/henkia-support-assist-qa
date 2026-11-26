"""Offline checks for KE-05.3: full KE document for procedures (no network)."""

from copy import deepcopy

import app.knowledge_gateway.henkia_knowledge_engine as ke
from app.knowledge_gateway import ke_full_document as full
from app.knowledge_gateway.agent_core_shadow import build_shadow_retrieval
from tests.agent_core_v2_clean.test_ke_document_search import URI, _fake_mcp
from tests.agent_core_v2_clean.test_ke_multi_base import BASE

DOC = "\n\n".join([
    "INSTRUCTIVO USO DASHBOARD ALPHA. Alcance del documento y responsables del tablero de operación.",
    "Historial de versiones y control de cambios del documento corporativo.",
    "ACCESO. Acceda mediante el enlace web seguro enviado a su correo. Si es su primera vez, registre su correo corporativo e ingrese el código de acceso.",
    "Sección de consumibles: color y tamaño de los indicadores de tóner.",
    "Glosario de términos generales del área de operaciones.",
    "Consejos generales: use los filtros y exporte los datos a Excel.",
])


def _ke(item_id, ordinal):
    return {"id": item_id, "title": "IN0504.pdf", "source": URI, "url": "", "page": "", "text": f"Fragmento {ordinal}",
            "metadata": {"provider": "henkia_ke", "ordinal": ordinal, "chunk_id": f"c{ordinal}",
                         "knowledge_base_id": "kb2", "source_access": "internal_sharepoint"}}


def _accepted():
    rows = [_ke("R1", 8), _ke("R2", 3)]
    return {"generation_evidence": rows, "evidence": rows,
            "evidence_verdict": {"status": "sufficient", "selected_evidence": rows},
            "procedural_expansion": {"ok": True}}


def test_sections_keep_order_and_size():
    sections = full.split_sections(DOC, size=160)
    assert sections[0].startswith("INSTRUCTIVO") and sections[-1].startswith("Consejos")
    assert all(len(s) <= 160 for s in sections)
    long_text = ("Paso de configuración del tablero. " * 120).strip()
    assert all(len(s) <= full.SECTION_CHARS for s in full.split_sections(long_text))


def test_selection_keeps_scope_and_closing_plus_matching_sections():
    sections = DOC.split("\n\n")
    chosen = full.select_sections(sections, "¿Cómo accedo al dashboard por primera vez con el código de acceso?")
    access = next(i for i, s in enumerate(sections) if s.startswith("ACCESO"))
    glossary = next(i for i, s in enumerate(sections) if s.startswith("Glosario"))
    assert chosen[0] == 0 and chosen[-1] == len(sections) - 1
    assert access in chosen and glossary not in chosen and chosen == sorted(chosen)
    assert full.select_sections(sections, "impresora láser térmica") == []


def test_full_document_replaces_chunks_caches_text_and_keeps_no_text_in_trace():
    calls = []

    def reader(kb_id, uri):
        calls.append((kb_id, uri))
        return {"ok": True, "text": DOC, "latency_ms": 5000.0, "schema_cached": True}
    store = {}
    retrieval = _accepted()
    trace = full.apply_full_document(retrieval, reader, store, "¿Cómo accedo con el código de acceso?")
    assert trace["used"] and not trace["cached"] and calls == [("kb2", URI)]
    rows = retrieval["generation_evidence"]
    assert all(r["origin"] == "ke_full_document" and r["metadata"]["provider"] == "henkia_ke" for r in rows)
    assert all(r["metadata"]["source_access"] == "internal_sharepoint" for r in rows)
    assert [r["id"] for r in rows] == [f"R{i}" for i in range(1, len(rows) + 1)]
    assert any("código de acceso" in r["text"] for r in rows)
    assert "ACCESO" not in str(trace)
    again = full.apply_full_document(_accepted(), reader, store, "¿Cómo accedo con el código de acceso?")
    assert again["used"] and again["cached"] and len(calls) == 1


def test_read_failure_keeps_the_chunks():
    retrieval = _accepted()
    trace = full.apply_full_document(retrieval, lambda kb, uri: {"ok": False, "error_code": "read_timeout"}, {}, "acceso")
    assert not trace["used"] and trace["error_code"] == "read_timeout"
    assert [r["text"] for r in retrieval["generation_evidence"]] == ["Fragmento 8", "Fragmento 3"]


def test_text_cache_is_bounded():
    store = {}
    for i in range(5):
        full._cache_text(store, f"uri{i}", "x")
    assert list(store[full.TEXT_CACHE_KEY]) == ["uri2", "uri3", "uri4"]


def test_read_full_document_uses_single_call_once_schema_is_known():
    sent = []
    original = ke.requests.post
    ke.requests.post = _fake_mcp(sent, DOC)
    ke._MCP_SCHEMAS.clear()
    config = {**BASE, "HENKIA_KE_KB_IDS": "kb2"}
    try:
        first = ke.read_full_document(config, "kb2", URI)
        sent.clear()
        second = ke.read_full_document(config, "kb2", URI)
    finally:
        ke.requests.post = original
        ke._MCP_SCHEMAS.clear()
    assert first["ok"] and not first["schema_cached"] and first["text"] == DOC
    assert second["ok"] and second["schema_cached"]
    assert [x["method"] for x in sent] == ["tools/call"]


SIMP_ROWS = [
    {"source_name": "IN0504.pdf", "document_uri": URI, "file_id": URI, "score": 0.67, "ordinal": 8, "chunk_id": "c8",
     "knowledge_base_id": "kb2",
     "content": "INSTRUCTIVO USO DASHBOARD ALPHA. ACCESO: acceda al dashboard mediante el enlace seguro enviado a su correo. "
                "Para acceder por primera vez registre su correo e ingrese el código de acceso al dashboard."},
    {"source_name": "IN0504.pdf", "document_uri": URI, "file_id": URI, "score": 0.63, "ordinal": 3, "chunk_id": "c3",
     "knowledge_base_id": "kb2",
     "content": "INSTRUCTIVO USO DASHBOARD ALPHA. El dashboard permite acceder a indicadores; para acceder use su correo corporativo."},
]


def _simp_result(local_mode, documented):
    message = "¿Cómo accedo al dashboard de Alpha?"
    goal = "Acceder al dashboard de Alpha"
    details = {"subject": "Alpha", "component": "dashboard", "operation": "acceder"}
    u = {"user_act": "new_request", "intent": "procedural", "topic_relation": "new_topic", "domain_relevance": "in_scope",
         "current_goal": goal, "goal_updates": details, "canonical_subject": "Alpha", "subject_origin": "current_message",
         "reference_relation": "none"}
    query = {"text": f"{message}. {goal}", "fields": {"goal": goal, "intent": "procedural", "subject": "Alpha", "details": details,
             "current_message": message, "topic_relation": "new_topic", "user_act": "new_request"}}
    return message, {"understanding": u, "topic_boundary": {"relation": "new_topic"}, "retrieval": {"query": query},
                     "answer": {"text": "x", "mode": local_mode, "documented_evidence_used": documented},
                     "knowledge_comparison": {"query": message, "normalized_result": {"http_status": 200, "error": None, "results": deepcopy(SIMP_ROWS)}}}


def _run(local_mode, documented, enabled=True):
    reads, searches = [], []
    original_read, original_search = ke.read_full_document, ke.search_document
    ke.read_full_document = lambda config, kb, uri: reads.append(uri) or {"ok": True, "text": DOC, "latency_ms": 1.0}
    ke.search_document = lambda *a, **k: searches.append(a) or ke.SearchResult(provider="henkia_ke", query="q", http_status=200)
    config = {**BASE, "HENKIA_KE_KB_IDS": "kb2", **({"HENKIA_KE_FULL_DOCUMENT": "procedural"} if enabled else {})}
    message, result = _simp_result(local_mode, documented)
    try:
        retrieval = build_shadow_retrieval(result, message, {}, {}, config, {})
    finally:
        ke.read_full_document, ke.search_document = original_read, original_search
    return retrieval, reads, searches


def test_route_reads_full_document_when_ke_answer_will_be_published():
    retrieval, reads, searches = _run("controlled_internal_knowledge", False)
    assert retrieval["evidence_verdict"]["status"] in {"sufficient", "partial"}, retrieval["evidence_verdict"].get("reason")
    exp = retrieval["procedural_expansion"]
    assert reads == [URI] and searches == []
    assert exp["adapter"] == "henkia_ke_full_document" and exp["full_document"]["used"]
    assert all(r["origin"] == "ke_full_document" for r in retrieval["generation_evidence"])


def test_route_skips_full_document_when_local_is_documented_or_disabled():
    _, reads, searches = _run("procedural_documented_answer", True)
    assert reads == [] and len(searches) == 1
    _, reads, _ = _run("controlled_internal_knowledge", False, enabled=False)
    assert reads == []


class _BytesSse:
    """SSE response as the KE sends it: UTF-8 bytes, no charset in the header."""

    def __init__(self, payload):
        import json as _json
        self.status_code = 200
        self.ok = True
        self.headers = {"content-type": "text/event-stream"}
        self.content = ("event: message\ndata: " + _json.dumps(payload, ensure_ascii=False) + "\n\n").encode("utf-8")

    @property
    def text(self):  # what requests would return without charset
        return self.content.decode("iso-8859-1")


def test_sse_bytes_are_decoded_as_utf8_and_tool_json_is_unwrapped():
    import json as _json
    body = "A continuación, deberá realizar el registro.\n\nIngrese el código de acceso."
    wrapped = _json.dumps({"base": "kb-kb2", "uri": URI, "texto": body}, ensure_ascii=False, indent=1)

    def post(url, headers=None, json=None, timeout=None):
        if json["method"] == "initialize":
            return _BytesSse({"jsonrpc": "2.0", "id": 1, "result": {}})
        if json["method"] == "tools/list":
            return _BytesSse({"jsonrpc": "2.0", "id": 2, "result": {"tools": [
                {"name": "leer_documento", "inputSchema": {"properties": {"base": {}, "uri": {}, "max_caracteres": {}}}}]}})
        assert json["params"]["arguments"] == {"base": "kb2", "uri": URI, "max_caracteres": 30000}
        return _BytesSse({"jsonrpc": "2.0", "id": 3, "result": {"content": [{"type": "text", "text": wrapped}]}})
    original = ke.requests.post
    ke.requests.post = post
    ke._MCP_SCHEMAS.clear()
    try:
        out = ke.read_full_document({**BASE, "HENKIA_KE_KB_IDS": "kb2"}, "kb2", URI)
    finally:
        ke.requests.post = original
        ke._MCP_SCHEMAS.clear()
    assert out["ok"] and out["text"] == body
    assert "Ã" not in out["text"] and '"base"' not in out["text"]
    assert full.split_sections(out["text"], size=50) == ["A continuación, deberá realizar el registro.", "Ingrese el código de acceso."]
