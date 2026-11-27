"""Offline checks for scripts/ke_web_sync.py (option C). No network."""

import json
import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "scripts"))
import ke_web_sync as sync  # noqa: E402

BASE = "4c466401-c373-4f55-b74b-aa00cfd17850"


def test_document_name_is_stable_and_managed():
    url = "https://www.papercut.com/help/manuals/ng-mf/applicationserver/topics/find-me-printing/"
    name = sync.document_name(url)
    assert name == sync.document_name(url) and name.endswith(".md") and name.startswith(sync.MANAGED_PREFIX)
    assert name != sync.document_name(url + "x")


class _FakeClient:
    calls = []

    def __init__(self, key):
        _FakeClient.calls = []

    def tool(self, name, arguments):
        assert name in sync.ALLOWED_TOOLS
        _FakeClient.calls.append((name, arguments))
        if name == "listar_documentos":
            return True, json.dumps({"documentos": [{"name": "www-papercut-com-old-1.md"}, {"name": "Administrator Guide.pdf"},
                                                    {"name": "www-papercut-com-keep-2.md"}]})
        return True, "ok"

    def close(self):
        pass


def _prepared(tmp):
    out = pathlib.Path(tmp)
    (out / "documents").mkdir()
    docs = []
    for name in ("www-papercut-com-keep-2.md", "www-papercut-com-new-3.md"):
        (out / "documents" / name).write_text(f"# {name}\n\ntexto", encoding="utf-8")
        docs.append({"name": name, "metadata": {"reference_url": "https://www.papercut.com/x", "content_hash": name}})
    (out / "manifest.json").write_text(json.dumps({"documents_manifest": docs}), encoding="utf-8")
    (out / "upload_state.json").write_text(json.dumps({"www-papercut-com-keep-2.md": "www-papercut-com-keep-2.md"}))
    return out


def test_upload_skips_unchanged_prunes_only_own_pages_and_ingests():
    original_client, original_key = sync.McpClient, sync._write_key
    sync.McpClient, sync._write_key = _FakeClient, lambda: "k"
    try:
        with tempfile.TemporaryDirectory() as tmp:
            out = _prepared(tmp)
            sync.main(["--upload", "--base", BASE, "--out", str(out), "--prune", "--ingest"])
            state = json.loads((out / "upload_state.json").read_text())
    finally:
        sync.McpClient, sync._write_key = original_client, original_key
    names = [(n, a.get("nombre")) for n, a in _FakeClient.calls]
    assert ("subir_documento", "www-papercut-com-new-3.md") in names
    assert ("subir_documento", "www-papercut-com-keep-2.md") not in names
    assert ("borrar_documento", "www-papercut-com-old-1.md") in names
    assert not any(n == "borrar_documento" and a != "www-papercut-com-old-1.md" for n, a in names)
    assert names[-1][0] == "ingerir_base"
    upload = next(a for n, a in _FakeClient.calls if n == "subir_documento")
    assert upload["base"] == BASE and upload["codificacion"] == "texto" and upload["metadatos"]["reference_url"]
    assert "www-papercut-com-new-3.md" in state


def test_upload_requires_a_base_uuid():
    try:
        sync.main(["--upload", "--base", "Impresion"])
    except SystemExit as exc:
        assert "uuid" in str(exc)
    else:
        raise AssertionError("expected SystemExit")


def test_ke_rows_use_the_document_title_and_requests_carry_english_terms():
    from app.knowledge_gateway.agent_core_shadow import ke_evidence_rows
    from app.knowledge_gateway.henkia_knowledge_engine import normalize
    from app.agent_core_v2_clean.semantic_fit import evaluate_item

    payload = {"data": [{"filename": "www-papercut-com-kb-setupfindme-afbe90ac.md", "score": 0.8,
                         "attributes": {"document_title": "Set up Find-Me printing with PaperCut MF",
                                        "reference_url": "https://www.papercut.com/kb/Main/SetupFindMePrintingUsingPaperCutMF/",
                                        "document_uri": "tenants/x/kb/y/www-papercut-com-kb-setupfindme-afbe90ac.md",
                                        "chunk_id": "c1", "ordinal": 3},
                         "content": [{"type": "text", "text": "Configure the Find-Me queue in PaperCut MF and set up the virtual queue."}]}]}
    rows = ke_evidence_rows(normalize(payload, "q", "kb1", 1.0, 200).to_dict())
    assert rows[0]["title"] == "Set up Find-Me printing with PaperCut MF"
    assert rows[0]["url"].startswith("https://www.papercut.com/")

    fields = {"goal": "Explicar cómo configurar la impresión Find-Me en PaperCut", "intent": "procedural",
              "current_message": "¿Cómo configuro Find-Me en PaperCut?", "topic_relation": "new_topic",
              "details": {"subject": "PaperCut", "operation": "configurar", "focus": "impresión Find-Me"}}
    without = evaluate_item(rows[0], "q", fields, canonical=True)["score"]
    with_en = evaluate_item(rows[0], "q", {**fields, "english_terms": ["configure", "set up", "printing", "queue"]}, canonical=True)["score"]
    assert with_en > without, (without, with_en)


def test_english_vendor_page_is_accepted_without_goal_framing_words():
    """QA: Find-Me pages were rejected on goal words ("pasos", "funcion") no page states."""
    from app.knowledge_gateway.agent_core_shadow import build_shadow_retrieval

    name = "www-papercut-com-kb-main-setupfindmeprintingusingpapercutmf-afbe90ac.md"
    texts = [(0, "# How to set up Find-Me printing with PaperCut MF\n\nThis article demonstrates how to set up Find-Me Printing with PaperCut MF."),
             (3, "## 3. Configure the Find-Me queue in PaperCut MF\n\nThis section walks you through logging into PaperCut MF to configure Find-Me Printing."),
             (9, "3. Check the Enable find me printing support checkbox.\n4. Select This device (single queue).\n5. Select the destination queue for the device.")]
    rows = [{"source_name": name, "content": text, "score": 0.75, "ordinal": ordinal, "chunk_id": f"c{ordinal}",
             "document_uri": f"tenants/x/kb/y/{name}", "reference_url": "https://www.papercut.com/kb/Main/SetupFindMePrintingUsingPaperCutMF/",
             "knowledge_base_id": "kb1"} for ordinal, text in texts]
    goal = "Obtener los pasos para configurar la función Find-Me en PaperCut"
    details = {"subject": "PaperCut Find-Me", "product": "PaperCut", "operation": "configurar", "component": "Find-Me"}
    u = {"user_act": "new_request", "intent": "procedural", "topic_relation": "new_topic", "current_goal": goal,
         "goal_updates": details, "canonical_subject": "PaperCut Find-Me", "reference_relation": "none",
         "term_translations": [{"term": "configuro", "english": "configure"}]}
    message = "¿Cómo configuro Find-Me en PaperCut?"
    fields = {"goal": goal, "intent": "procedural", "details": details, "current_message": message, "english_terms": ["configure"],
              "topic_relation": "new_topic", "user_act": "new_request"}
    result = {"understanding": u, "topic_boundary": {"relation": "new_topic"}, "retrieval": {"query": {"text": message, "fields": fields}},
              "knowledge_comparison": {"query": message, "normalized_result": {"http_status": 200, "error": None, "results": rows}}}
    verdict = build_shadow_retrieval(result, message, {}, {})["evidence_verdict"]
    assert verdict["status"] == "sufficient", verdict.get("reason")
    assert "pasos" not in verdict["operation_alignment"]["required_terms"]
