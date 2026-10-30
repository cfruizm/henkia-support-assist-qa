from __future__ import annotations

import re
import unicodedata
from .topic_boundary import infer_topic_boundary

_TOKEN_RE = re.compile(r"[\wáéíóúüñ]+", re.I)
_GENERIC = {
    "ahora", "dame", "unicamente", "solamente", "resume", "explica", "explicame",
    "procedimiento", "documentado", "metodo", "metodos", "validar", "antes", "iniciar",
    "que", "debo", "para", "por", "del", "una", "uno", "the", "only", "method",
    "procedure", "before", "start", "update", "actualizar", "actualizacion",
}
_REFERENTIAL_ACTS = {
    "request_elaboration", "follow_up", "answer", "answer_to_question", "continue",
    "verification", "request_details",
}
_CONTINUATION_INTENTS = {"procedural", "requirements", "verification", "conceptual"}


def _semantic_text(value):
    if value is None:return ""
    if isinstance(value,str):return " ".join(value.split()).strip()
    if isinstance(value,(int,float,bool)):return str(value)
    if isinstance(value,list):return " ".join(x for x in (_semantic_text(item) for item in value) if x)
    if isinstance(value,dict):
        for key in ("summary","goal","current_goal","subject","operation","product","value","text","name"):
            text=_semantic_text(value.get(key))
            if text:return text
        return " ".join(x for x in (_semantic_text(item) for item in value.values()) if x)
    return " ".join(str(value).split()).strip()

def _norm(value):
    return unicodedata.normalize("NFKD", _semantic_text(value)).encode("ascii", "ignore").decode().casefold()


def _tokens(value):
    return {x for x in _TOKEN_RE.findall(_norm(value)) if len(x) > 2 and x not in _GENERIC}


def _semantic_continuation(understanding, memory):
    """Detect a focused follow-up within the same operational subject.

    This is intentionally domain-independent. It compares the previous active objective, the
    current structured goal and the current subject/operation. A change of method is treated as
    refinement when the underlying object/operation family remains shared.
    """
    previous = " ".join(
        value for value in (
            _semantic_text(getattr(memory, "active_topic", None)),
            _semantic_text(getattr(getattr(memory, "pending_goal", None), "summary", None)),
            _semantic_text((getattr(getattr(memory, "pending_goal", None), "known_details", {}) or {}).get("subject")),
            _semantic_text((getattr(getattr(memory, "pending_goal", None), "known_details", {}) or {}).get("operation")),
        ) if value
    )
    current_details = dict(getattr(understanding, "goal_updates", {}) or {})
    current = " ".join(
        value for value in (
            _semantic_text(getattr(understanding, "current_goal", None)),
            _semantic_text(current_details.get("subject")),
            _semantic_text(current_details.get("operation")),
            _semantic_text(current_details.get("method")),
            _semantic_text(current_details.get("focus")),
        ) if value
    )
    old = _tokens(previous)
    new = _tokens(current)
    if not old or not new:
        return False, 0.0
    shared = old & new
    ratio = len(shared) / max(1, min(len(old), len(new)))
    # Two meaningful shared terms, or one highly discriminative shared term in a referential turn.
    referential = str(getattr(understanding, "user_act", "") or "").casefold() in _REFERENTIAL_ACTS
    same_family = len(shared) >= 2 or (referential and ratio >= 0.20 and len(shared) >= 1)
    return same_family, round(ratio, 3)


