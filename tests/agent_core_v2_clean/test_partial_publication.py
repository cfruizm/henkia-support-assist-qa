"""Offline checks: complete answers must not be labeled as partial coverage.

QA showed complete answers (e.g. a full ports table) published with a
"Cobertura parcial" banner because a requirements answer had to cite at least
3 pages even when the request was narrow. Stub LLM, product-neutral fixtures.
"""

import app.agent_core_v2_clean.documented_answer as _documented
from app.agent_core_v2_clean.documented_answer import DocumentedAnswerComposer
from app.llm_gateway.models import LLMResult

# Offline tests must never open the real vectorstore (local chromadb rewrites
# chroma.sqlite3): the same-document fetcher is an empty stub in this module.
_documented._same_document_fetcher = lambda *args: {"evidence": []}


class _Stub:
    def __init__(self, text):
        self.text = text

    def complete(self, request):
        return LLMResult(True, self.text, "stub", "stub", request.purpose, 1.0, {"total_tokens": 10}, "stop")


def _evidence(pages_and_text):
    return [
        {"id": f"R{i}", "title": "Platform Alpha System Requirements", "source": "/docs/requirements.pdf",
         "page": page, "text": text, "metadata": {"title": "Platform Alpha System Requirements", "page_label": page}}
        for i, (page, text) in enumerate(pages_and_text, 1)
    ]


EVIDENCE = _evidence([
    ("3", "General system requirements for Platform Alpha include an operating system and network access."),
    ("5", "Port 443 TCP outbound is required for activation and licensing services."),
    ("6", "Port 5222 TCP outbound is required for secure XMPP messaging to cloud services."),
])


def _retrieval(evidence):
    return {
        "ok": True, "evidence": evidence, "generation_evidence": evidence,
        "evidence_verdict": {"status": "sufficient", "accepted": True, "mode": "documented", "selected_evidence": evidence},
        "query": {"fields": {}}, "_answer_context": {},
    }


UNDERSTANDING = {
    "intent": "requirements", "user_act": "follow_up", "topic_relation": "return_to_previous",
    "canonical_subject": "Platform Alpha", "current_goal": "Conocer los puertos de Platform Alpha", "goal_updates": {},
}


def test_narrow_requirements_answer_citing_half_the_pages_is_complete():
    composer = DocumentedAnswerComposer(_Stub(
        "Los puertos requeridos son 443 TCP para activación y licencias [R2] "
        "y 5222 TCP para mensajería segura XMPP [R3]."
    ), 760)
    answer = composer.compose("Volviendo a Platform Alpha, ¿cuáles eran los puertos?", UNDERSTANDING, _retrieval(EVIDENCE))
    assert answer.mode == "documented_answer", (answer.mode, composer.validation)
    assert "Cobertura documental parcial" not in answer.text
    assert composer.validation["required_page_coverage"] == 2


def test_answer_citing_a_single_page_of_three_is_still_partial():
    composer = DocumentedAnswerComposer(_Stub("El puerto 443 TCP es necesario para activación [R2]."), 760)
    answer = composer.compose("¿Cuáles son los requisitos de Platform Alpha?", UNDERSTANDING, _retrieval(EVIDENCE))
    assert answer.mode == "documented_answer_partial", (answer.mode, composer.validation)


def test_exhaustive_list_request_fetches_same_document_fragments():
    from app.agent_core_v2_clean.documented_fact_coverage import augment_exhaustive_numeric_evidence

    source = "/docs/requirements.pdf"
    base = [{"id": "R1", "title": "Req", "source": source, "page": "5", "text": "Port legend: internet, intranet, local, remote."}]
    retrieval = {"evidence": base, "generation_evidence": base, "diagnostic_evidence": base,
                 "evidence_verdict": {"selected_evidence": base}}
    calls = []

    def fetcher(query, target, k):
        calls.append(target)
        return {"evidence": [
            {"text": "443 TCP outbound activation; 5222 TCP XMPP messaging.", "title": "Req", "source": source,
             "metadata": {"page_label": "6"}},
            {"text": "Unrelated fragment from another document.", "title": "Other", "source": "/docs/other.pdf",
             "metadata": {"page_label": "1"}},
        ]}

    out, diagnostic = augment_exhaustive_numeric_evidence(retrieval, "¿Cuáles eran los puertos?", fetcher)
    texts = [row["text"] for row in out["generation_evidence"]]
    assert calls == [source]
    assert diagnostic["activated"] and diagnostic["fetched_count"] == 1
    assert any("5222" in text for text in texts)
    assert not any("another document" in text for text in texts)


def test_shadow_ke_route_never_fetches_local_documents():
    import app.agent_core_v2_clean.documented_answer as documented

    called = []
    original = documented._same_document_fetcher
    documented._same_document_fetcher = lambda *args: called.append(args) or {"evidence": []}
    try:
        evidence = _evidence([("5", "Port legend only.")])
        retrieval = {**_retrieval(evidence), "provider": "henkia_ke"}
        composer = DocumentedAnswerComposer(_Stub("La leyenda de puertos está documentada [R1]."), 760)
        composer.compose("¿Cuáles eran los puertos?", UNDERSTANDING, retrieval)
    finally:
        documented._same_document_fetcher = original
    assert called == []
