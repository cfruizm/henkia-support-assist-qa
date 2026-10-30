"""QA-only topic-boundary oracle.

Creates an alternative boundary proposal from already available structured data.
It never writes to runtime understanding, memory, retrieval, or response.
"""
from __future__ import annotations
from copy import deepcopy
import re
from typing import Any, Mapping

SCHEMA_VERSION=1

def _m(v:Any)->dict:return dict(v) if isinstance(v,Mapping) else {}
def _t(v:Any)->str:return " ".join(str(v or "").split())
def _norm(v:Any)->str:return " ".join(re.findall(r"[a-z0-9]+",_t(v).casefold()))
def _active_case(state:Mapping[str,Any])->dict:
 c=_m(_m(state).get("support_case"));return c if _t(c.get("subject")) or c.get("symptoms") or c.get("attempts") else {}

def propose_boundary(result:Mapping[str,Any])->dict:
 u=_m(result.get("understanding"));before=_m(result.get("state_before"));after=_m(result.get("state_after"));previous_case=_active_case(before);current_case=_active_case(after)
 current_subject=_t(u.get("canonical_subject"));previous_case_subject=_t(previous_case.get("subject"));origin=_t(u.get("subject_origin"));reference=_t(u.get("reference_relation"));runtime_relation=_t(u.get("topic_relation"));runtime_intent=_t(u.get("intent"))
 explicit_new_subject=bool(current_subject and previous_case_subject and _norm(current_subject)!=_norm(previous_case_subject) and origin=="current_message" and reference in {"","none"})
 runtime_case_closed=bool(previous_case and not current_case)
 expected_relation="new_topic" if explicit_new_subject else runtime_relation
 should_clear_case=bool(explicit_new_subject or runtime_case_closed)
 reasons=[]
 if explicit_new_subject:reasons.append("explicit_current_subject_differs_from_active_case")
 if runtime_case_closed:reasons.append("runtime_closed_previous_support_case")
 return {"schema_version":SCHEMA_VERSION,"runtime":{"subject":current_subject,"topic_relation":runtime_relation,"intent":runtime_intent,"subject_origin":origin,"reference_relation":reference,"previous_case_subject":previous_case_subject,"case_active_after":bool(current_case)},"proposal":{"topic_relation":expected_relation,"clear_previous_case":should_clear_case,"new_subject_boundary":explicit_new_subject},"reason_codes":reasons,"status":"boundary_change_proposed" if expected_relation!=runtime_relation or should_clear_case else "runtime_boundary_preserved","observational_only":True,"production_changed":False}

def apply_boundary_to_shadow(frame:Mapping[str,Any],proposal:Mapping[str,Any])->tuple[dict,dict]:
 p=deepcopy(frame or {});prop=_m(proposal.get("proposal"));before_rel=_t(_m(p.get("topic")).get("relation"));before_case=deepcopy(_m(p.get("case")))
 if _t(prop.get("topic_relation")):
  topic=_m(p.get("topic"));topic["relation"]=_t(prop.get("topic_relation"));p["topic"]=topic
 if prop.get("clear_previous_case"):
  p["case"]={"symptoms":[],"observations":[],"attempts":[],"affected_scope":None,"resolution_status":None}
 return p,{"changed":before_rel!=_t(_m(p.get("topic")).get("relation")) or before_case!=_m(p.get("case")),"topic_relation_before":before_rel,"topic_relation_after":_t(_m(p.get("topic")).get("relation")),"case_cleared":bool(prop.get("clear_previous_case")),"reason_codes":list(proposal.get("reason_codes") or [])}
