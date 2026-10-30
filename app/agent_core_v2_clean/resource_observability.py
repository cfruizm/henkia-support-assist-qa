from __future__ import annotations
import json
import os
import resource
from .publication_observability import build_publication_ledger

_MAX_SAMPLES = 64


def _json_bytes(value):
    try:
        return len(json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str).encode("utf-8"))
    except Exception:
        return 0


def process_rss_bytes():
    """Best-effort current RSS. No optional dependency is required."""
    try:
        with open("/proc/self/status", "r", encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) * 1024
    except Exception:
        pass
    try:
        value = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
        return value if os.name == "darwin" else value * 1024
    except Exception:
        return None


def _largest_bytes(rows):
    sizes = [_json_bytes(row) for row in list(rows or [])]
    return max(sizes, default=0)


def _cache_bytes(store):
    names = (
        "exact_turn_cache", "retrieval_cache", "documented_answer_cache",
        "procedural_answer_cache", "internal_knowledge_cache",
    )
    return {name: _json_bytes(store.get(name) or {}) for name in names}


def surface_snapshot(store, result=None):
    turns = store.get("turns") or []
    audit_turns = store.get("audit_turns") or []
    messages = store.get("messages") or []
    audit_messages = store.get("audit_messages") or []
    caches = _cache_bytes(store)
    retrieval = (result or {}).get("retrieval") or {}
    return {
        "process_rss_bytes": process_rss_bytes(),
        "session_store_bytes": _json_bytes({k: v for k, v in store.items() if k != "memory"}),
        "runtime_turns_bytes": _json_bytes(turns),
        "audit_turns_bytes": _json_bytes(audit_turns),
        "messages_bytes": _json_bytes(messages),
        "audit_messages_bytes": _json_bytes(audit_messages),
        "answer_context_bytes": _json_bytes(store.get("answer_context") or {}),
        "cache_bytes_by_type": caches,
        "cache_total_bytes": sum(caches.values()),
        "retrieval_payload_bytes": _json_bytes(retrieval),
        "largest_runtime_turn_bytes": _largest_bytes(turns),
        "largest_audit_turn_bytes": _largest_bytes(audit_turns),
        "retained_turns": len(turns),
        "archived_turns": len(audit_turns),
        "retained_messages": len(messages),
        "archived_messages": len(audit_messages),
    }


def begin_turn(store):
    snap = surface_snapshot(store)
    return {
        "rss_before_bytes": snap.get("process_rss_bytes"),
        "session_store_before_bytes": snap.get("session_store_bytes", 0),
    }


def finalize_turn(store, result, before=None):
    before = before or {}
    result["publication_ledger"] = build_publication_ledger(result)
    snap = surface_snapshot(store, result)
    rss_before = before.get("rss_before_bytes")
    rss_after = snap.get("process_rss_bytes")
    sample = {
        "schema_version": 1,
        "turn": int(getattr(store.get("memory"), "turn_number", 0) or 0),
        **snap,
        "process_rss_delta_bytes": (rss_after - rss_before) if rss_after is not None and rss_before is not None else None,
        "session_store_delta_bytes": snap.get("session_store_bytes", 0) - int(before.get("session_store_before_bytes") or 0),
        "turn_total_tokens": int(((result or {}).get("turn_metrics") or {}).get("total_tokens") or 0),
        "turn_llm_calls": int(((result or {}).get("turn_metrics") or {}).get("calls") or 0),
        "answer_mode": str(((result or {}).get("answer") or {}).get("mode") or ""),
        "retrieval_enabled": bool(((result or {}).get("retrieval") or {}).get("enabled")),
    }
    history = store.setdefault("resource_observability", [])
    history.append(sample)
    store["resource_observability"] = history[-_MAX_SAMPLES:]
    result["resource_observability"] = dict(sample)
    return sample


def export_diagnostic(store, export_estimated_bytes=None):
    history = list(store.get("resource_observability") or [])
    latest = dict(history[-1]) if history else surface_snapshot(store)
    rss_values = [row.get("process_rss_bytes") for row in history if row.get("process_rss_bytes") is not None]
    store_values = [row.get("session_store_bytes") for row in history]
    retrieval_values = [row.get("retrieval_payload_bytes") for row in history]
    return {
        "schema_version": 1,
        "policy": "observability_only_no_behavior_change",
        "sample_count": len(history),
        "latest": latest,
        "peak_process_rss_bytes": max(rss_values, default=latest.get("process_rss_bytes")),
        "peak_session_store_bytes": max(store_values, default=latest.get("session_store_bytes", 0)),
        "peak_retrieval_payload_bytes": max(retrieval_values, default=latest.get("retrieval_payload_bytes", 0)),
        "export_estimated_bytes": export_estimated_bytes,
        "samples": history,
    }

