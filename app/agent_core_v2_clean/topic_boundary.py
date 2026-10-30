from __future__ import annotations
from dataclasses import asdict, dataclass
import re
import unicodedata

_TOKEN_RE = re.compile(r"[\wáéíóúüñ]+", re.I)
STRUCTURAL = {"operation", "subject", "platform", "product", "component", "device", "scope"}
_OPERATION_GENERIC = {"explicar", "procedimiento", "realizar", "consultar", "actualizar", "configurar", "impresora", "impresion", "usuario", "como", "para", "del", "una", "the", "how", "printer", "user"}
MATERIAL_SCOPE = {"platform", "product", "component", "device", "scope"}
_REFERENTIAL_ACTS = {"request_elaboration", "answer", "confirmation", "correction", "continue"}
_REFINEMENT_MARKERS = {"paso", "parte", "opcion", "campo", "despues", "antes", "siguiente", "donde", "cual", "cuando", "como", "porque", "eso", "esa", "ese", "esto", "esta", "that", "this", "it", "step", "option", "field", "next", "after", "before", "where", "which"}

@dataclass(frozen=True)
class TopicBoundary:
    relation: str
    reason: str
    shared_ratio: float
    changed_dimensions: list[str]
    introduced_dimensions: list[str]
    previous_evidence_role: str
    def to_dict(self): return asdict(self)

def _norm(value):
    return unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode().casefold()

def _tokens(value):
    return {x.casefold() for x in _TOKEN_RE.findall(_norm(value)) if len(x) > 2}

def _material_operation_change(before, now, old_goal, new_goal):
    old_value = before.get("operation") or old_goal
    new_value = now.get("operation") or new_goal
    old_terms = _tokens(old_value) - _OPERATION_GENERIC
    new_terms = _tokens(new_value) - _OPERATION_GENERIC
    if not old_terms or not new_terms:
        return False
    overlap = len(old_terms & new_terms) / max(1, len(old_terms | new_terms))
    return overlap < 0.20 and bool(new_terms - old_terms)

def _is_refinement(previous_state, understanding, old, new, changed, introduced):
    pending = (previous_state or {}).get("pending_goal") or {}
    if not pending.get("summary") or introduced: return False
    relation = str((understanding or {}).get("topic_relation") or "")
    act = str((understanding or {}).get("user_act") or "")
    if relation == "same_topic" or act in _REFERENTIAL_ACTS: return True
    markers = new & _REFINEMENT_MARKERS
    subject_only_change = set(changed).issubset({"operation", "subject"})
    lexical_containment = bool(old & new) and len(old & new) / max(1, len(new)) >= 0.20
    return subject_only_change and bool(markers) and lexical_containment

def infer_topic_boundary(previous_state: dict, understanding: dict) -> TopicBoundary:
    before = ((previous_state or {}).get("pending_goal") or {}).get("known_details") or {}
    now = (understanding or {}).get("goal_updates") or {}
    old_goal = ((previous_state or {}).get("pending_goal") or {}).get("summary") or ""
    new_goal = (understanding or {}).get("current_goal") or ""
    old = _tokens(old_goal) | _tokens(" ".join(str(before.get(k, "")) for k in STRUCTURAL))
    new = _tokens(new_goal) | _tokens(" ".join(str(now.get(k, "")) for k in STRUCTURAL))
    shared = len(old & new) / max(1, len(old | new))
    changed = sorted(k for k in STRUCTURAL if before.get(k) and now.get(k) and _norm(before[k]) != _norm(now[k]))
    introduced = sorted(k for k in MATERIAL_SCOPE if not before.get(k) and now.get(k))
    material_operation = _material_operation_change(before, now, old_goal, new_goal)
    previous_subject=(previous_state or {}).get("active_subject") or before.get("subject")
    current_subject=(understanding or {}).get("canonical_subject") or now.get("subject")
    explicit_subject_switch=(
        str((understanding or {}).get("subject_origin") or "").casefold()=="current_message"
        and bool(previous_subject and current_subject)
        and _norm(previous_subject)!=_norm(current_subject)
    )
    if explicit_subject_switch:
        changed=sorted(set(changed)|{"subject"})
        return TopicBoundary("new_topic","explicit_current_message_subject_switch",round(shared,3),changed,introduced,"none")
    semantic_continuation = (
        str((understanding or {}).get("topic_relation") or "").casefold() == "same_topic"
        or str((understanding or {}).get("user_act") or "").casefold() in _REFERENTIAL_ACTS
        or (bool((understanding or {}).get("case_updates")) and not introduced)
    )
    # A diagnostic update can change the immediate operation while preserving the
    # same incident. Explicit semantic continuity and case facts outrank lexical
    # operation drift unless a new material subject/scope was introduced.
    if semantic_continuation and not introduced:
        return TopicBoundary("same_topic_refinement", "semantic_continuation_with_case_progress", round(shared, 3), changed, introduced, "primary")
    if material_operation:
        changed = sorted(set(changed) | {"operation"})
        return TopicBoundary("new_topic", "material_operation_changed", round(shared, 3), changed, introduced, "none")
    if _is_refinement(previous_state, understanding, old, new, changed, introduced):
        return TopicBoundary("same_topic_refinement", "referential_or_contained_goal_refinement", round(shared, 3), changed, introduced, "primary")
    explicit_new = (understanding or {}).get("topic_relation") == "new_topic"
    independent = bool(new_goal and now.get("operation") and now.get("subject"))
    if explicit_new or (independent and {"operation", "subject"}.issubset(changed) and shared < .50):
        return TopicBoundary("new_topic", "explicit_or_independent_goal_boundary", round(shared, 3), changed, introduced, "none")
    if any(k in MATERIAL_SCOPE for k in changed) or introduced:
        return TopicBoundary("same_topic_changed_scope", "material_scope_changed", round(shared, 3), changed, introduced, "comparison_only")
    return TopicBoundary("same_topic", "continuity_preserved", round(shared, 3), changed, introduced, "eligible")

def sanitize_new_topic_state(memory, understanding: dict, previous_state: dict | None = None):
    pending = getattr(memory, "pending_goal", None)
    if pending is not None:
        pending.known_details = dict((understanding or {}).get("goal_updates") or {})
        pending.summary = str((understanding or {}).get("current_goal") or "")
    if hasattr(memory, "fact_records"): memory.fact_records = {}