def reconcile_turn(understanding, memory, message):
    corrections = []
    before = memory.to_dict() if hasattr(memory, "to_dict") else {}
    boundary = infer_topic_boundary(before, understanding.to_dict())
    case = getattr(memory, "support_case", None)
    case_active = bool(case and case.status in {"diagnosing", "reopened"})

    explicit_subject_switch = (
        str(getattr(understanding,"subject_origin","") or "").casefold()=="current_message"
        and bool(str(getattr(understanding,"canonical_subject","") or "").strip())
        and bool(str(getattr(memory,"active_subject","") or "").strip())
        and str(getattr(understanding,"canonical_subject","") or "").strip().casefold()
            != str(getattr(memory,"active_subject","") or "").strip().casefold()
    )
    active_case_continuation = (
        case_active
        and not explicit_subject_switch
        and understanding.intent in {"troubleshooting", "procedural", "requirements", "verification"}
        and understanding.domain_relevance == "in_scope"
    )
    semantic_followup, semantic_ratio = _semantic_continuation(understanding, memory)
    structured_reference_followup = (
        bool(getattr(memory, "active_subject", None))
        and str(getattr(understanding, "reference_relation", "") or "").casefold() == "current_subject"
        and str(getattr(understanding, "subject_origin", "") or "").casefold() in {"conversation_memory", "current_subject", "inherited"}
        and str(getattr(understanding, "canonical_subject", "") or "").strip().casefold()
            == str(getattr(memory, "active_subject", "") or "").strip().casefold()
        and str(getattr(understanding, "domain_relevance", "") or "").casefold() == "in_scope"
        and str(getattr(understanding, "intent", "") or "").casefold() in {"conceptual", "procedural", "requirements", "troubleshooting", "architecture", "warranty"}
    )
    completed_goal_followup = (
        semantic_followup
        and understanding.intent in _CONTINUATION_INTENTS
        and understanding.domain_relevance == "in_scope"
    )

    structured_historical_return = (
        str(getattr(understanding,"topic_relation","") or "").casefold()=="return_to_previous"
        and str(getattr(understanding,"reference_relation","") or "").casefold()=="previous_subject"
        and bool(str(getattr(understanding,"canonical_subject","") or "").strip())
    )
    canonical_independent_turn = (
        str(getattr(understanding,"topic_relation","") or "").casefold() in {"new_topic","independent"}
        and str(getattr(understanding,"user_act","") or "").casefold() in {"new_request","independent_question","topic_change"}
        and str(getattr(understanding,"reference_relation","") or "none").casefold() in {"","none"}
    )
    if structured_historical_return:
        understanding.topic_relation = "return_to_previous"
        boundary = type(boundary)(
            "return_to_previous", "structured_historical_return_preserved", max(boundary.shared_ratio, semantic_ratio),
            boundary.changed_dimensions, boundary.introduced_dimensions, "primary"
        )
        corrections.append("structured_historical_return_preserved")
    elif structured_reference_followup:
        understanding.topic_relation = "same_topic"
        if understanding.user_act == "new_request":
            understanding.user_act = "request_elaboration"
        boundary = type(boundary)(
            "same_topic_refinement", "structured_current_subject_reference", max(boundary.shared_ratio, semantic_ratio),
            boundary.changed_dimensions, boundary.introduced_dimensions, "primary"
        )
        corrections.append("structured_current_subject_continuity_preserved")
    elif canonical_independent_turn and not active_case_continuation:
        understanding.user_act="new_request";understanding.topic_relation="new_topic"
        boundary=type(boundary)("new_topic","canonical_new_topic_precedence",boundary.shared_ratio,boundary.changed_dimensions,boundary.introduced_dimensions,"none")
        corrections.append("canonical_new_topic_precedence_preserved")
    elif active_case_continuation:
        understanding.topic_relation = "same_topic"
        boundary = type(boundary)(
            "same_topic_refinement", "active_case_continuity", boundary.shared_ratio,
            boundary.changed_dimensions, boundary.introduced_dimensions, "primary"
        )
        corrections.append("active_case_continuity_preserved")
    elif completed_goal_followup:
        understanding.topic_relation = "same_topic"
        if understanding.user_act == "new_request":
            understanding.user_act = "request_elaboration"
        boundary = type(boundary)(
            "same_topic_refinement", "semantic_goal_followup", semantic_ratio,
            boundary.changed_dimensions, boundary.introduced_dimensions, "primary"
        )
        corrections.append("completed_goal_followup_preserved")
    elif understanding.user_act == "request_elaboration" and not (
        getattr(memory, "active_topic", None) or getattr(memory, "last_assistant_question", None)
    ):
        understanding.user_act = "new_request"
        understanding.topic_relation = "new_topic"
        corrections.append("orphan_elaboration_to_new_request")
    elif boundary.relation == "new_topic":
        understanding.user_act = "new_request"
        understanding.topic_relation = "new_topic"
        corrections.append("independent_goal_preserved_as_new_topic")
    elif boundary.relation == "same_topic_changed_scope":
        understanding.topic_relation = "same_topic"
        corrections.append("material_scope_change_detected")

    return understanding, corrections, boundary.to_dict()
