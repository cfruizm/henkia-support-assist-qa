from __future__ import annotations


def compact_diagnostic_progression(memory):
    case = getattr(memory, "support_case", None)
    observations = list(getattr(case, "observations", None) or [])
    symptoms = list(getattr(case, "symptoms", None) or [])
    attempts = list(getattr(case, "attempts", None) or [])
    completed = []
    for item in attempts[-6:]:
        completed.append({
            "action": str(item.get("action") or "").strip(),
            "result": str(item.get("result") or "").strip() or None,
            "outcome": str(item.get("outcome") or "unknown").strip(),
        })
    return {
        "active": str(getattr(case, "status", "") or "") == "diagnosing",
        "confirmed_symptoms": symptoms[-5:],
        "confirmed_observations": observations[-6:],
        "attempted_actions": completed,
        "last_question": getattr(memory, "last_assistant_question", None),
        "response_policy": {
            "do_not_request_confirmed_information": True,
            "do_not_repeat_completed_action_without_reason": True,
            "advance_with_one_discriminating_check": True,
            "use_attempt_results_to_narrow_hypotheses": True,
        },
    }
