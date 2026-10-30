from __future__ import annotations
from dataclasses import dataclass,field,asdict
from typing import Any,Mapping
import hashlib,json
VALID_ORIGINS={"current_turn","conversation","canonical_history","user_confirmed","documented_context","authorized_evidence","none"}
def _text(v):return " ".join(str(v or "").split())
def _map(v):return dict(v) if isinstance(v,Mapping) else {}
def stable_topic_id(t,v):
 if not v:return ""
 return hashlib.sha256(json.dumps({"type":_text(t).casefold(),"value":_text(v).casefold()},sort_keys=True).encode()).hexdigest()[:20]
@dataclass
class CanonicalSubject:type:str="unknown";value:str="";canonical_id:str="";origin:str="none";confidence:float=0.0
@dataclass
class CanonicalOperation:intent:str="unknown";text:str="";current_message:str=""
@dataclass
class CanonicalTopic:topic_id:str="";relation:str="new_topic";status:str="active"
@dataclass
class CanonicalConversationFrame:
 schema_version:int=3;act:str="new_request";domain_relevance:str="uncertain";subject:CanonicalSubject=field(default_factory=CanonicalSubject);operation:CanonicalOperation=field(default_factory=CanonicalOperation);topic:CanonicalTopic=field(default_factory=CanonicalTopic);known_details:dict[str,str]=field(default_factory=dict);missing_material_details:list[str]=field(default_factory=list);retrieval_required:bool=False;case:dict[str,Any]=field(default_factory=dict);warnings:list[str]=field(default_factory=list);phase:str="pre_retrieval"
 def to_dict(self):return asdict(self)
def _subject(t,v,i="",o="none",c=0):
 v=_text(v);return CanonicalSubject(t if v else "unknown",v,_text(i),o if v else "none",c if v else 0)
def _explicit(details):
 d=_map(details)
 for t,k in (("product","product"),("product","platform"),("model","model"),("component","component"),("process","process"),("document","document"),("subject","subject")):
  if _text(d.get(k)):return _subject(t,d[k],d.get("canonical_id"),"user_confirmed",1)
 return CanonicalSubject()
def _previous(prev,registry):
 p=_map(prev);s=_map(p.get("subject"));v=_text(s.get("value"))
 if not v:
  tid=_text(_map(p.get("topic")).get("topic_id"));s=_map(_map(registry).get(tid)).get("subject") or {};v=_text(s.get("value"))
 return _subject(_text(s.get("type")) or "subject",v,s.get("canonical_id"),"canonical_history",float(s.get("confidence") or .85)) if v else CanonicalSubject()
def build_frame(message,understanding,memory,answer_context=None,previous_frame=None,topic_registry=None):
 u=_map(understanding);m=_map(memory);pending=_map(m.get("pending_goal"));details={**_map(pending.get("known_details")),**_map(u.get("goal_updates"))};explicit=_explicit(details);previous=_previous(previous_frame,topic_registry)
 runtime_intent=_text(u.get("intent"));pending_intent=_text(pending.get("intent"));prior_intent=_text(_map(_map(previous_frame).get("operation")).get("intent"));intent=runtime_intent if runtime_intent and runtime_intent!="unknown" else pending_intent if pending_intent and pending_intent!="unknown" else prior_intent if prior_intent and prior_intent!="unknown" else "unknown"
 relation=_text(u.get("topic_relation")) or "new_topic";warnings=[];continuity=relation in {"same_topic","same_topic_refinement"} or _text(u.get("user_act")) in {"follow_up","answer_to_question","request_elaboration"}
 # A runtime new topic may inherit only when the semantic intent remains stable. Intent change is a real boundary.
 stable_intent=bool(previous.value and prior_intent not in {"","unknown"} and intent==prior_intent)
 if explicit.value:subject=explicit
 elif continuity and previous.value:subject=previous
 elif relation=="new_topic" and previous.value:
  # An operation or intent change does not by itself replace the conversational subject.
  # Keep it as a candidate until explicit input or authorized evidence resolves another subject.
  subject=previous;relation="same_topic_candidate";warnings.append("runtime_new_topic_without_new_subject")
 else:subject=CanonicalSubject()
 if continuity and not subject.value:warnings.append("follow_up_without_resolved_subject")
 prior_tid=_text(_map(_map(previous_frame).get("topic")).get("topic_id"));tid=prior_tid if relation in {"same_topic","same_topic_refinement","same_topic_candidate"} and prior_tid else stable_topic_id(subject.type,subject.canonical_id or subject.value)
 case=_map(m.get("support_case"));op=_text(u.get("current_goal")) or _text(message)
 if u.get("should_retrieve") and not subject.value:warnings.append("retrieval_without_subject")
 if u.get("should_retrieve") and intent=="unknown":warnings.append("technical_intent_unresolved")
 if intent=="troubleshooting" and not any((case.get("symptoms"),case.get("observations"),case.get("attempts"),case.get("affected_scope"))):warnings.append("troubleshooting_without_case_context")
 return CanonicalConversationFrame(act=_text(u.get("user_act")) or "new_request",domain_relevance=_text(u.get("domain_relevance")) or "uncertain",subject=subject,operation=CanonicalOperation(intent,op,_text(message)),topic=CanonicalTopic(tid,relation),known_details={str(k):_text(v) for k,v in details.items() if _text(v)},retrieval_required=bool(u.get("should_retrieve")),case={"symptoms":list(case.get("symptoms") or []),"observations":list(case.get("observations") or []),"attempts":list(case.get("attempts") or []),"affected_scope":case.get("affected_scope"),"resolution_status":case.get("resolution_status")},warnings=warnings)
def _authorized(retrieval):
 verdict=_map(_map(retrieval).get("evidence_verdict"));ids=[]
 if not verdict.get("accepted"):return CanonicalSubject()
 for x in verdict.get("selected_evidence") or []:
  meta=_map(_map(x).get("metadata"));v=_text(meta.get("product") or meta.get("component"));t="product" if _text(meta.get("product")) else "component"
  if v:ids.append((t,v))
 uniq={(t,v.casefold()):(t,v) for t,v in ids}
 return _subject(*next(iter(uniq.values())),next(iter(uniq.values()))[1],"authorized_evidence",.95) if len(uniq)==1 else CanonicalSubject()
def enrich_frame(payload,retrieval,answer=None):
 p=dict(payload or {});s=_map(p.get("subject"));a=_authorized(retrieval);w=list(p.get("warnings") or [])
 if a.value and (not _text(s.get("value")) or _text(s.get("canonical_id") or s.get("value")).casefold()!=_text(a.canonical_id or a.value).casefold()):
  # Current authorized evidence can resolve or replace a carried candidate subject.
  p["subject"]=asdict(a);t=_map(p.get("topic"));t["topic_id"]=stable_topic_id(a.type,a.canonical_id or a.value);p["topic"]=t
 elif not _text(s.get("value")) and _map(retrieval).get("evidence_verdict",{}).get("accepted"):w.append("accepted_evidence_without_unambiguous_subject")
 p["warnings"]=sorted(set(w));p["phase"]="post_retrieval";return p
def validate_frame_payload(p):
 p=_map(p);issues=[];t=_map(p.get("topic"));s=_map(p.get("subject"))
 if _text(t.get("relation")) in {"same_topic","same_topic_refinement","same_topic_candidate"} and not _text(t.get("topic_id")):issues.append("same_topic_requires_topic_id")
 if _text(s.get("origin")) not in VALID_ORIGINS:issues.append("invalid_subject_origin")
 return issues
