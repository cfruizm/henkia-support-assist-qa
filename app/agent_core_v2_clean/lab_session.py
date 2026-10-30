# Export lineage retained for regression discovery: henkia_support_assist_4b1_9
# Regression lineage: agent_core_v2_clean_phase4a3_9_10_2_compound_attempt_preservation
# Regression lineage: agent_core_v2_clean_phase4a3_9_10_degraded_terminal_arbitration_scoped_negative_claims
# Regression lineage: agent_core_v2_clean_phase4a3_9_9_cumulative_document_evidence_safe_negative_block_repair
# Regression lineage: agent_core_v2_clean_phase4a3_9_4_visible_terminal_truncation_recovery
from copy import deepcopy
import json
import secrets
import hashlib
from app.llm_gateway.config import load_gateway_config
from app.llm_gateway.gateway import LLMGateway, reset_gateway_session
from .models import ConversationMemory
from .understanding import ConversationUnderstanding
from .policy import ConversationPolicy
from .response import NaturalResponseComposer
from .agent import CleanConversationalAgent
from .telemetry import empty, normalize, add_result, snapshot
from .budget import BudgetPolicy
from .budget_fallback import build_budget_fallback
from .retrieval import RetrievalQueryBuilder, ReadOnlyRetrieval, retrieval_summary
from .documented_answer import DocumentedAnswerComposer, answer_fingerprint, PROMPT_VERSION
from .documented_router import maybe_generate_procedural
from .documented_fallback import build_documented_fallback
from .conceptual_route import must_preempt_documented_answer
from .semantic_fit import apply_semantic_fit, capture_answer_context
from .guidance_action_filter import sanitize_answer_context
from .runtime_memory import compact_turn, compact_cache_artifact, enforce_runtime_memory_limits, memory_diagnostic
from .resource_observability import begin_turn, finalize_turn, export_diagnostic
from .token_observability import turn_diagnostic as token_turn_diagnostic, session_diagnostic as token_session_diagnostic
from .diagnostic_manifest import build_diagnostic_manifest
from .unified_evidence_authority import apply_unified_evidence_verdict
from .exact_document_switch import reconcile_exact_document_switch
from .visible_answer import format_visible_answer
from .decision_observability import attach_retrieval
from .response_reconciler import reconcile
from .topic_boundary import infer_topic_boundary
from .operational_coherence import normalize_generation_flags
from .documentation_limitation import classify as classify_documentation_limitation
from .escalation_coordinator import start as start_escalation, handle as handle_escalation
from .workflow_understanding import WorkflowInterpreter
from .escalation_export import build_export as build_escalation_export, build_text as build_escalation_text
from .cache_limits import enforce_cache_limits
from .document_continuity import continuity_authority
from .intent_reconciliation import reconcile_procedural_intent

KEY = "agent_core_v2_clean_store"

def _safe_text(value):
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, list):
        return " ".join(_safe_text(x) for x in value if _safe_text(x))
    if isinstance(value, dict):
        for key in ("summary", "subject", "operation", "product", "value", "text"):
            if key in value and value.get(key) is not None:
                return _safe_text(value.get(key))
        return ""
    return str(value)

def _stabilize_memory_text(memory):
    memory.active_topic = _safe_text(getattr(memory, "active_topic", None)) or None
    goal = getattr(memory, "pending_goal", None)
    if goal is not None:
        goal.summary = _safe_text(getattr(goal, "summary", ""))
        if hasattr(goal, "missing_detail"):
            goal.missing_detail = _safe_text(getattr(goal, "missing_detail", "")) or None
    memory.last_assistant_question = _safe_text(getattr(memory, "last_assistant_question", None)) or None
    return memory

def _context_key(message, memory):
    return "|".join((" ".join(_safe_text(message).split()).casefold(), _safe_text(memory.active_topic).strip().casefold(), _safe_text(memory.pending_goal.summary).strip().casefold()))

def _artifact(result):
    artifact={k: deepcopy(result.get(k)) for k in ("understanding", "understanding_contract", "goal_update_normalization", "decision", "answer", "retrieval", "documented_answer", "procedural_answer", "internal_knowledge", "procedural_recovery", "answer_context")}
    return compact_cache_artifact(artifact)

def _zero():
    return {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "provider_failed_calls": 0, "contract_failed_calls": 0, "functional_failed_calls": 0}

def _workflow_turn_metrics(trace,contract_valid):
    trace=dict(trace or {})
    if not trace or trace.get("skipped"):
        return _zero()
    usage=trace.get("usage") or {}
    return {"calls":1,"prompt_tokens":int(usage.get("prompt_tokens") or 0),"completion_tokens":int(usage.get("completion_tokens") or 0),"total_tokens":int(usage.get("total_tokens") or 0),"provider_failed_calls":0 if trace.get("ok") else 1,"contract_failed_calls":0 if contract_valid else 1,"functional_failed_calls":0 if contract_valid else 1}

