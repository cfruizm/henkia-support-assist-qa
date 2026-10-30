from __future__ import annotations
import re
from .models import ConversationMemory, TurnUnderstanding
from .memory import failed_actions, normalize_text

TECH_INTENTS={"troubleshooting","procedural","requirements","architecture","warranty"}

class TurnReconciler:
    def _active_case_next_step(self,u,memory):
        return memory.support_case.status=="diagnosing" and u.user_act in {"follow_up","request_elaboration","answer_to_question","attempt_result"}

    def reconcile(self,u,memory,message=""):
        warnings=[]
        if self._active_case_next_step(u,memory):
            u.should_retrieve=True
            if u.topic_relation=="new_topic":
                u.topic_relation="same_topic";warnings.append("active_case_relation_preserved")
        if u.needs_clarification:
            # A proposed clarification never outranks an active case or a clear conceptual question.
            if u.intent in {"conceptual","requirements"} and u.current_goal:
                u.needs_clarification=False;u.clarification_target=None;warnings.append("clarification_removed_for_clear_goal")
            elif memory.support_case.status=="diagnosing" and u.should_retrieve:
                u.needs_clarification=False;u.clarification_target=None;warnings.append("clarification_deferred_until_grounding")
        if u.intent in TECH_INTENTS and u.current_goal:
            u.should_retrieve=True
        if u.domain_relevance=="out_of_scope":
            u.should_retrieve=False;u.needs_clarification=False;u.clarification_target=None
        return u,warnings

    def decision(self,u,memory):
        if u.domain_relevance=="out_of_scope":return {"action":"redirect_scope","reason":"out_of_scope","ask_one_question":False}
        if u.user_act=="social" or u.intent=="social":return {"action":"social","reason":"social_message"}
        if u.user_act=="cancel" or u.intent=="cancel":return {"action":"cancel","reason":"explicit_cancel"}
        if u.user_act=="escalation" or u.intent=="escalation":return {"action":"offer_escalation","reason":"explicit_escalation"}
        if u.degraded:return {"action":"degraded_continue","reason":"understanding_unavailable"}
        if u.needs_clarification and u.clarification_target:
            return {"action":"ask_one_question","reason":"indispensable_missing_detail","ask_one_question":True,"question_target":u.clarification_target}
        if u.should_retrieve or u.intent in TECH_INTENTS:
            return {"action":"retrieve","reason":"technical_or_documented_answer","response_mode":"grounded"}
        return {"action":"answer","reason":"clear_non_documented_request","response_mode":"natural"}
