"""QA-only observational canonical shadow.

The shadow reuses artifacts already produced by the runtime. It never changes
production memory, retrieval, decisions, or the user-visible answer.
"""
from __future__ import annotations
from copy import deepcopy
import json
from typing import Any, Mapping
from .canonical_frame_shadow import STORE_KEY, DIVERGENCE_KEY, build_shadow_frame, enrich_shadow_frame

SCHEMA_VERSION=1
SHADOW_STORE_KEY="qa_canonical_shadow_store"

def _m(v:Any)->dict:return dict(v) if isinstance(v,Mapping) else {}
def _bool(v:Any,default:bool=False)->bool:
 if v is None:return default
 if isinstance(v,bool):return v
 return str(v).strip().casefold() in {"1","true","yes","on"}
def _get(c:Any,k:str,d:Any=None)->Any:
 g=getattr(c,"get",None)
 if not callable(g):return d
 try:return g(k,d)
 except TypeError:
  v=g(k);return d if v is None else v

def shadow_config(c:Any)->dict:
 requested=_bool(_get(c,"HENKIA_SHADOW_ENABLED",False))
 observational=_bool(_get(c,"HENKIA_SHADOW_OBSERVATIONAL_ONLY",True),True)
 forbidden=any(_bool(_get(c,k,False)) for k in ("HENKIA_SHADOW_CAN_CHANGE_RUNTIME","HENKIA_SHADOW_CAN_CHANGE_RETRIEVAL","HENKIA_SHADOW_CAN_CHANGE_RESPONSE"))
 safe=observational and not forbidden
 return {"enabled":requested and safe,"requested_enabled":requested,"observational_only":observational,"safety_lock_passed":safe,"deployment_env":str(_get(c,"HENKIA_DEPLOYMENT_ENV","") or ""),"max_divergences":max(1,min(int(_get(c,"HENKIA_SHADOW_MAX_DIVERGENCES",20) or 20),50))}

def _bytes(v:Any)->int:
 try:return len(json.dumps(v,ensure_ascii=False,separators=(",",":"),default=str).encode("utf-8"))
 except Exception:return 0

def _minimal(r:Mapping[str,Any])->dict:
 keys=("understanding","state_before","state_after","retrieval","answer","answer_context","decision","topic_boundary","entity_frame")
 return {k:deepcopy(r.get(k)) for k in keys if r.get(k) is not None}

def observe_shadow(result:dict,store:dict,message:str,config:Any)->dict:
 cfg=shadow_config(config)
 d={"schema_version":SCHEMA_VERSION,"enabled":cfg["enabled"],"observational_only":True,"production_changed":False,"llm_calls_added":0,"retrieval_calls_added":0,"status":"disabled","safety_lock_passed":cfg["safety_lock_passed"]}
 if not cfg["enabled"]:
  if cfg["requested_enabled"] and not cfg["safety_lock_passed"]:d.update({"status":"blocked_by_safety_lock","error_code":"shadow_mutation_flag_forbidden"})
  result["qa_shadow"]=d;return d
 try:
  ss=store.setdefault(SHADOW_STORE_KEY,{})
  ss["answer_context"]=deepcopy(store.get("answer_context") or {})
  sr=_minimal(result)
  build_shadow_frame(ss,message,sr);enrich_shadow_frame(ss,sr)
  frame=deepcopy(sr.get(STORE_KEY) or {})
  div=deepcopy(sr.get(DIVERGENCE_KEY) or [])[:cfg["max_divergences"]]
  d.update({"status":"observed","frame":frame,"comparison":{"status":"divergence" if div else "match","divergence_count":len(div),"divergences":div}})
  d["serialized_bytes"]=_bytes(d)
 except Exception as exc:
  d.update({"status":"diagnostic_error","error_code":type(exc).__name__,"error_message":str(exc)[:300]})
 result["qa_shadow"]=d;return d

def summarize_shadow_turns(turns:list[dict])->dict:
 rows=[r.get("qa_shadow") or {} for r in turns if isinstance(r,Mapping)]
 observed=[r for r in rows if r.get("status")=="observed"]
 divergent=[r for r in observed if _m(r.get("comparison")).get("status")=="divergence"]
 errors=[r for r in rows if r.get("status")=="diagnostic_error"]
 return {"schema_version":SCHEMA_VERSION,"turns_with_shadow_field":len(rows),"observed_turns":len(observed),"divergent_turns":len(divergent),"matching_turns":len(observed)-len(divergent),"diagnostic_errors":len(errors),"shadow_llm_calls_added":0,"shadow_retrieval_calls_added":0,"production_changed":False,"estimated_shadow_bytes":sum(int(r.get("serialized_bytes") or 0) for r in rows)}