def get_store(s):
    if KEY not in s:
        s[KEY] = {"session_id": secrets.token_hex(12), "memory": ConversationMemory(), "messages": [], "turns": [], "audit_messages": [], "audit_turns": [], "errors": [], "telemetry": empty(), "budget": BudgetPolicy.for_mode("normal").to_dict(), "deterministic_results": [], "exact_turn_cache": {}, "retrieval_cache": {}, "documented_answer_cache": {}, "procedural_answer_cache": {}, "cache_metrics": {}, "answer_context": {}}
    x = s[KEY]
    x["memory"] = _stabilize_memory_text(x.get("memory") or ConversationMemory())
    x["telemetry"] = normalize(x.get("telemetry"))
    for k in ("exact_turn_cache", "retrieval_cache", "documented_answer_cache", "procedural_answer_cache"):
        x.setdefault(k, {})
    x.setdefault("answer_context", {})
    x.setdefault("cache_metrics", {})
    for k in ("hits", "calls_avoided", "tokens_avoided_estimate", "retrieval_hits", "documented_answer_hits", "procedural_answer_hits", "internal_knowledge_hits"):
        x["cache_metrics"].setdefault(k, 0)
    for k, d in (("deterministic_results", []), ("errors", []), ("turns", []), ("messages", []), ("audit_turns", []), ("audit_messages", [])):
        x.setdefault(k, d)
    enforce_cache_limits(x)
    enforce_runtime_memory_limits(x)
    return x

def reset_store(s):
    reset_gateway_session(s)
    s.pop(KEY, None)
    return get_store(s)

def _gateway(secrets_obj, s):
    return LLMGateway(load_gateway_config(secrets_obj), s)

def _configure_budget(store, secrets_obj):
    current_mode=str((store.get("budget") or {}).get("mode") or "normal")
    policy, diagnostic=BudgetPolicy.from_runtime(secrets_obj, mode=current_mode)
    store["budget"]=policy.to_dict()
    store["budget_configuration"]={
        **diagnostic,
        "effective":policy.to_dict(),
    }
    return policy

def build_agent(secrets_obj, s, budget):
    g = _gateway(secrets_obj, s)
    return CleanConversationalAgent(ConversationUnderstanding(g, budget.understanding_max_tokens), ConversationPolicy(), NaturalResponseComposer(g, budget.response_max_tokens, lambda: (s.get(KEY) or {}).get("answer_context") or {}))

