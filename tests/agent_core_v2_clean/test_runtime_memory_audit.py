"""Offline checks for runtime-memory compaction and audit archiving.

A turn evicted from the bounded runtime window must keep its diagnostic
blocks in the audit archive; otherwise exported campaigns silently lose
evidence (KE-03 lost agent_core_ke_shadow for turns older than the window).
"""

from app.agent_core_v2_clean.runtime_memory import (
    MAX_RETAINED_TURNS,
    MAX_SHADOW_ANSWER,
    compact_turn,
    enforce_runtime_memory_limits,
)

# Diagnostic blocks that exported campaigns rely on.
AUDITED_BLOCKS = (
    "understanding",
    "decision",
    "answer",
    "retrieval",
    "provider_trace",
    "topic_boundary",
    "qa_shadow",
    "knowledge_comparison",
    "agent_core_ke_shadow",
)


def _ke_shadow(answer_text="respuesta sombra"):
    return {
        "schema_version": 1,
        "enabled": True,
        "executed": True,
        "observational_only": True,
        "affects_publication": False,
        "production_changed": False,
        "ke_route": {
            "retrieval_provider": "henkia_ke",
            "evidence_status": "sufficient",
            "evidence_accepted": True,
            "answer_mode": "documented_answer",
            "documented_answer": {"semantic_fit": {"ranked_ids": ["KE1"] * 50}},
            "answer": {"text": answer_text, "mode": "documented_answer"},
        },
        "published_route": {"retrieval_provider": "local_chroma", "answer_mode": "documented_answer"},
        "comparison": {"answer_mode_agreement": True, "publication_unchanged": True},
        "traces": {"conceptual": {"large": "x" * 5000}, "procedural": {"large": "y" * 5000}},
    }


def _turn(index):
    return {
        "input": f"pregunta {index}",
        "understanding": {"intent": "requirements"},
        "decision": {"action": "defer_to_retrieval"},
        "answer": {"text": f"respuesta {index}", "mode": "documented_answer"},
        "retrieval": {"evidence_verdict": {"status": "sufficient", "accepted": True}},
        "provider_trace": {"understanding": {"ok": True}},
        "topic_boundary": {"relation": "new_topic"},
        "qa_shadow": {"status": "observed"},
        "knowledge_comparison": {"enabled": True},
        "agent_core_ke_shadow": _ke_shadow(f"sombra {index}"),
    }


def _run_campaign(turn_count):
    store = {"turns": [], "messages": []}
    for index in range(1, turn_count + 1):
        store["turns"].append(compact_turn(_turn(index)))
        enforce_runtime_memory_limits(store)
    return store


def test_evicted_turns_keep_every_audited_block():
    store = _run_campaign(MAX_RETAINED_TURNS + 7)
    archived = store["audit_turns"]
    assert len(archived) == 7
    for row in archived:
        missing = [block for block in AUDITED_BLOCKS if block not in row]
        assert not missing, f"{row['input']} lost {missing}"


def test_ke_shadow_survives_archiving_with_comparison_fields():
    store = _run_campaign(MAX_RETAINED_TURNS + 1)
    shadow = store["audit_turns"][0]["agent_core_ke_shadow"]
    assert shadow["executed"] is True
    assert shadow["affects_publication"] is False
    assert shadow["production_changed"] is False
    assert shadow["ke_route"]["evidence_accepted"] is True
    assert shadow["ke_route"]["answer"]["text"] == "sombra 1"
    assert shadow["comparison"]["answer_mode_agreement"] is True


def test_ke_shadow_compaction_drops_traces_and_bounds_answer():
    long_text = "a" * (MAX_SHADOW_ANSWER + 500)
    turn = compact_turn({"agent_core_ke_shadow": _ke_shadow(long_text)})
    shadow = turn["agent_core_ke_shadow"]
    assert "traces" not in shadow
    assert "documented_answer" not in shadow["ke_route"]
    assert len(shadow["ke_route"]["answer"]["text"]) == MAX_SHADOW_ANSWER
    assert shadow["ke_route"]["answer"]["text_truncated"] is True


def test_compaction_does_not_mutate_the_live_result():
    result = {"agent_core_ke_shadow": _ke_shadow()}
    compact_turn(result)
    assert "traces" in result["agent_core_ke_shadow"]
    assert "documented_answer" in result["agent_core_ke_shadow"]["ke_route"]
