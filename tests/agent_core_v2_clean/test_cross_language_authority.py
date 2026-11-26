"""Offline checks: Spanish requests must be able to use English documentation.

Unified evidence authority compared request tokens literally, so a Spanish
"instalar" never matched English "installation" and correct vendor documents
were rejected as no_operationally_aligned_evidence. Synthetic, product-neutral
fixtures (no real product names).
"""

from app.agent_core_v2_clean.operation_bridge import present_terms, term_present
from app.agent_core_v2_clean.unified_evidence_authority import apply_unified_evidence_verdict


def _item(item_id, title, text, score=0.6):
    return {
        "id": item_id, "title": title, "source": f"/docs/{title}.pdf", "page": "3",
        "text": text, "semantic_fit": {"score": score},
        "metadata": {"title": title},
    }


def _retrieval(items):
    return {
        "ok": True, "count": len(items), "evidence": items, "generation_evidence": items,
        "diagnostic_evidence": items,
        "query": {"text": "q", "fields": {"topic_relation": "new_topic", "user_act": "new_request"}},
        "_answer_context": {},
    }


def _understanding(goal, intent="procedural", subject="Platform Alpha"):
    return {
        "user_act": "new_request", "intent": intent, "topic_relation": "new_topic",
        "domain_relevance": "in_scope", "current_goal": goal, "goal_updates": {"subject": subject},
        "canonical_subject": subject, "subject_origin": "current_message", "reference_relation": "none",
    }


INSTALL_DOC = [
    _item("R1", "Platform Alpha Administrator Guide",
          "Installation. Click Next to begin the installation of Platform Alpha. When all the components "
          "are installed, the Installation is complete message will display. Follow these steps."),
    _item("R2", "Platform Alpha Administrator Guide",
          "To install the Platform Alpha agent, run the setup wizard and follow each step on screen."),
]


def test_bridge_matches_spanish_operations_to_english_stems():
    available = {"installation", "configure", "disappearing", "released", "jobs", "steps"}
    assert term_present("instalar", available)
    assert term_present("configurar", available)
    assert term_present("desaparecen", available)
    assert term_present("liberarlos", available)
    assert term_present("trabajos", available)
    assert present_terms({"exportar", "integrar"}, available) == set()


def test_spanish_install_request_accepts_english_install_guide():
    message = "¿Cómo se instala Platform Alpha?"
    out = apply_unified_evidence_verdict(_retrieval(INSTALL_DOC), message, _understanding("Obtener los pasos para instalar Platform Alpha"))
    verdict = out["evidence_verdict"]
    assert verdict["accepted"] and verdict["status"] == "sufficient", verdict
    assert verdict["operation_alignment"]["aligned"]


def test_qualifier_is_not_a_required_dimension():
    message = "¿Cuál es el procedimiento aprobado para configurar Platform Alpha?"
    docs = [_item("R1", "Configure Platform Alpha", "To configure Platform Alpha, open the settings page and follow these steps to complete the configuration.")]
    out = apply_unified_evidence_verdict(_retrieval(docs), message, _understanding("Obtener el procedimiento aprobado para configurar Platform Alpha"))
    verdict = out["evidence_verdict"]
    assert "aprobado" not in verdict["operation_alignment"]["required_terms"]
    assert verdict["accepted"], verdict


def test_unrelated_operation_is_still_rejected():
    message = "¿Cómo integro Platform Alpha con un CRM externo?"
    out = apply_unified_evidence_verdict(_retrieval(INSTALL_DOC), message, _understanding("Integrar Platform Alpha con un CRM externo"))
    verdict = out["evidence_verdict"]
    assert not verdict["accepted"] and verdict["reason"] == "no_operationally_aligned_evidence", verdict