def _attach_retrieval(result, message, store):
    if (result.get("decision") or {}).get("action") not in {"defer_to_retrieval", "diagnose_with_retrieval"}:
        return result
    try:
        u = type("U", (), result.get("understanding") or {})()
        builder = RetrievalQueryBuilder()
        # Topic boundary is the effective authority for retrieval. It must be
        # resolved before query construction so a subject switch cannot inherit
        # symptoms, scope or escalation facts from the previous case.
        boundary = infer_topic_boundary(result.get("state_before") or {}, result.get("understanding") or {})
        query = builder.build(message, store["memory"], u, effective_topic_relation=boundary.relation)
        current = builder.current_only(message, u)
        current.fields["topic_relation"] = boundary.relation
        current.fields["model_topic_relation"] = (result.get("understanding") or {}).get("topic_relation")
        current.fields["query_isolation"] = "new_topic" if boundary.relation == "new_topic" else "current_turn_only"
        continuity = continuity_authority(result.get("understanding") or {}, boundary.to_dict(), store.get("answer_context") or {})
        raw_preferred_sources = continuity.get("preferred_sources") or []
        preferred_sources=[]
        for item in raw_preferred_sources:
            if isinstance(item,dict):
                value=item.get("source") or item.get("url") or item.get("identity") or (item.get("metadata") or {}).get("canonical_url")
            else:
                value=item
            value=str(value or "").strip()
            if value and value not in preferred_sources:preferred_sources.append(value)
        source_key = "|".join(preferred_sources)
        cache_key = query.fingerprint + (":" + hashlib.sha256(source_key.encode()).hexdigest()[:12] if source_key else "")
        cached = store["retrieval_cache"].get(cache_key)
        if cached:
            raw = deepcopy(cached)
            raw["cache_hit"] = True
            store["cache_metrics"]["retrieval_hits"] += 1
        else:
            raw = ReadOnlyRetrieval(k=6).search(query, current, preferred_sources=preferred_sources)
            raw["cache_hit"] = False
            store["retrieval_cache"][cache_key] = deepcopy(raw)
        result, exact_switch = reconcile_exact_document_switch(result, raw, message, store)
        if exact_switch.get("applied"):
            boundary = infer_topic_boundary(result.get("state_before") or {}, result.get("understanding") or {})
            continuity = continuity_authority(result.get("understanding") or {}, boundary.to_dict(), {})
            raw["exact_document_switch"] = deepcopy(exact_switch)
        result["topic_boundary"] = boundary.to_dict()
        result["document_continuity"] = {k:v for k,v in continuity.items() if k != "answer_context"}
        raw.setdefault("query", {}).setdefault("fields", {})["topic_relation"] = boundary.relation
        raw["query"]["fields"]["previous_evidence_role"] = continuity.get("previous_evidence_role") or boundary.previous_evidence_role
        raw["query"]["fields"]["user_act"] = (result.get("understanding") or {}).get("user_act")
        answer_context = continuity.get("answer_context") or {}
        # Context must be present before semantic fit and evidence authority execute.
        # Both stages treat it as structured authority, never as a replacement for relevance.
        raw["_answer_context"] = deepcopy(answer_context)
        retrieval = apply_semantic_fit(raw, answer_context)
        retrieval["_answer_context"] = deepcopy(answer_context)
        retrieval = apply_unified_evidence_verdict(retrieval, message, result.get("understanding") or {})
        retrieval["documentation_limitation"]=classify_documentation_limitation(retrieval)
        retrieval["_answer_context"] = deepcopy(answer_context)
        escalation_closed=str(getattr(store["memory"].escalation,"status","") or "").casefold() in {"completed","cancelled"}
        retrieval["_case_context"] = {
            "attempts": [] if escalation_closed else deepcopy(getattr(store["memory"].support_case,"attempts",[]) or []),
            "historical_attempts": deepcopy(getattr(store["memory"].support_case,"attempts",[]) or []) if escalation_closed else [],
            "observations": [] if escalation_closed else deepcopy(getattr(store["memory"].support_case,"observations",[]) or []),
            "affected_scope": None if escalation_closed else getattr(store["memory"].support_case,"affected_scope",None),
            "case_context_authority": "historical" if escalation_closed else "active",
        }
        retrieval["pre_retrieval_boundary"] = boundary.to_dict()
        retrieval = attach_retrieval(result, retrieval, message)
    except Exception as exc:
        retrieval = {"enabled": True, "ok": False, "llm_called": False, "production_changed": False, "count": 0, "evidence": [], "errors": [{"type": type(exc).__name__, "message": str(exc)}]}
    result["retrieval"] = retrieval
    result["answer"]["text"] = retrieval_summary(retrieval)
    result["answer"]["mode"] = "retrieval_diagnostic" if retrieval.get("ok") else "retrieval_error"
    return result

def _conceptual(result, message, secrets_obj, s, budget, store):
    if (result.get("decision") or {}).get("action") not in {"defer_to_retrieval", "diagnose_with_retrieval"}:
        return result, {"skipped": True, "reason": "decision_does_not_authorize_retrieval"}
    retrieval = result.get("retrieval") or {}
    understanding = result.get("understanding") or {}
    verdict = retrieval.get("evidence_verdict") or {}
    if not retrieval.get("ok") or not retrieval.get("evidence") or not verdict.get("accepted"):
        return result, None
    model = str(getattr(load_gateway_config(secrets_obj), "model", "") or "")
    key = answer_fingerprint(message, understanding, retrieval, model)
    cached = store["documented_answer_cache"].get(key)
    if cached:
        result["answer"] = deepcopy(cached["answer"])
        result["documented_answer"] = {**deepcopy(cached["diagnostic"]), "cache_hit": True}
        store["cache_metrics"]["documented_answer_hits"] += 1
        return result, {"skipped": True, "reason": "documented_answer_cache"}
    allowed, _ = budget.can_call(store["telemetry"], estimated_tokens=1100)
    if not allowed:
        return result, None
    intent = str(understanding.get("intent") or "").casefold()
    composer = DocumentedAnswerComposer(_gateway(secrets_obj, s), 760 if intent == "requirements" else 620 if intent == "conceptual" else 640)
    answer = composer.compose(message, understanding, retrieval)
    payload = answer.to_dict()
    payload.update({"documented_evidence_used": answer.mode in {"documented_answer", "documented_answer_partial"}, "internal_knowledge_used": False, "knowledge_mode": "documented_only" if answer.mode in {"documented_answer", "documented_answer_partial"} else "none"})
    result["answer"] = payload
    diagnostic = {"enabled": True, "cache_hit": False, "prompt_version": PROMPT_VERSION, "quality_budget_preserved": True, "semantic_fit": retrieval.get("semantic_fit"), "validation": deepcopy(composer.validation or {})}
    result["documented_answer"] = diagnostic
    if answer.mode in {"documented_answer", "documented_answer_partial"}:
        store["memory"].pending_goal.status = "complete" if answer.mode == "documented_answer" else "partially_answered"
        result["state_after"] = deepcopy(store["memory"].to_dict())
        if answer.mode == "documented_answer":
            store["documented_answer_cache"][key] = {"answer": deepcopy(payload), "diagnostic": deepcopy(diagnostic)}
    return result, composer.last_provider_result

