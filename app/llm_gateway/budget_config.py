from __future__ import annotations
import os

BUDGET_DEFAULTS = {"max_session_calls": 60, "max_session_tokens": 52000, "session_reserve_tokens": 2200}
BUDGET_SECRET_KEYS = {
    "max_session_calls": ("HF_MAX_SESSION_CALLS", "LLM_MAX_CALLS_PER_SESSION", "AGENT_CORE_MAX_SESSION_CALLS"),
    "max_session_tokens": ("HF_MAX_SESSION_TOKENS", "LLM_MAX_TOTAL_TOKENS_PER_SESSION", "AGENT_CORE_MAX_SESSION_TOKENS"),
    "session_reserve_tokens": ("HF_SESSION_RESERVE_TOKENS", "AGENT_CORE_SESSION_RESERVE_TOKENS"),
}

def _source_value(secrets, key):
    try:
        value = secrets.get(key)
        if value is not None:return value, "streamlit_secrets"
    except Exception:pass
    if key in os.environ:return os.environ[key], "environment"
    return None, None

def _bounded_int(raw, minimum, maximum):
    value=int(str(raw).strip())
    if value < minimum or value > maximum:raise ValueError(f"value_out_of_range:{minimum}:{maximum}")
    return value

def load_budget_config(secrets) -> dict:
    """Canonical cumulative-session budget used by gateway and Agent Core."""
    limits={"max_session_calls":(1,1000),"max_session_tokens":(500,2_000_000),"session_reserve_tokens":(0,500_000)}
    effective,sources,keys,invalid={},{},{},[]
    for field,candidates in BUDGET_SECRET_KEYS.items():
        selected=None
        for key in candidates:
            raw,source=_source_value(secrets,key)
            if source is None:continue
            try:
                selected=_bounded_int(raw,*limits[field]);effective[field]=selected;sources[field]=source;keys[field]=key;break
            except Exception as exc:
                invalid.append({"field":field,"key":key,"source":source,"value":str(raw),"error":str(exc)})
        if selected is None:
            effective[field]=BUDGET_DEFAULTS[field];sources[field]="default";keys[field]=None
    if effective["session_reserve_tokens"] >= effective["max_session_tokens"]:
        invalid.append({"field":"session_reserve_tokens","key":keys["session_reserve_tokens"],"source":sources["session_reserve_tokens"],"value":str(effective["session_reserve_tokens"]),"error":"reserve_must_be_lower_than_max_session_tokens"})
        effective["session_reserve_tokens"]=min(BUDGET_DEFAULTS["session_reserve_tokens"],max(0,effective["max_session_tokens"]//10));sources["session_reserve_tokens"]="validated_fallback";keys["session_reserve_tokens"]=None
    return {**effective,"sources":sources,"keys":keys,"invalid_values":invalid}
