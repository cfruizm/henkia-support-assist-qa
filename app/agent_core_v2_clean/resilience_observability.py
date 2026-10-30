from __future__ import annotations
from copy import deepcopy


def empty_resilience():
    return {
        "schema_version":1,
        "calls_observed":0,
        "routes":{},
        "primary_route_calls":0,
        "fallback_route_calls":0,
        "fallback_used_calls":0,
        "fallback_reasons":{},
        "rate_limit_events":0,
        "rate_limit_retries":0,
        "rate_limit_retry_successes":0,
        "rate_limit_retry_failures":0,
        "rate_limit_retry_skipped":0,
        "rate_limit_wait_seconds_total":0.0,
        "primary_skipped_by_circuit_calls":0,
        "circuit_decisions":{},
        "circuit_states_after":{},
        "last_circuit_state":None,
        "last_provider_route":None,
        "last_fallback_reason":None,
    }


def _inc(values,key,amount=1):
    if key in (None,""):return
    name=str(key);values[name]=int(values.get(name,0) or 0)+int(amount)


def normalize_resilience(raw=None):
    out=empty_resilience();src=dict(raw or {})
    for key in ("calls_observed","primary_route_calls","fallback_route_calls","fallback_used_calls","rate_limit_events","rate_limit_retries","rate_limit_retry_successes","rate_limit_retry_failures","rate_limit_retry_skipped","primary_skipped_by_circuit_calls"):
        out[key]=int(src.get(key,0) or 0)
    out["rate_limit_wait_seconds_total"]=float(src.get("rate_limit_wait_seconds_total",0.0) or 0.0)
    for key in ("routes","fallback_reasons","circuit_decisions","circuit_states_after"):out[key]=dict(src.get(key) or {})
    for key in ("last_circuit_state","last_provider_route","last_fallback_reason"):out[key]=src.get(key)
    return out


def add_resilience(summary,result):
    out=normalize_resilience(summary);metadata=dict((result or {}).get("metadata") or {})
    if not metadata:return out
    final_route=metadata.get("provider_route_final") or metadata.get("provider_route")
    initial_route=metadata.get("provider_route_initial")
    fallback_used=bool((result or {}).get("fallback_used") or metadata.get("route_fallback_used"))
    out["calls_observed"]+=1
    _inc(out["routes"],final_route)
    if final_route:out["last_provider_route"]=final_route
    if fallback_used:
        out["fallback_used_calls"]+=1;out["fallback_route_calls"]+=1
    elif final_route and (not initial_route or final_route==initial_route):out["primary_route_calls"]+=1
    reason=metadata.get("route_fallback_reason")
    if reason:_inc(out["fallback_reasons"],reason);out["last_fallback_reason"]=reason
    retry_trace=list(metadata.get("rate_limit_retry_trace") or [])
    retry_count=int(metadata.get("rate_limit_retry_count",0) or 0)
    if retry_trace or retry_count:
        out["rate_limit_events"]+=1;out["rate_limit_retries"]+=retry_count
        if metadata.get("rate_limit_retry_succeeded") is True:out["rate_limit_retry_successes"]+=1
        elif retry_count:out["rate_limit_retry_failures"]+=1
        for item in retry_trace:
            out["rate_limit_wait_seconds_total"]+=float(item.get("wait_seconds",0.0) or 0.0)
            if item.get("retry_allowed") is False:out["rate_limit_retry_skipped"]+=1
    if metadata.get("primary_skipped_by_circuit"):out["primary_skipped_by_circuit_calls"]+=1
    decision=(metadata.get("circuit_decision") or {}).get("reason")
    if decision:_inc(out["circuit_decisions"],decision)
    state=(metadata.get("circuit_state_after") or {}).get("state")
    if state:_inc(out["circuit_states_after"],state);out["last_circuit_state"]=state
    return out


def gate(summary,telemetry):
    data=normalize_resilience(summary);telemetry=dict(telemetry or {})
    observed=int(data["calls_observed"])
    checks={
        "observability_present":observed>0,
        "provider_calls_successful":int(telemetry.get("provider_failed_calls",0) or 0)==0,
        "contracts_successful":int(telemetry.get("contract_failed_calls",0) or 0)==0,
        "functional_calls_successful":int(telemetry.get("functional_failed_calls",0) or 0)==0,
        "circuit_not_stuck_open":data.get("last_circuit_state")!="open",
    }
    blocking=[name for name,passed in checks.items() if not passed]
    return {
        "schema_version":1,
        "status":"pass" if not blocking else "review",
        "ready_for_next_stage":not blocking,
        "checks":checks,
        "blocking_checks":blocking,
        "note":"A pass validates the observed campaign. Error branches remain covered by deterministic gateway tests when no natural provider failure occurred.",
    }


def snapshot(summary,telemetry):
    data=normalize_resilience(summary)
    calls=max(1,int(data["calls_observed"]))
    data["fallback_rate"]=round(data["fallback_used_calls"]/calls,6)
    data["primary_route_rate"]=round(data["primary_route_calls"]/calls,6)
    data["average_rate_limit_wait_seconds"]=round(data["rate_limit_wait_seconds_total"]/max(1,data["rate_limit_events"]),3)
    data["gate"]=gate(data,telemetry)
    return deepcopy(data)