def _answers(result, message, secrets_obj, s, budget, store):
    result=reconcile_procedural_intent(result,store)
    if (result.get("decision") or {}).get("action") not in {"defer_to_retrieval", "diagnose_with_retrieval"}:
        skipped={"skipped":True,"reason":"decision_does_not_authorize_retrieval"};return result,skipped,skipped
    retrieval=result.get("retrieval") or {};verdict=retrieval.get("evidence_verdict") or {};documented_trace={"skipped":True,"reason":"documented_answer_not_called"}
    understanding=result.get("understanding") or {}
    # Procedural requests have a dedicated composer with ordered-stage and safety
    # contracts. Running the generic documented composer first made that generic
    # answer terminal and silently suppressed the procedural path.
    if understanding.get("intent")=="procedural":
        result,procedural_trace=maybe_generate_procedural(result,message,_gateway(secrets_obj,s),budget,store,str(getattr(load_gateway_config(secrets_obj),"model","") or ""))
        result.setdefault("functional_events",[]).append({"type":"procedural_route_authority","winner":"procedural_composer","suppressed":"generic_documented_composer","reason":"explicit_procedural_intent"})
        return result,{"skipped":True,"reason":"procedural_intent_uses_dedicated_composer"},procedural_trace
    if verdict.get("accepted") and retrieval.get("generation_evidence"):
        result,documented_trace=_conceptual(result,message,secrets_obj,s,budget,store)
        answer_mode = str((result.get("answer") or {}).get("mode") or "")
        provider_completed = bool((documented_trace or {}).get("ok"))
        documented_terminal = answer_mode in {
            "documented_answer", "documented_answer_partial",
            "documented_truncation_safe_defer",
        }
        # Accepted evidence plus a completed documented-provider call is terminal.
        # Validation and deterministic repair belong to the documented composer;
        # a second large composer may not overwrite, contradict, or rate-limit it.
        if documented_terminal or (provider_completed and verdict.get("accepted") and answer_mode.startswith("documented_")):
            result.setdefault("functional_events",[]).append({
                "type":"terminal_answer_arbitration",
                "winner":"single_documented_composer",
                "suppressed":"procedural_composer",
                "reason":"accepted_evidence_completed_documented_attempt_is_terminal",
            })
            return result,documented_trace,{"skipped":True,"reason":"authorized_documented_answer_is_terminal"}
        # Accepted documentary evidence remains authoritative when its composer is
        # temporarily unavailable. Do not spend a second large generation call.
        provider_failed = (documented_trace or {}).get("ok") is False
        provider_error = str((documented_trace or {}).get("error_code") or "").casefold()
        transient_failure = provider_failed and provider_error in {
            "rate_limited", "timeout", "provider_unavailable", "service_unavailable",
            "provider_error", "upstream_unavailable",
        }
        if transient_failure and verdict.get("accepted"):
            fallback = build_documented_fallback(retrieval, reason=provider_error or "provider_degraded")
            if fallback:
                result["answer"] = fallback
                result["documented_answer"] = {
                    **dict(result.get("documented_answer") or {}),
                    "provider_degraded": True,
                    "deterministic_fallback_used": True,
                    "secondary_composer_suppressed": True,
                }
                result.setdefault("functional_events", []).append({
                    "type": "degraded_terminal_arbitration",
                    "winner": "deterministic_documented_fallback",
                    "suppressed": "procedural_composer",
                    "reason": "accepted_documented_evidence_provider_failure_no_secondary_composer",
                })
                return result, documented_trace, {
                    "skipped": True,
                    "reason": "accepted_documented_evidence_provider_failure_no_secondary_composer",
                }
    u=result.get("understanding") or {};decision=result.get("decision") or {}
    active_case_followup=(decision.get("action")=="diagnose_with_retrieval" and u.get("user_act") in {"follow_up","request_elaboration","answer_to_question","attempt_result"} and u.get("topic_relation") in {"same_topic","return_to_previous"})
    if active_case_followup and u.get("intent")=="conceptual":
        u=dict(u);u["intent"]="troubleshooting";result["understanding"]=u
        result.setdefault("functional_events",[]).append({"type":"active_case_followup_route_recovered","from_intent":"conceptual","to_intent":"troubleshooting","reason":"diagnostic_followup_requires_operational_grounding"})
    result,procedural_trace=maybe_generate_procedural(result,message,_gateway(secrets_obj,s),budget,store,str(getattr(load_gateway_config(secrets_obj),"model","") or ""))
    if not documented_trace or documented_trace.get("skipped"):
        documented_trace={"skipped":True,"reason":"no_terminal_documented_answer"}
    return result,documented_trace,procedural_trace

