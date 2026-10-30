from copy import deepcopy
from typing import Mapping
import re
from .canonical_frame import build_frame,enrich_frame,validate_frame_payload
STORE_KEY="canonical_conversation_frame";REGISTRY_KEY="canonical_topic_registry";DIVERGENCE_KEY="canonical_divergences"
def _m(v):return dict(v) if isinstance(v,Mapping) else {}
def _t(v):return " ".join(str(v or "").split())
def _norm(v):return " ".join(re.findall(r"[a-z0-9]+",_t(v).casefold()))
def _finish(p):
 i=validate_frame_payload(p);p["validation"]={"valid":not i,"issues":i};p["mode"]="shadow";return p
def build_shadow_frame(store,message,result):
 p=_finish(build_frame(message,result.get("understanding") or {},result.get("state_before") or {},store.get("answer_context") or {},store.get(STORE_KEY) or {},store.get(REGISTRY_KEY) or {}).to_dict());store[STORE_KEY]=deepcopy(p);result[STORE_KEY]=deepcopy(p);result[DIVERGENCE_KEY]=compare_runtime(result,p);return p
def enrich_shadow_frame(store,result):
 p=_finish(enrich_frame(result.get(STORE_KEY) or store.get(STORE_KEY) or {},result.get("retrieval") or {},result.get("answer") or {}));store[STORE_KEY]=deepcopy(p);result[STORE_KEY]=deepcopy(p);result[DIVERGENCE_KEY]=compare_runtime(result,p);_commit(store,p,result);return p
def _commit(store,p,result):
 tid=_t(_m(p.get("topic")).get("topic_id"));sub=_m(p.get("subject"));
 if not tid or not _t(sub.get("value")):return
 r=store.setdefault(REGISTRY_KEY,{}).setdefault(tid,{});r.update({"subject":deepcopy(sub),"last_operation":deepcopy(p.get("operation") or {}),"case":deepcopy(p.get("case") or {}),"last_answer_mode":_t(_m(result.get("answer")).get("mode"))})
 ctx=result.get("answer_context") or {}
 if _m(result.get("answer")).get("mode") in {"documented_answer","documented_answer_partial"} and ctx.get("cited_evidence"):r["documented_context"]=deepcopy(ctx)
def _same_relation(a,b):
 a=_t(a);b=_t(b)
 same={"same_topic","same_topic_refinement","same_topic_candidate"}
 return a==b or (a in same and b in same)
def _subject_coverage(fields):
 details=_m(fields.get("details"));return _t(fields.get("subject") or details.get("subject") or fields.get("subject_id"))
def _case_signal(value):
 c=_m(value);return bool(_t(c.get("subject")) or c.get("symptoms") or c.get("observations") or c.get("attempts") or _t(c.get("affected_scope")) or _t(c.get("resolution_status")))
