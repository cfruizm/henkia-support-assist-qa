from __future__ import annotations

from typing import Any


def should_complete_conceptual_goal(result: dict[str, Any]) -> bool:
    understanding = result.get("understanding") or {}
    answer = result.get("answer") or {}
    if understanding.get("intent") != "conceptual":
        return False
    if understanding.get("needs_clarification"):
        return False
    if answer.get("partial") or str(answer.get("finish_reason") or "").casefold() in {"length", "max_tokens"}:
        return False
    return bool(str(answer.get("text") or "").strip())


def complete_conceptual_goal(result: dict[str, Any]) -> dict[str, Any]:
    if not should_complete_conceptual_goal(result):
        return result
    state = result.get("state_after") or result.get("state")
    if isinstance(state, dict):
        goal = state.get("pending_goal") or {}
        if isinstance(goal, dict):
            goal["status"] = "complete"
            goal["missing_detail"] = None
    understanding = result.get("understanding")
    if isinstance(understanding, dict):
        understanding["goal_complete"] = True
    result["conceptual_completion"] = {"applied": True, "reason": "complete_non_partial_conceptual_answer"}
    return result