def _trace_list(value):
    if not value:
        return []
    return [x for x in (value if isinstance(value, list) else [value]) if x]

def _apply_answer_traces(result, conceptual, procedural, store):
    traces = _trace_list(conceptual) + _trace_list(procedural)
    result.setdefault("provider_trace", {}).update({"documented_answer": conceptual or {"skipped": True, "reason": "documented_answer_not_called"}, "procedural_answer": procedural or {"skipped": True, "reason": "procedural_answer_not_called"}})
    recorded = []
    for trace in traces:
        if trace.get("skipped"):
            continue
        attempts = trace.get("attempts") or []
        if attempts:
            for attempt in attempts:
                add_result(store["telemetry"], attempt)
                recorded.append(attempt)
        else:
            add_result(store["telemetry"], trace)
            recorded.append(trace)
    return recorded

def _combined_turn_metrics(base_traces, generated_traces):
    def expand(trace):
        if not trace or trace.get("skipped"): return []
        nested=[trace.get("initial"),trace.get("repair")]
        return [x for x in nested if x and not x.get("skipped")] if any(nested) else [trace]
    items=[]
    for trace in list(base_traces or [])+list(generated_traces or []): items.extend(expand(trace))
    out = _zero()
    out["calls"] = len(items)
    for item in items:
        usage = item.get("usage") or {}
        for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
            out[key] += int(usage.get(key, 0) or 0)
        if item.get("ok") is False:
            out["provider_failed_calls"] += 1
    return out

def _cacheable_final(result):
    answer = result.get("answer") or {}
    return answer.get("mode") in {"documented_answer", "procedural_documented_answer", "controlled_internal_knowledge"} and str(answer.get("finish_reason") or "").casefold() not in {"length", "max_tokens"}

def _finalize_answer_context(result, store):
    understanding=result.get("understanding") or {}
    social_turn=str(understanding.get("intent") or "").casefold()=="social" or str(understanding.get("user_act") or "").casefold()=="social"
    if social_turn:
        # Social turns are visible conversation events, not new technical answers. Preserve the
        # previous documentary authority, evidence ledger and pending technical question intact.
        preserved=deepcopy(store.get("answer_context") or {})
        result["answer_context"]=preserved
        result["social_context"]={"preserved_previous_answer_context":True,"response_mode":"deterministic_social"}
        result["state_after"]=deepcopy(store["memory"].to_dict())
        return
    case_history_turn=str(understanding.get("intent") or "").casefold()=="case_history" or str((result.get("answer") or {}).get("mode") or "").casefold()=="deterministic_case_history"
    if case_history_turn:
        preserved=deepcopy(store.get("answer_context") or {})
        result["answer_context"]=preserved
        result["case_history_context"]={"preserved_previous_answer_context":True,"captured_as_new_guidance":False,"response_mode":"deterministic_case_history"}
        store["memory"].last_assistant_question=None
        result["state_after"]=deepcopy(store["memory"].to_dict())
        return
    context = sanitize_answer_context(capture_answer_context(result, store.get("answer_context") or {}))
    if context:
        store["answer_context"] = context
        result["answer_context"] = deepcopy(context)
        store["memory"].last_assistant_question = context.get("closing_question") or None
        result["state_after"] = deepcopy(store["memory"].to_dict())

