from __future__ import annotations


def fallback_matches_current_goal(result, retrieval):
    boundary = (result or {}).get("topic_boundary") or {}
    evidence = list((retrieval or {}).get("generation_evidence") or (retrieval or {}).get("evidence") or [])
    carried = any(bool(item.get("carried_from_previous_answer")) for item in evidence)
    previous_used = bool(((retrieval or {}).get("semantic_fit") or {}).get("previous_answer_sources_used"))
    allowed = not (boundary.get("relation") == "new_topic" and (carried or previous_used))
    result["fallback_authority"] = {
        "allowed": allowed,
        "reason": "current_goal_evidence" if allowed else "evidence_from_previous_goal",
        "topic_relation": boundary.get("relation"),
        "carried_evidence_present": carried,
        "previous_answer_sources_used": previous_used,
    }
    return allowed
