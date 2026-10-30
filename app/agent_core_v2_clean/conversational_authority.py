from __future__ import annotations
from dataclasses import dataclass, asdict

_SUPPORTED_INTENTS = {
    "conceptual", "procedural", "troubleshooting", "requirements",
    "architecture", "warranty", "escalation", "cancel", "social",
}
_CONTINUATION_RELATIONS = {"same_topic", "return_to_previous"}

@dataclass(frozen=True)
class AuthorityTrace:
    original_topic_relation: str
    final_topic_relation: str
    original_domain_relevance: str
    final_domain_relevance: str
    topic_overridden: bool
    scope_overridden: bool
    reasons: list[str]
    def to_dict(self):
        return asdict(self)

def reconcile_understanding(understanding, memory):
    """Reconcile provider labels using conversation structure, never domain keywords.

    The provider's explicit new-topic decision is preserved. An out-of-scope label
    is overridden only for a continuation of an active in-scope support goal with
    a supported intent. Independent requests remain untouched.
    """
    original_relation = str(getattr(understanding, "topic_relation", "") or "")
    original_scope = str(getattr(understanding, "domain_relevance", "") or "")
    reasons: list[str] = []
    has_active_goal = bool(getattr(memory, "active_topic", None) or getattr(getattr(memory, "pending_goal", None), "summary", None))
    has_last_question = bool(getattr(memory, "last_assistant_question", None))

    if getattr(understanding, "user_act", None) == "request_elaboration":
        if not has_active_goal and not has_last_question:
            understanding.user_act = "new_request"
            understanding.topic_relation = "new_topic"
            reasons.append("orphan_elaboration_normalized_to_new_request")
        elif original_relation == "new_topic":
            understanding.user_act = "new_request"
            understanding.topic_relation = "new_topic"
            reasons.append("provider_new_topic_preserved")
        else:
            understanding.topic_relation = "same_topic"
            understanding.should_retrieve = True
            reasons.append("active_goal_elaboration_preserved")

    continuation = (
        has_active_goal
        and str(getattr(understanding, "topic_relation", "") or "") in _CONTINUATION_RELATIONS
        and str(getattr(understanding, "intent", "") or "") in _SUPPORTED_INTENTS
        and str(getattr(understanding, "user_act", "") or "") not in {"independent_question", "topic_change"}
    )
    if original_scope == "out_of_scope" and continuation:
        understanding.domain_relevance = "in_scope"
        reasons.append("continuation_of_active_in_scope_topic")

    return understanding, AuthorityTrace(
        original_topic_relation=original_relation,
        final_topic_relation=str(getattr(understanding, "topic_relation", "") or ""),
        original_domain_relevance=original_scope,
        final_domain_relevance=str(getattr(understanding, "domain_relevance", "") or ""),
        topic_overridden=original_relation != str(getattr(understanding, "topic_relation", "") or ""),
        scope_overridden=original_scope != str(getattr(understanding, "domain_relevance", "") or ""),
        reasons=reasons,
    )