def _escalation_result(message, store, handled, before):
    store["memory"].turn_number += 1
    text=handled.get("text") or ""
    status=handled.get("status")
    pending=handled.get("pending_field")
    store["memory"].last_assistant_question=text if status=="collecting" and pending else None
    store["memory"].pending_goal.status="complete" if status in {"completed","cancelled"} else "waiting_user" if status=="collecting" else "active"
    store["answer_context"]={"answer_mode":handled.get("mode","escalation"),"goal":"Preparar escalamiento estructurado","main_text_excerpt":" ".join(text.split())[:1000],"closing_question":text if status=="collecting" and pending else None,"source_identities":[],"source_titles":[x.get("title") for x in store["memory"].escalation.sources_consulted if x.get("title")],"cited_ids":[],"cited_evidence":[],"finish_reason":"deterministic","partial":False}
    data={"input":message,"state_before":before,"understanding":{"user_act":"escalation","intent":"escalation","topic_relation":"same_topic","domain_relevance":"in_scope","current_goal":"Preparar escalamiento estructurado","goal_complete":handled.get("status") in {"completed","cancelled"},"goal_updates":{},"case_updates":[],"needs_clarification":handled.get("status")=="collecting","clarification_target":handled.get("pending_field"),"should_retrieve":False,"confidence":1.0,"reasoning_summary":"native_escalation_lifecycle"},"understanding_contract":{"valid":True,"source":"native_escalation"},"decision":{"action":"continue_escalation","reason":"native_escalation_lifecycle","ask_one_question":handled.get("status")=="collecting","question_target":handled.get("pending_field")},"answer":{"text":text,"mode":handled.get("mode","escalation"),"knowledge_used":False},"retrieval":{"enabled":False,"skipped_reason":"native_escalation_lifecycle"},"escalation":{"status":handled.get("status"),"pending_field":handled.get("pending_field"),"state":deepcopy(store["memory"].escalation.to_dict()),"export":deepcopy(handled.get("export"))},"state_after":deepcopy(store["memory"].to_dict()),"provider_trace":{"understanding":{"skipped":True,"reason":"native_escalation"},"response":{"skipped":True,"reason":"native_escalation"}},"turn_metrics":_zero(),"execution":{"mode":"deterministic_escalation","llm_calls":0,"tokens":0},"production_changed":False}
    store["messages"] += [{"role":"user","content":message},{"role":"assistant","content":text}];store["turns"].append(compact_turn(data))
    enforce_runtime_memory_limits(store)
    return data

def _apply_visual_format(result):
    answer=(result or {}).get("answer") or {};text=answer.get("text")
    if not isinstance(text,str) or not text.strip():return result
    formatted,diagnostic=format_visible_answer(text,answer.get("mode"),answer.get("knowledge_mode"),answer.get("finish_reason"))
    answer["text"]=formatted;answer["visual_presentation"]=diagnostic;result["answer"]=answer
    result.setdefault("functional_events",[]).append({"type":"visible_answer_formatted",**diagnostic})
    return result

