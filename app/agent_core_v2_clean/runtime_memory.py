from __future__ import annotations
from copy import deepcopy
import json

MAX_RETAINED_TURNS=8
MAX_RETAINED_MESSAGES=18
MAX_AUDIT_TURNS=128
MAX_AUDIT_MESSAGES=256
MAX_ERRORS=12
CACHE_LIMITS={
 "exact_turn_cache":1,
 "retrieval_cache":2,
 "documented_answer_cache":2,
 "procedural_answer_cache":2,
 "internal_knowledge_cache":2,
}
MAX_EVIDENCE_ITEMS=6
MAX_EVIDENCE_TEXT=700
MAX_EXCERPT=900

def _json_bytes(value):
 try:return len(json.dumps(value,ensure_ascii=False,separators=(",",":")).encode("utf-8"))
 except Exception:return 0

def _compact_evidence(item):
 row={k:deepcopy(item.get(k)) for k in ("id","title","source","url","page","origin","stable_id") if item.get(k) not in (None,"")}
 text=" ".join(str(item.get("text") or "").split())
 if text:row["text"]=text[:MAX_EVIDENCE_TEXT]
 sf=item.get("semantic_fit") or {}
 if sf:row["semantic_fit"]={k:deepcopy(sf.get(k)) for k in ("score","matched_terms","title_matched_terms","concept_matches") if sf.get(k) not in (None,[],{})}
 md=item.get("metadata") or {};row["metadata"]={k:deepcopy(md.get(k)) for k in ("canonical_url","source_url","product","vendor","source_type","document_family","title") if md.get(k) not in (None,"")}
 return row

def _compact_retrieval(value):
 r=deepcopy(value or {})
 for key in ("diagnostic_evidence","generation_evidence","evidence"):
  if key in r:r[key]=[_compact_evidence(x) for x in (r.get(key) or [])[:MAX_EVIDENCE_ITEMS]]
 verdict=r.get("evidence_verdict") or {}
 if verdict.get("selected_evidence") is not None:verdict["selected_evidence"]=[_compact_evidence(x) for x in (verdict.get("selected_evidence") or [])[:MAX_EVIDENCE_ITEMS]]
 r["evidence_verdict"]=verdict;r.pop("_answer_context",None);r.pop("_case_context",None)
 return r

def _compact_answer_context(value):
 c=deepcopy(value or {})
 for key in ("cited_evidence","current_answer_cited_evidence","active_document_evidence_ledger"):
  if key in c:c[key]=[_compact_evidence(x) for x in (c.get(key) or [])[:MAX_EVIDENCE_ITEMS]]
 if c.get("main_text_excerpt"):c["main_text_excerpt"]=" ".join(str(c["main_text_excerpt"]).split())[:MAX_EXCERPT]
 c["delivered_guidance"]=[deepcopy(x) for x in (c.get("delivered_guidance") or [])[-10:]]
 return c

def compact_turn(result):
 out=deepcopy(result or {})
 if "retrieval" in out:out["retrieval"]=_compact_retrieval(out.get("retrieval"))
 if "answer_context" in out:out["answer_context"]=_compact_answer_context(out.get("answer_context"))
 plan=out.get("canonical_response_plan") or {}
 if plan:
  out["canonical_response_plan"]={k:deepcopy(plan.get(k)) for k in ("schema_version","response_plan","evidence_plan","diagnostic_plan","validation") if plan.get(k) is not None}
  (out["canonical_response_plan"].get("evidence_plan") or {}).pop("selected_evidence",None)
 trace=out.get("provider_trace") or {}
 for value in trace.values():
  if isinstance(value,dict) and len(str(value.get("text") or ""))>MAX_EXCERPT:value["text"]=str(value["text"])[:MAX_EXCERPT]
 out["provider_trace"]=trace;out["runtime_compaction"]={"policy":"bounded_session_v2","serialized_bytes":_json_bytes(out)}
 return out

