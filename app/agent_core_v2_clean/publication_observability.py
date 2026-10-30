from __future__ import annotations
from copy import deepcopy

_TRUNCATED = {"length", "max_tokens"}


def build_publication_ledger(result):
    """Describe what was generated and what reached the user without changing behavior."""
    result = result or {}
    answer = deepcopy(result.get("answer") or {})
    context = deepcopy(result.get("answer_context") or {})
    provider_trace = deepcopy(result.get("provider_trace") or {})
    finish_reason = str(answer.get("finish_reason") or context.get("finish_reason") or "").casefold() or None
    text = str(answer.get("text") or "")
    partial = bool(answer.get("partial") or context.get("partial"))
    truncated = finish_reason in _TRUNCATED
    blocked = bool(result.get("blocked"))
    error = deepcopy(result.get("error") or {}) or None
    return {
        "schema_version": 1,
        "observational_only": True,
        "answer_mode": answer.get("mode"),
        "knowledge_mode": answer.get("knowledge_mode"),
        "finish_reason": finish_reason,
        "provider_reported_truncation": truncated,
        "partial_flag": partial,
        "user_visible_text_present": bool(text.strip()),
        "user_visible_character_count": len(text),
        "blocked": blocked,
        "error": error,
        "response_provider_trace_present": bool(provider_trace.get("response")),
        "recovery_observed": bool(result.get("procedural_recovery") or result.get("documented_fallback") or result.get("budget_status")),
        "publication_outcome": (
            "blocked" if blocked else
            "truncated_visible" if truncated and text.strip() else
            "truncated_empty" if truncated else
            "published" if text.strip() else "empty"
        ),
    }
