from __future__ import annotations

"""Read-only semantic trace for the 3B.4.1 stable runtime.

The module observes completed turns. It never mutates memory, understanding,
retrieval, evidence selection, response planning, or the published answer.
"""

from copy import deepcopy
from typing import Any

TRACE_VERSION = "semantic_trace_shadow_v1"


def _dict(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return " ".join(value.split()).strip()
    return str(value).strip()


def _subject_from_details(details: dict) -> str | None:
    for key in ("product", "subject", "platform", "component", "device", "model", "manufacturer"):
        value = _text(details.get(key))
        if value:
            return value
    return None


def _evidence_ids(rows: Any) -> list[str]:
    return [
        _text(item.get("id"))
        for item in (rows or [])
        if isinstance(item, dict) and _text(item.get("id"))
    ]


def build_semantic_trace(result: dict, previous_turn: dict | None = None) -> dict:
    """Create an observational trace without changing the runtime result."""
    result = _dict(result)
    previous_turn = _dict(previous_turn)
    understanding = _dict(result.get("understanding"))
    before = _dict(result.get("state_before"))
    after = _dict(result.get("state_after"))
    before_goal = _dict(before.get("pending_goal"))
    after_goal = _dict(after.get("pending_goal"))
    current_details = _dict(understanding.get("goal_updates"))
    inherited_details = _dict(before_goal.get("known_details"))
    retrieval = _dict(result.get("retrieval"))
    query = _dict(retrieval.get("query"))
    query_fields = _dict(query.get("fields"))
    verdict = _dict(retrieval.get("evidence_verdict"))
    boundary = _dict(result.get("topic_boundary"))
    answer = _dict(result.get("answer"))
    previous_answer = _dict(previous_turn.get("answer"))

    current_subject = _subject_from_details(current_details)
    inherited_subject = _subject_from_details(inherited_details)
    query_subject = _text(query_fields.get("subject")) or _subject_from_details(_dict(query_fields.get("details")))

    observations = []
    declared_relation = _text(understanding.get("topic_relation"))
    boundary_relation = _text(boundary.get("relation"))
    if declared_relation and boundary_relation and declared_relation != boundary_relation:
        observations.append({
            "code": "relation_disagreement",
            "understanding": declared_relation,
            "topic_boundary": boundary_relation,
        })
    if current_subject and inherited_subject and current_subject.casefold() != inherited_subject.casefold():
        observations.append({
            "code": "subject_change_candidate",
            "current": current_subject,
            "inherited": inherited_subject,
        })
    if current_subject and query_subject and current_subject.casefold() != query_subject.casefold():
        observations.append({
            "code": "query_subject_disagreement",
            "current": current_subject,
            "query": query_subject,
        })
    pending_question = _text(before.get("last_assistant_question"))
    if not pending_question and _text(previous_answer.get("mode")) == "clarification":
        pending_question = _text(previous_answer.get("text"))
    if pending_question and len(_text(result.get("input")).split()) <= 8:
        observations.append({
            "code": "possible_clarification_response",
            "pending_question": pending_question,
        })

    return {
        "version": TRACE_VERSION,
        "mode": "shadow_read_only",
        "affects_runtime": False,
        "message": _text(result.get("input")),
        "understanding": {
            "user_act": _text(understanding.get("user_act")),
            "intent": _text(understanding.get("intent")),
            "topic_relation": declared_relation,
            "current_goal": _text(understanding.get("current_goal")),
            "needs_clarification": bool(understanding.get("needs_clarification")),
            "clarification_target": _text(understanding.get("clarification_target")) or None,
        },
        "subject_lineage": {
            "current_turn": current_subject,
            "inherited": inherited_subject,
            "retrieval_query": query_subject or None,
        },
        "topic": {
            "active_before": _text(before.get("active_topic")) or None,
            "active_after": _text(after.get("active_topic")) or None,
            "goal_before": _text(before_goal.get("summary")) or None,
            "goal_after": _text(after_goal.get("summary")) or None,
            "boundary_relation": boundary_relation or None,
            "boundary_reason": _text(boundary.get("reason")) or None,
        },
        "clarification": {
            "pending_before": pending_question or None,
            "short_reply_candidate": bool(pending_question and len(_text(result.get("input")).split()) <= 8),
        },
        "retrieval": {
            "query_text": _text(query.get("text")),
            "diagnostic_ids": _evidence_ids(retrieval.get("diagnostic_evidence") or retrieval.get("evidence")),
            "generation_ids": _evidence_ids(retrieval.get("generation_evidence") or retrieval.get("evidence")),
            "verdict_status": _text(verdict.get("status")) or None,
            "verdict_reason": _text(verdict.get("reason")) or None,
        },
        "publication": {
            "answer_mode": _text(answer.get("mode")),
            "finish_reason": _text(answer.get("finish_reason")) or None,
            "published": bool(_text(answer.get("text"))),
        },
        "observations": observations,
    }


def attach_semantic_trace(result: dict, previous_turn: dict | None = None) -> dict:
    """Attach trace as telemetry only. Return the same result object."""
    if isinstance(result, dict):
        result["semantic_trace_shadow"] = build_semantic_trace(
            deepcopy(result), deepcopy(previous_turn or {})
        )
    return result