def compact_cache_artifact(artifact):
 a=artifact or {};answer=deepcopy(a.get("answer") or {});understanding=a.get("understanding") or {};decision=a.get("decision") or {};context=a.get("answer_context") or {};retrieval=a.get("retrieval") or {};verdict=retrieval.get("evidence_verdict") or {}
 return {
  "answer":answer,
  "understanding":{k:deepcopy(understanding.get(k)) for k in ("intent","user_act","topic_relation","current_goal","canonical_subject","requested_workflow") if understanding.get(k) is not None},
  "decision":{k:deepcopy(decision.get(k)) for k in ("action","reason","ask_one_question","question_target") if decision.get(k) is not None},
  "retrieval":{"evidence_verdict":{k:deepcopy(verdict.get(k)) for k in ("status","mode","accepted","reason","document_ids","evidence_ids","continuity_authority","selection_authority") if verdict.get(k) is not None}},
  "answer_context":{k:deepcopy(context.get(k)) for k in ("goal","source_identities","source_titles","cited_ids","evidence_authority","finish_reason","partial") if context.get(k) is not None},
 }

def _trim_cache(cache,limit):
 if not isinstance(cache,dict):return
 while len(cache)>limit:cache.pop(next(iter(cache)),None)

def _audit_turn(value):
 row=compact_turn(value)
 # Audit exports must preserve causal traces even when runtime memory evicts old turns.
 keep=("input","state_before","understanding","understanding_contract","goal_update_normalization","state_after","decision","answer","retrieval","documented_answer","procedural_answer","internal_knowledge","escalation","provider_trace","turn_metrics","execution","functional_events","error","runtime_compaction","resource_observability","resource_checkpoint_trace","decision_trace","publication_ledger","topic_boundary","entity_frame","qa_shadow","knowledge_comparison")
 return {key:deepcopy(row.get(key)) for key in keep if row.get(key) is not None}

def enforce_runtime_memory_limits(store):
 turns=list(store.get("turns") or [])
 messages=list(store.get("messages") or [])
 evicted_turns=turns[:-MAX_RETAINED_TURNS] if len(turns)>MAX_RETAINED_TURNS else []
 evicted_messages=messages[:-MAX_RETAINED_MESSAGES] if len(messages)>MAX_RETAINED_MESSAGES else []
 if evicted_turns:
  archive=store.setdefault("audit_turns",[]);archive.extend(_audit_turn(x) for x in evicted_turns);store["audit_turns"]=archive[-MAX_AUDIT_TURNS:]
 if evicted_messages:
  archive=store.setdefault("audit_messages",[]);archive.extend(deepcopy(evicted_messages));store["audit_messages"]=archive[-MAX_AUDIT_MESSAGES:]
 store["turns"]=turns[-MAX_RETAINED_TURNS:];store["messages"]=messages[-MAX_RETAINED_MESSAGES:];store["errors"]=(store.get("errors") or [])[-MAX_ERRORS:]
 for name,limit in CACHE_LIMITS.items():_trim_cache(store.setdefault(name,{}),limit)
 store["runtime_memory_diagnostic"]=memory_diagnostic(store);return store

def memory_diagnostic(store):
 caches={name:{"configured_limit":((store.get("cache_metrics") or {}).get("configured_limits") or {}).get(name),"effective_runtime_limit":limit,"entries":len(store.get(name) or {}),"estimated_serialized_bytes":_json_bytes(store.get(name) or {})} for name,limit in CACHE_LIMITS.items()}
 return {"policy":"bounded_session_v2_audited","retained_turns":len(store.get("turns") or []),"retained_messages":len(store.get("messages") or []),"archived_audit_turns":len(store.get("audit_turns") or []),"archived_audit_messages":len(store.get("audit_messages") or []),"turn_bytes":_json_bytes(store.get("turns") or []),"answer_context_bytes":_json_bytes(store.get("answer_context") or {}),"cache_summary":caches,"estimated_store_bytes":_json_bytes({k:v for k,v in store.items() if k!="memory"})}