def _div(kind,severity,**extra):return {"type":kind,"severity":severity,**extra}
def compare_runtime_detailed(result,p):
 u=_m(result.get("understanding"));topic=_m(p.get("topic"));operation=_m(p.get("operation"));shadow_subject=_m(p.get("subject"));known=_m(p.get("known_details"))
 retrieval=_m(result.get("retrieval"));query=_m(retrieval.get("query"));fields=_m(query.get("fields"));runtime_after=_m(result.get("state_after"));runtime_case=_m(runtime_after.get("support_case"));shadow_case=_m(p.get("case"))
 runtime={"act":_t(u.get("user_act")),"intent":_t(u.get("intent")),"domain_relevance":_t(u.get("domain_relevance")),"subject":_t(u.get("canonical_subject")),"subject_origin":_t(u.get("subject_origin")),"topic_relation":_t(u.get("topic_relation")),"reference_relation":_t(u.get("reference_relation")),"retrieval_required":bool(u.get("should_retrieve")),"query_subject":_subject_coverage(fields),"case_signal":_case_signal(runtime_case),"case":deepcopy(runtime_case)}
 shadow={"act":_t(p.get("act")),"intent":_t(operation.get("intent")),"domain_relevance":_t(p.get("domain_relevance")),"subject":_t(shadow_subject.get("value")),"subject_origin":_t(shadow_subject.get("origin")),"known_subject":_t(known.get("subject")),"topic_relation":_t(topic.get("relation")),"retrieval_required":bool(p.get("retrieval_required")),"case_signal":_case_signal(shadow_case),"case":deepcopy(shadow_case)}
 out=[];observations=[]
 if runtime["act"] and shadow["act"] and runtime["act"]!=shadow["act"]:out.append(_div("user_act_disagreement","medium",runtime=runtime["act"],shadow=shadow["act"]))
 if runtime["intent"] and shadow["intent"] and runtime["intent"]!=shadow["intent"]:out.append(_div("intent_disagreement","high",runtime=runtime["intent"],shadow=shadow["intent"]))
 if runtime["domain_relevance"] and shadow["domain_relevance"] and runtime["domain_relevance"]!=shadow["domain_relevance"]:out.append(_div("domain_relevance_disagreement","high",runtime=runtime["domain_relevance"],shadow=shadow["domain_relevance"]))
 if not _same_relation(runtime["topic_relation"],shadow["topic_relation"]):out.append(_div("topic_relation_disagreement","high",runtime=runtime["topic_relation"],shadow=shadow["topic_relation"]))
 if runtime["retrieval_required"]!=shadow["retrieval_required"]:out.append(_div("retrieval_requirement_disagreement","high",runtime=runtime["retrieval_required"],shadow=shadow["retrieval_required"]))
 # Query subject may be represented directly or under details.subject. QA-1 only checked the first representation.
 if shadow["retrieval_required"] and query and not runtime["query_subject"]:out.append(_div("retrieval_query_missing_resolved_subject","high",runtime_subject=runtime["subject"],shadow_subject=shadow["subject"]))
 # Compare current-request subject against the shadow's known subject. Evidence metadata IDs are retained as an observation, not treated as the human-facing subject.
 if runtime["domain_relevance"]=="in_scope" and runtime["subject"] and shadow["known_subject"] and _norm(runtime["subject"])!=_norm(shadow["known_subject"]):out.append(_div("known_subject_disagreement","high",runtime=runtime["subject"],shadow_known=shadow["known_subject"]))
 if runtime["subject"] and shadow["subject"] and _norm(runtime["subject"])!=_norm(shadow["subject"]):observations.append({"type":"evidence_subject_identity_differs","runtime_subject":runtime["subject"],"shadow_evidence_subject":shadow["subject"],"shadow_origin":shadow["subject_origin"]})
 # New topics must not inherit the prior support case. Troubleshooting must capture the newly opened or updated case after runtime processing.
 new_topic=runtime["topic_relation"] in {"new_topic","independent"}
 if new_topic and runtime["intent"]!="troubleshooting" and shadow["case_signal"]:out.append(_div("shadow_case_context_carried_into_new_topic","high",shadow_case=shadow_case))
 if runtime["intent"]=="troubleshooting" and runtime["case_signal"] and not shadow["case_signal"]:out.append(_div("shadow_missing_runtime_case_context","high",runtime_case=runtime_case))
 elif runtime["intent"]=="troubleshooting" and runtime_case.get("attempts") and not shadow_case.get("attempts"):out.append(_div("shadow_missing_confirmed_attempts","high",runtime_attempt_count=len(runtime_case.get("attempts") or [])))
 if runtime["domain_relevance"]=="out_of_scope" and runtime["subject"]!=shadow["subject"]:observations.append({"type":"technical_subject_preserved_during_out_of_scope","runtime_request_subject":runtime["subject"],"preserved_shadow_subject":shadow["subject"]})
 return {"status":"divergence" if out else "match","divergence_count":len(out),"divergences":out,"observations":observations,"runtime":runtime,"shadow":shadow}
def compare_runtime(result,p):return compare_runtime_detailed(result,p)["divergences"]
def refresh_shadow_diagnostics(result):result[DIVERGENCE_KEY]=compare_runtime(result,_m(result.get(STORE_KEY)));return result[DIVERGENCE_KEY]
