from copy import deepcopy
import re
from .memory import apply_understanding
from .scope_reconciler import reconcile_turn
from .scope_authority import reconcile_scope
from .operational_coherence import reconcile_understanding_object,apply_reopen_transition
from .conversation_entity_frame import reconcile_entity_frame
from .conversation_guardrails import reconcile_association,scope_gate
from .models import AgentResponse
from .escalation_intake import reconcile_escalation_intake
from .document_object_continuity import reconcile_document_object
from .decision_observability import snapshot,decision_trace

def _closing_question(text):
 f=list(re.finditer(r"¿[^?]{1,420}\?"," ".join(str(text or "").split())));return f[-1].group(0).strip() if f else None

def _is_structurally_social(u, message=""):
    """Recognize a non-operational lateral turn from the semantic payload.

    This deliberately avoids matching user words, product names or languages.  It also runs
    before any reconciler can mutate conversation memory.  The explicit labels remain the
    primary signal; the structural fallback covers provider label drift such as a greeting
    returned as ``new_request/conceptual`` while every operational field says "do nothing".
    """
    intent = str(getattr(u, "intent", "") or "").casefold()
    user_act = str(getattr(u, "user_act", "") or "").casefold()
    if intent == "social" or user_act == "social":
        return True, "explicit_semantic_social_label"

    domain = str(getattr(u, "domain_relevance", "") or "").casefold()
    workflow = str(getattr(u, "requested_workflow", "none") or "none").casefold()
    reference = str(getattr(u, "reference_relation", "none") or "none").casefold()
    goal_updates = dict(getattr(u, "goal_updates", {}) or {})
    original_message_word_count = len(str(message or "").split())
    no_operational_payload = (
        not bool(getattr(u, "needs_clarification", False))
        and set(goal_updates).issubset({"operation"})
        and not list(getattr(u, "case_updates", []) or [])
        and not str(getattr(u, "canonical_subject", "") or "").strip()
        and workflow in {"", "none"}
        and reference in {"", "none"}
    )
    # A provider may drift only the retrieval flag on a very short, subjectless social opener.
    # Technical requests remain protected by canonical_subject, case updates, workflow or detail fields.
    label_drift_shape = user_act == "new_request" and intent == "conceptual" and original_message_word_count <= 3
    eligible_domain = domain not in {"out_of_scope", "uncertain"}
    if no_operational_payload and label_drift_shape and eligible_domain:
        return True, "structural_non_operational_lateral_turn"
    return False, None


