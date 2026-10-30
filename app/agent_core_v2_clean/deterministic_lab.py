from __future__ import annotations
from copy import deepcopy
from .models import TurnUnderstanding
from .memory import apply_understanding
from .policy import ConversationPolicy
from .retrieval import RetrievalQueryBuilder,ReadOnlyRetrieval,retrieval_summary

REQUIRED=("user_act","intent","topic_relation","domain_relevance","current_goal")
CACHE_ARTIFACT_FIELDS=("understanding","understanding_contract","goal_update_normalization","decision","answer","retrieval")

def _context_key(message,memory):
 return "|".join((" ".join(str(message).split()).casefold(),str(memory.active_topic or "").strip().casefold(),str(memory.pending_goal.summary or "").strip().casefold()))

def _artifact(result):
 return {key:deepcopy(result.get(key)) for key in CACHE_ARTIFACT_FIELDS}

def _publish_exact_cache(store,message,key_before,result):
 """Publishes a validated zero-LLM semantic artifact in the existing exact-turn cache."""
 if not (result.get("understanding_contract") or {}).get("valid"):return
 entry={"artifact":_artifact(result),"tokens_estimate":0,"source":"deterministic_inline","validated_without_llm":True}
 cache=store.setdefault("exact_turn_cache",{})
 cache[key_before]=entry
 cache[_context_key(message,store["memory"])]=entry

def process_deterministic(message,semantic_input,store):
 """Runs the real downstream pipeline and seeds its exact cache with zero LLM calls."""
 missing=[key for key in REQUIRED if not str(semantic_input.get(key) or "").strip()]
 if missing:raise ValueError("missing_semantic_fields:"+",".join(missing))
 key_before=_context_key(message,store["memory"]);before=deepcopy(store["memory"].to_dict())
 u=TurnUnderstanding(user_act=str(semantic_input["user_act"]),intent=str(semantic_input["intent"]),topic_relation=str(semantic_input["topic_relation"]),domain_relevance=str(semantic_input["domain_relevance"]),current_goal=str(semantic_input["current_goal"]),goal_complete=bool(semantic_input.get("goal_complete",False)),goal_updates=dict(semantic_input.get("goal_updates") or {}),case_updates=list(semantic_input.get("case_updates") or []),needs_clarification=bool(semantic_input.get("needs_clarification",False)),clarification_target=semantic_input.get("clarification_target"),should_retrieve=bool(semantic_input.get("should_retrieve",True)),confidence=1.0,reasoning_summary="explicit_zero_llm_contract",degraded=False)
 decision=ConversationPolicy().decide(u,store["memory"]);apply_understanding(store["memory"],u)
 retrieval={"enabled":False,"llm_called":False,"production_changed":False,"skipped_reason":"decision_does_not_require_retrieval"};answer="Turno procesado sin LLM."
 if decision.action in {"defer_to_retrieval","diagnose_with_retrieval"}:
  builder=RetrievalQueryBuilder();built=builder.build(message,store["memory"],u);current=builder.current_only(message,u);cache=store.setdefault("retrieval_cache",{});cached=cache.get(built.fingerprint)
  if cached:retrieval=deepcopy(cached);retrieval["cache_hit"]=True
  else:retrieval=ReadOnlyRetrieval(k=6).search(built,current);retrieval["cache_hit"]=False;cache[built.fingerprint]=deepcopy(retrieval)
  answer=retrieval_summary(retrieval)
 elif decision.action=="diagnose":answer="Caso actualizado sin LLM. Revisa el estado y la decisión diagnóstica."
 elif decision.action=="redirect_scope":answer="Consulta fuera del alcance configurado. El estado anterior se conserva."
 result={"input":message,"state_before":before,"understanding":u.to_dict(),"understanding_contract":{"valid":True,"source":"explicit_zero_llm_contract"},"goal_update_normalization":{"removed_goal_update_keys":[],"source":"explicit_zero_llm_contract"},"decision":decision.to_dict(),"state_after":deepcopy(store["memory"].to_dict()),"answer":{"text":answer,"mode":"deterministic_inline","knowledge_used":False},"retrieval":retrieval,"provider_trace":{"understanding":{"skipped":True,"reason":"deterministic_inline"},"response":{"skipped":True,"reason":"deterministic_inline"}},"turn_metrics":{"calls":0,"prompt_tokens":0,"completion_tokens":0,"total_tokens":0,"provider_failed_calls":0,"contract_failed_calls":0,"functional_failed_calls":0},"execution":{"mode":"deterministic","llm_calls":0,"tokens":0,"published_to_exact_cache":True},"cache":{"hit":False,"type":None,"published":True,"source":"deterministic_inline"},"production_changed":False}
 _publish_exact_cache(store,message,key_before,result)
 store["messages"] += [{"role":"user","content":message},{"role":"assistant","content":answer}];store["turns"].append(result)
 return result