def process_message(message, secrets_obj, s):
    store = get_store(s)
    resource_before = begin_turn(store)
    cache_overrides={
        "exact_turn_cache":getattr(secrets_obj,"get",lambda *_:None)("AGENT_CORE_EXACT_CACHE_MAX_ENTRIES",8),
        "retrieval_cache":getattr(secrets_obj,"get",lambda *_:None)("AGENT_CORE_RETRIEVAL_CACHE_MAX_ENTRIES",8),
        "documented_answer_cache":getattr(secrets_obj,"get",lambda *_:None)("AGENT_CORE_DOCUMENTED_CACHE_MAX_ENTRIES",8),
        "procedural_answer_cache":getattr(secrets_obj,"get",lambda *_:None)("AGENT_CORE_PROCEDURAL_CACHE_MAX_ENTRIES",6),
        "internal_knowledge_cache":getattr(secrets_obj,"get",lambda *_:None)("AGENT_CORE_INTERNAL_CACHE_MAX_ENTRIES",6),
    }
    resource_guard=enforce_cache_limits(store,cache_overrides)
    budget = _configure_budget(store, secrets_obj)
    memory_before = deepcopy(store["memory"])
    before = deepcopy(store["memory"].to_dict())
    if store["memory"].escalation.status in {"collecting","review","suspended","completed","cancelled"}:
        wi=WorkflowInterpreter(_gateway(secrets_obj,s),96);wu=wi.interpret(message,store["memory"].escalation);add_result(store["telemetry"],wi.last_provider_result,wi.contract_valid)
        handled=handle_escalation(store["memory"].escalation,message,store["memory"],wu,store.get("answer_context") or {})
        if handled.get("handled"):
            result=_escalation_result(message,store,handled,before);result["workflow_understanding"]=wu.to_dict();result["workflow_contract"]={"valid":wi.contract_valid,"source":"dedicated_workflow_interpreter"};result["provider_trace"]["workflow_understanding"]=wi.last_provider_result
            result["turn_metrics"]=_workflow_turn_metrics(wi.last_provider_result,wi.contract_valid)
            workflow_calls=int(result["turn_metrics"].get("calls") or 0)
            result["execution"]={"mode":"deterministic_escalation" if workflow_calls==0 else "semantic_escalation","llm_calls":workflow_calls,"workflow_budget_tokens":0 if workflow_calls==0 else 96}
            finalize_turn(store,result,resource_before)
            if store.get("turns"):
                store["turns"][-1]=compact_turn(result)
            enforce_runtime_memory_limits(store)
            return result
        if handled.get("answer_independent"):before=deepcopy(store["memory"].to_dict())
    key = _context_key(message, store["memory"])
    cached = store["exact_turn_cache"].get(key)
    execution = {"mode": budget.mode, "understanding_budget": budget.understanding_max_tokens, "response_budget": budget.response_max_tokens, "resource_guard":resource_guard}
    if cached:
        store["memory"].turn_number += 1
        result = {"input": message, "state_before": before, **deepcopy(cached["artifact"]), "state_after": deepcopy(store["memory"].to_dict()), "provider_trace": {"understanding": {"skipped": True, "reason": "exact_turn_cache"}, "response": {"skipped": True, "reason": "exact_turn_cache"}}, "execution": {**execution, "cache_hit": True}, "cache": {"hit": True, "type": "exact_turn"}, "production_changed": False}
        if (result.get("decision") or {}).get("action")=="offer_escalation":
            conceptual={"skipped":True,"reason":"native_escalation"};procedural={"skipped":True,"reason":"native_escalation"}
        else:
            result, conceptual, procedural = _answers(result, message, secrets_obj, s, budget, store)
        traces = _apply_answer_traces(result, conceptual, procedural, store)
        result["turn_metrics"] = _combined_turn_metrics([], traces)
        result = reconcile(result, store["memory"])
        result = normalize_generation_flags(result)
        result = _apply_visual_format(result)
        _finalize_answer_context(result, store)
        result["session_metrics_after_turn"] = snapshot(store["telemetry"])
        text = result["answer"]["text"]
        store["cache_metrics"]["hits"] += 1
        store["cache_metrics"]["calls_avoided"] += 1
        store["messages"] += [{"role": "user", "content": message}, {"role": "assistant", "content": text}]
        store["turns"].append(compact_turn(result))
        enforce_runtime_memory_limits(store)
        return result
    allowed, block_reason = budget.can_call(store["telemetry"])
    if not allowed:
        status=budget.status(store["telemetry"])
        answer=build_budget_fallback(message,store["memory"],answer_context=store.get("answer_context") or {},budget_status=status)
        result={"input":message,"blocked":True,"answer":answer,"budget_status":status,"budget_configuration":deepcopy(store.get("budget_configuration") or {}),"turn_metrics":_zero(),"execution":{**execution,"budget_block_reason":block_reason},"production_changed":False}
        store["messages"] += [{"role":"user","content":message},{"role":"assistant","content":answer["text"]}]
        result["turn_metrics"]["token_observability"]=token_turn_diagnostic(result,store)
        store["turns"].append(compact_turn(result));enforce_runtime_memory_limits(store);finalize_turn(store,result,resource_before)
        if store.get("turns"):store["turns"][-1]=compact_turn(result)
        return result
    store["messages"].append({"role": "user", "content": message})
    try:
        result = build_agent(secrets_obj, s, budget).process(message, store["memory"], store.get("answer_context") or {})
        degraded=bool((result.get("understanding") or {}).get("degraded"))
        degraded_reason=str((result.get("understanding") or {}).get("reasoning_summary") or "")
        safe_degraded_contract=degraded and degraded_reason.startswith("deterministic_degraded_contract:")
        if degraded and not safe_degraded_contract:
            # Only unresolved degraded turns are rolled back. A bounded deterministic
            # contract has already isolated the current topic and is safe to ground.
            store["memory"] = memory_before
            result["state_after"] = deepcopy(store["memory"].to_dict())
            result.setdefault("functional_events", []).append({"type":"degraded_understanding_memory_rollback","reason":"provider_contract_invalid_without_safe_deterministic_contract"})
        elif safe_degraded_contract:
            result.setdefault("functional_events", []).append({"type":"deterministic_degraded_contract_retained","reason":"bounded_current_turn_or_pending_question_contract"})
        if (result.get("decision") or {}).get("action")=="offer_escalation":
            handled=start_escalation(store["memory"].escalation,store["memory"],store.get("answer_context") or {},"Solicitud explícita del usuario")
            text=handled.get("text") or ""
            result["answer"]={"text":text,"mode":handled.get("mode","escalation_collecting"),"knowledge_used":False}
            result["escalation"]={"status":handled.get("status"),"pending_field":handled.get("pending_field"),"state":deepcopy(store["memory"].escalation.to_dict())}
            result["state_after"]=deepcopy(store["memory"].to_dict())
        if (result.get("decision") or {}).get("action")!="offer_escalation":
            result = _attach_retrieval(result, message, store)
        base = result.get("provider_trace") or {}
        contract = (result.get("understanding_contract") or {}).get("valid")
        add_result(store["telemetry"], base.get("understanding"), contract)
        add_result(store["telemetry"], base.get("response"))
        result, conceptual, procedural = _answers(result, message, secrets_obj, s, budget, store)
        traces = _apply_answer_traces(result, conceptual, procedural, store)
        base_traces = [x for x in (base.get("understanding"), base.get("response")) if x and not x.get("skipped")]
        result["turn_metrics"] = _combined_turn_metrics(base_traces, traces)
        result["budget_status"]=budget.status(store["telemetry"])
        result["budget_configuration"]=deepcopy(store.get("budget_configuration") or {})
        result = reconcile(result, store["memory"])
        result = normalize_generation_flags(result)
        result = _apply_visual_format(result)
        _finalize_answer_context(result, store)
        result["session_metrics_after_turn"] = snapshot(store["telemetry"])
        result["execution"] = {**execution, "cache_hit": False}
        result["cache"] = {"hit": False}
        text = result["answer"]["text"]
        if contract and _cacheable_final(result):
            entry = {"artifact": _artifact(result), "tokens_estimate": result["turn_metrics"].get("total_tokens", 0)}
            store["exact_turn_cache"][key] = entry
            store["exact_turn_cache"][_context_key(message, store["memory"])] = entry
    except Exception as exc:
        store["memory"] = memory_before
        store["errors"].append({"turn": store["memory"].turn_number + 1, "message": message, "error_type": type(exc).__name__, "error": str(exc)})
        status=budget.status(store["telemetry"])
        budget_exception=status.get("state") in {"reserve_protected","exhausted"} or "límite de tokens" in str(exc).casefold() or "budget" in str(exc).casefold()
        if budget_exception:
            answer=build_budget_fallback(message,store["memory"],answer_context=store.get("answer_context") or {},budget_status={**status,"exception_type":type(exc).__name__})
            text=answer["text"]
            result={"input":message,"blocked":True,"answer":answer,"budget_status":status,"budget_configuration":deepcopy(store.get("budget_configuration") or {}),"error":{"type":type(exc).__name__,"message":str(exc),"controlled":True},"execution":{**execution,"budget_exception_recovered":True},"production_changed":False}
        else:
            text = "No pude procesar este turno. El error quedó registrado."
            result = {"input": message, "error": {"type": type(exc).__name__, "message": str(exc)}, "execution": execution, "production_changed": False}
    store["messages"].append({"role": "assistant", "content": text})
    metrics=result.setdefault("turn_metrics",_zero())
    metrics["token_observability"]=token_turn_diagnostic(result,store)
    store["turns"].append(compact_turn(result))
    enforce_runtime_memory_limits(store)
    finalize_turn(store,result,resource_before)
    if store.get("turns"):
        store["turns"][-1]=compact_turn(result)
    enforce_runtime_memory_limits(store)
    return result