class CleanConversationalAgent:
    def __init__(self, understanding, policy, response):
        self.understanding = understanding
        self.policy = policy
        self.response = response

    def process(self, message, memory, answer_context=None):
        before = deepcopy(memory.to_dict())
        u = self.understanding.interpret(message, memory)
        decision_stages = [("provider_understanding", snapshot(u))]
        social_turn, social_reason = _is_structurally_social(u, message)
        corrections = []
        events = []
        authoritative_scope = {"applied":False,"terminal":False,"reason":"social_turn_bypasses_scope_authority"}
        if not social_turn:
            scoped, authoritative_scope = reconcile_scope(message, u.to_dict(), before)
            for key,value in scoped.items():
                if hasattr(u,key):setattr(u,key,value)
            decision_stages.append(("authoritative_scope_gate", snapshot(u)))
            if authoritative_scope.get("applied"):
                corrections.append("authoritative_scope_reconciled")
                events.append({"type":"authoritative_scope_gate",**authoritative_scope})
        association_event = {"applied": False, "reason": "social_turn_bypasses_association_reconciliation"} if social_turn else None
        scope_event = {"applied": False, "reason": "social_turn_bypasses_scope_reconciliation"} if social_turn else None

        if social_turn:
            # Normalize and terminate before entity, topic, scope or case reconcilers can mutate state.
            u.intent = "social"
            u.user_act = "social"
            u.topic_relation = "same_topic" if (memory.active_topic or memory.active_subject) else "no_topic"
            u.should_retrieve = False
            u.needs_clarification = False
            u.clarification_target = None
            u.case_updates = []
            u.goal_updates = {}
            u.goal_complete = True
            u.canonical_subject = None
            u.subject_origin = None
            u.reference_relation = "none"
            u.requested_workflow = "none"
            entity_frame = {
                "version": "entity_frame_v1",
                "active_before": memory.active_subject,
                "explicit": None,
                "reference": "none",
                "selected": memory.active_subject,
                "transition": "preserved_social_terminal",
                "history": deepcopy(memory.subject_history),
            }
            boundary = {
                "relation": "neutral_social_interruption",
                "previous_evidence_role": "preserved" if memory.active_subject else "none",
                "reason": "social_turn_does_not_create_or_change_technical_topic",
            }
            corrections.extend([
                "social_turn_semantic_label_reconciled" if social_reason != "explicit_semantic_social_label" else "social_turn_confirmed",
                "social_turn_operational_state_guard",
                "social_turn_neutral_boundary",
                "social_turn_pre_reconciliation_terminal",
            ])
            events.append({
                "type": "deterministic_social_terminal",
                "reason": social_reason or "semantic_social_act_requires_no_response_generation",
            })
        else:
            decision_stages.append(("pre_continuity_contract", snapshot(u)))
            reconciled,event=reconcile_document_object(message,u.to_dict(),memory,answer_context or {})
            if event.get("applied"):
                for key,value in reconciled.items():
                    if hasattr(u,key):setattr(u,key,value)
                events.append({"type":"active_document_object_continuity",**event})
                corrections.append("active_document_object_continuity_preserved")
            decision_stages.append(("document_object_continuity", snapshot(u)))
            if str(u.domain_relevance or "").casefold() == "out_of_scope":
                entity_frame = {
                    "version": "entity_frame_v1",
                    "active_before": memory.active_subject,
                    "explicit": u.canonical_subject,
                    "reference": u.reference_relation,
                    "selected": memory.active_subject,
                    "transition": "blocked_out_of_scope",
                    "history": deepcopy(memory.subject_history),
                }
            else:
                u, entity_frame = reconcile_entity_frame(memory, u, message)
            decision_stages.append(("conversation_entity_frame", snapshot(u)))
            u, corrections, boundary = reconcile_turn(u, memory, message)
            decision_stages.append(("scope_reconciler", snapshot(u)))
            u, coherence_events = reconcile_understanding_object(u, memory, boundary)
            events.extend(coherence_events)
            decision_stages.append(("operational_coherence", snapshot(u)))
            guarded, association_event = reconcile_association(message, u.to_dict(), before)
            guarded, scope_event = scope_gate(message, guarded, before)
            for key, value in guarded.items():
                if hasattr(u, key):
                    setattr(u, key, value)
            decision_stages.append(("association_and_scope_guards", snapshot(u)))

        u, escalation_intake = reconcile_escalation_intake(message, u)
        if escalation_intake.get("applied"):
            events.append({"type":"escalation_intake_reconciled",**escalation_intake})
        decision_stages.append(("escalation_intake", snapshot(u)))
        trace = decision_trace(decision_stages, before, boundary, entity_frame, events)
        normalization = deepcopy(self.understanding.normalization or {})
        normalization.setdefault("structural_corrections", [])
        for item in corrections + [event.get("reason") for event in events]:
            if item and item not in normalization["structural_corrections"]:
                normalization["structural_corrections"].append(item)

        decision = self.policy.decide(u, memory)
        if social_turn:
            memory.turn_number += 1
        else:
            apply_understanding(memory, u)
            apply_reopen_transition(memory, events)

        if decision.action in {"offer_escalation", "continue_escalation"}:
            answer = AgentResponse("", "workflow_pending", False)
        else:
            answer = self.response.compose(message, memory, u, decision)
        question = _closing_question(answer.text)
        if not social_turn:
            if question:
                memory.last_assistant_question = question
            elif decision.action not in {"redirect_scope", "degraded_continue", "offer_escalation", "continue_escalation"}:
                memory.last_assistant_question = None

        return {
            "input": message,
            "state_before": before,
            "understanding": u.to_dict(),
            "understanding_contract": {
                "valid": self.understanding.contract_valid,
                "error": self.understanding.validation_error,
                "normalization": deepcopy(self.understanding.normalization or {}),
                "repair_attempted": bool((self.understanding.normalization or {}).get("repair_attempted")),
                "repair_succeeded": bool((self.understanding.normalization or {}).get("repair_succeeded")),
            },
            "goal_update_normalization": normalization,
            "decision": decision.to_dict(),
            "state_after": deepcopy(memory.to_dict()),
            "answer": answer.to_dict(),
            "provider_trace": {
                "understanding": self.understanding.last_provider_result,
                "response": self.response.last_provider_result if decision.action not in {"offer_escalation", "continue_escalation"} else {"skipped": True, "reason": "native_workflow_response_authority"},
            },
            "retrieval": {"enabled": False},
            "topic_boundary": boundary,
            "conversation_entity_frame": entity_frame,
            "decision_trace": trace,
            "association_reconciliation": association_event,
            "scope_gate": scope_event,
            "scope_authority": authoritative_scope,
            "functional_events": events,
            "production_changed": False,
        }