# Delta 1.1: checkpoint trace scoped to the active turn. ContextVar keeps
# concurrent Streamlit sessions isolated without storing heavy runtime objects.
from contextvars import ContextVar
from datetime import datetime, timezone
import time
import uuid

_ACTIVE_TRACE = ContextVar("henkia_resource_trace", default=None)
_PROCESS_BOOT_ID = f"{os.getpid()}-{uuid.uuid4().hex[:12]}"
_PROCESS_STARTED_MONOTONIC = time.monotonic()
_RESOURCE_STATE = {
    "embedding_model_loaded": False,
    "vectorstore_loaded": False,
    "retrieval_runtime_initialized": False,
    "embedding_model_name": None,
    "chroma_collection_name": None,
}


def process_identity():
    return {
        "process_id": os.getpid(),
        "application_boot_id": _PROCESS_BOOT_ID,
        "process_uptime_seconds": round(max(0.0, time.monotonic() - _PROCESS_STARTED_MONOTONIC), 3),
    }


def mark_resource_state(**updates):
    for key, value in updates.items():
        if key in _RESOURCE_STATE and value is not None:
            _RESOURCE_STATE[key] = value
    checkpoint("resource_state", resource_state=dict(_RESOURCE_STATE))


def start_checkpoint_trace(store, turn_number=None):
    trace = {
        "schema_version": 2,
        **process_identity(),
        "turn": int(turn_number or (getattr(store.get("memory"), "turn_number", 0) or 0) + 1),
        "started_at_utc": datetime.now(timezone.utc).isoformat(),
        "baseline_rss_bytes": process_rss_bytes(),
        "checkpoints": [],
    }
    _ACTIVE_TRACE.set(trace)
    checkpoint("turn_start", store=store)
    return trace


def checkpoint(name, store=None, result=None, **details):
    trace = _ACTIVE_TRACE.get()
    if trace is None:
        return None
    rss = process_rss_bytes()
    previous = trace["checkpoints"][-1].get("process_rss_bytes") if trace["checkpoints"] else trace.get("baseline_rss_bytes")
    row = {
        "name": str(name),
        "sampled_at_utc": datetime.now(timezone.utc).isoformat(),
        "elapsed_ms": round((time.monotonic() - _PROCESS_STARTED_MONOTONIC) * 1000.0, 3),
        "process_rss_bytes": rss,
        "rss_delta_from_previous_bytes": (rss - previous) if rss is not None and previous is not None else None,
        "rss_delta_from_turn_start_bytes": (rss - trace.get("baseline_rss_bytes")) if rss is not None and trace.get("baseline_rss_bytes") is not None else None,
        **process_identity(),
    }
    if store is not None:
        row["session_store_bytes"] = _json_bytes({k: v for k, v in store.items() if k != "memory"})
    if result is not None:
        row["retrieval_payload_bytes"] = _json_bytes((result or {}).get("retrieval") or {})
        row["answer_mode"] = str(((result or {}).get("answer") or {}).get("mode") or "")
    if details:
        row["details"] = details
    trace["checkpoints"].append(row)
    return row


def finish_checkpoint_trace(store, result=None):
    checkpoint("turn_end", store=store, result=result, resource_state=dict(_RESOURCE_STATE))
    trace = _ACTIVE_TRACE.get()
    if trace is None:
        return None
    trace["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
    rss_values = [x.get("process_rss_bytes") for x in trace["checkpoints"] if x.get("process_rss_bytes") is not None]
    trace["peak_process_rss_bytes"] = max(rss_values, default=trace.get("baseline_rss_bytes"))
    trace["final_process_rss_bytes"] = rss_values[-1] if rss_values else trace.get("baseline_rss_bytes")
    trace["resource_state"] = dict(_RESOURCE_STATE)
    _ACTIVE_TRACE.set(None)
    if result is not None:
        result["resource_checkpoint_trace"] = trace
    return trace