def export_session(s):
    x = get_store(s)
    exported_messages = deepcopy((x.get("audit_messages") or []) + (x.get("messages") or []))
    exported_turns = deepcopy((x.get("audit_turns") or []) + (x.get("turns") or []))
    payload = {"format": "henkia_support_assist_4c4_audited_session_v1", "session_id": x.get("session_id"), "gateway_budget": {"calls": int(s.get("llm_gateway_calls", 0)), "tokens": int(s.get("llm_gateway_tokens", 0))}, "messages": exported_messages, "turns": exported_turns, "audit_retention": {"complete_for_current_session": True, "archived_turns": len(x.get("audit_turns") or []), "recent_runtime_turns": len(x.get("turns") or []), "exported_turns": len(exported_turns)}, "state": x["memory"].to_dict(), "answer_context": deepcopy(x.get("answer_context") or {}), "budget": deepcopy(x["budget"]), "budget_configuration": deepcopy(x.get("budget_configuration") or {}), "telemetry": snapshot(x["telemetry"]), "cache_metrics": deepcopy(x["cache_metrics"]), "runtime_memory": memory_diagnostic(x), "errors": deepcopy(x["errors"]), "escalation_export": build_escalation_export(x["memory"].escalation,x["memory"].conversation_id) if x["memory"].escalation.confirmed else None, "retrieval_enabled": True, "documented_answer_enabled": True, "procedural_answer_enabled": True, "production_changed": False}
    try:
        export_bytes=len(json.dumps(payload,ensure_ascii=False,separators=(",",":"),default=str).encode("utf-8"))
    except Exception:
        export_bytes=None
    payload["resource_observability"]=export_diagnostic(x,export_bytes)
    payload["token_optimization_observability"]=token_session_diagnostic(exported_turns)
    payload["diagnostic_manifest"]=build_diagnostic_manifest(x, payload)
    return payload
