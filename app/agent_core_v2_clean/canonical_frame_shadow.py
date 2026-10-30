from copy import deepcopy
from typing import Mapping
from .canonical_frame import build_frame,enrich_frame,validate_frame_payload
STORE_KEY="canonical_conversation_frame";REGISTRY_KEY="canonical_topic_registry";DIVERGENCE_KEY="canonical_divergences"
def _m(v):return dict(v) if isinstance(v,Mapping) else {}
def _t(v):return " ".join(str(v or "").split())
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
def compare_runtime(result,p):
 out=[];u=_m(result.get("understanding"));s=_t(_m(p.get("subject")).get("value"));t=_m(p.get("topic"));q=_m(_m(result.get("retrieval")).get("query"));f=_m(q.get("fields"))
 if s and q and not _t(f.get("subject")):out.append({"type":"retrieval_query_missing_canonical_subject","severity":"high","canonical_subject":s})
 if "troubleshooting_without_case_context" in (p.get("warnings") or []):out.append({"type":"troubleshooting_without_case_context","severity":"high"})
 if _t(t.get("relation"))=="same_topic_candidate" and _t(u.get("topic_relation"))=="new_topic":out.append({"type":"topic_relation_disagreement","severity":"high"})
 return out
def refresh_shadow_diagnostics(result):result[DIVERGENCE_KEY]=compare_runtime(result,_m(result.get(STORE_KEY)));return result[DIVERGENCE_KEY]
