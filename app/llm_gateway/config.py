from __future__ import annotations
import os
from app.llm_gateway.budget_config import load_budget_config

def _get(secrets, key, default=None):
    try:
        value=secrets.get(key,default)
        return default if value is None else value
    except Exception:return default

def _as_bool(value, default=False):
    if value is None:return default
    if isinstance(value,bool):return value
    return str(value).strip().casefold() in {"1","true","yes","on"}

def load_gateway_config(secrets) -> dict:
    provider = str(_get(secrets, "LLM_PROVIDER", "huggingface")).lower().strip()
    fallback_provider = str(_get(secrets, "LLM_FALLBACK_PROVIDER", "huggingface")).lower().strip()
    fallback_enabled = _as_bool(_get(secrets, "LLM_FALLBACK_ENABLED", False), False)
    supported_providers = {"groq", "huggingface"}
    if provider not in supported_providers:
        raise ValueError(f"LLM_PROVIDER no soportado: {provider}. Use 'huggingface' o 'groq'.")
    if fallback_enabled and fallback_provider not in supported_providers:
        raise ValueError(f"LLM_FALLBACK_PROVIDER no soportado: {fallback_provider}. Use 'huggingface' o 'groq'.")
    structured = str(_get(secrets, "GROQ_STRUCTURED_OUTPUT_MODE", "best_effort")).lower().strip()
    budget = load_budget_config(secrets)
    return {
        "provider": provider,
        "fallback_enabled": fallback_enabled,
        "fallback_provider": fallback_provider,
        "max_calls_per_session": budget["max_session_calls"],
        "max_total_tokens_per_session": budget["max_session_tokens"],
        "session_reserve_tokens": budget["session_reserve_tokens"],
        "budget_configuration": budget,
        "orchestrator_max_tokens": max(64, min(4096, int(_get(secrets, "LLM_ORCHESTRATOR_MAX_TOKENS", 220)))),
        "understanding_max_tokens": max(320, min(4096, int(_get(secrets, "LLM_UNDERSTANDING_MAX_TOKENS", 360)))),
        "answer_max_tokens": max(128, min(4096, int(_get(secrets, "LLM_ANSWER_MAX_TOKENS", 900)))),
        "evidence_judge_max_tokens": max(64, min(4096, int(_get(secrets, "LLM_EVIDENCE_JUDGE_MAX_TOKENS", 360)))),
        "providers": {
            "groq": {"api_key": _get(secrets,"GROQ_API_KEY"), "orchestrator_model": str(_get(secrets,"GROQ_ORCHESTRATOR_MODEL","qwen/qwen3.8-27b")), "answer_model": str(_get(secrets,"GROQ_ANSWER_MODEL","openai/gpt-oss-120b")), "structured_mode": structured, "base_url": "https://api.groq.com/openai/v1/chat/completions"},
            "huggingface": {
                "token": _get(secrets,"HF_TOKEN"), "bill_to": str(_get(secrets,"HF_BILL_TO","") or "").strip(),
                "orchestrator_model": str(_get(secrets,"HF_ORCHESTRATOR_MODEL",_get(secrets,"HF_MODEL",""))),
                "answer_model": str(_get(secrets,"HF_ANSWER_MODEL",_get(secrets,"HF_MODEL",""))),
                "primary_provider": str(_get(secrets,"HF_PRIMARY_PROVIDER",_get(secrets,"HF_PROVIDER","cerebras")) or "cerebras").strip().casefold(),
                "fallback_provider": str(_get(secrets,"HF_FALLBACK_PROVIDER","deepinfra") or "deepinfra").strip().casefold(),
                "route_fallback_enabled": _as_bool(_get(secrets,"HF_ROUTE_FALLBACK_ENABLED",_get(secrets,"LLM_FALLBACK_ENABLED",False)),False),
                "rate_limit_max_retries": max(0,min(2,int(_get(secrets,"HF_429_MAX_RETRIES",1)))),
                "rate_limit_default_wait_seconds": max(1,min(60,float(_get(secrets,"HF_429_DEFAULT_WAIT_SECONDS",10)))),
                "rate_limit_max_wait_seconds": max(1,min(120,float(_get(secrets,"HF_429_MAX_WAIT_SECONDS",45)))),
                "rate_limit_jitter_seconds": max(0,min(10,float(_get(secrets,"HF_RETRY_JITTER_SECONDS",2)))),
                "circuit_breaker_enabled": _as_bool(_get(secrets,"HF_CIRCUIT_BREAKER_ENABLED",True),True),
                "circuit_failure_threshold": max(1,min(10,int(_get(secrets,"HF_CIRCUIT_FAILURE_THRESHOLD",2)))),
                "circuit_cooldown_seconds": max(5,min(900,float(_get(secrets,"HF_CIRCUIT_COOLDOWN_SECONDS",60)))),
                "circuit_half_open_max_calls": max(1,min(3,int(_get(secrets,"HF_CIRCUIT_HALF_OPEN_MAX_CALLS",1)))),
                "disable_thinking": _as_bool(_get(secrets,"HF_DISABLE_THINKING",True),True),
                "timeout_seconds": max(10,min(120,int(_get(secrets,"HF_TIMEOUT_SECONDS",75)))),
                "structured_mode": str(_get(secrets,"HF_STRUCTURED_OUTPUT_MODE","json_schema")).strip().casefold(),
            },
        },
    }

def model_for(config, provider, purpose=None, model_role=None):
    role = str(model_role or "").strip().casefold()
    key = "orchestrator_model" if role == "orchestrator" or (not role and purpose == "semantic_orchestrator") else "answer_model"
    return config["providers"][provider][key]
