from __future__ import annotations
from typing import Mapping
CASE_SIGNAL_TYPES={"symptom","observation","reported_failure","new_case","affected_scope","attempt_result"}
def _m(v):return dict(v) if isinstance(v,Mapping) else {}
def _resolved(s):return str(_m(s.get("support_case")).get("resolution_status","")).casefold()=="resolved" or str(_m(_m(s.get("pending_goal")).get("known_details")).get("resolution_status","")).casefold()=="resolved"
def reconcile_understanding_object(u,memory,boundary=None):
 events=[];p=u.to_dict()
 if str(p.get("domain_relevance","")).casefold()=="out_of_scope":
  u.should_retrieve=False;u.needs_clarification=False;u.clarification_target=None;u.case_updates=[]
  events.append({"type":"scope_preserved","reason":"explicit_out_of_scope_is_terminal"})
 if _resolved(memory.to_dict()) and p.get("case_updates") and not p.get("goal_complete"):u.goal_complete=False;events.append({"type":"case_reopened","reason":"new_failure_after_resolution"})
 return u,events
def apply_reopen_transition(memory,events):
 if any(x.get("type")=="case_reopened" for x in events):memory.pending_goal.status="active";memory.pending_goal.known_details.pop("resolution_status",None);memory.support_case.status="reopened";memory.support_case.resolution_status="regressed"
def normalize_generation_flags(result):
 d=result.get("evidence_decision") or {};s=result.get("evidence_sufficiency") or {};r=result.get("retrieval") or {};f=r.get("semantic_fit") or {};v=r.get("evidence_verdict") or {}
 if f:
  accepted=bool(v.get("accepted")) or (bool(d.get("accepted")) and bool(s.get("generation_allowed")))
  f["accepted_for_generation"]=accepted;f["low_fit"]=not accepted
  if accepted and str(v.get("reason") or "").startswith("primary_document_"):
   f["previous_answer_sources_used"]=True;f["previous_evidence_role"]="primary"
 return result
