"""KE-03: run Agent Core answer stages with KE evidence in an isolated shadow route."""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Callable, Mapping

from app.agent_core_v2_clean.semantic_fit import apply_semantic_fit, capture_answer_context
from app.agent_core_v2_clean.unified_evidence_authority import apply_unified_evidence_verdict
from app.agent_core_v2_clean.documentation_limitation import classify as classify_documentation_limitation
from app.agent_core_v2_clean.decision_observability import attach_retrieval
from app.agent_core_v2_clean.document_continuity import continuity_authority
from app.agent_core_v2_clean.guidance_action_filter import sanitize_answer_context

SCHEMA_VERSION = 2

# Shadow-only conversation context: the answer context produced by the previous
# KE shadow answer. The published route keeps using store["answer_context"].
SHADOW_CONTEXT_KEY = "ke_shadow_answer_context"

# Only these keys of the published (local Chroma) retrieval are reused by the
# shadow route. Everything evidence-related is rebuilt from KE rows so local
# evidence can never reach the shadow composers.
_BASE_RETRIEVAL_KEYS = ("query", "_case_context", "pre_retrieval_boundary")

# Retrieval keys that may carry evidence items into a composer.
_EVIDENCE_KEYS = ("evidence", "generation_evidence", "diagnostic_evidence")


def _mapping(value: Any) -> dict:
    return dict(value) if isinstance(value, Mapping) else {}


def _enabled(config: Any) -> bool:
    getter = getattr(config, "get", lambda *_: None)
    raw = getter("KE_AGENT_CORE_SHADOW_ENABLED", True)
    return str(raw).strip().casefold() not in {"0", "false", "no", "off", "disabled"}


def ke_evidence_rows(normalized_result: Mapping[str, Any]) -> list[dict]:
    """Adapt KE rows to the canonical evidence contract without inventing pages."""
    rows = list(_mapping(normalized_result).get("results") or [])
    evidence = []
    for index, row in enumerate(rows, 1):
        if not isinstance(row, Mapping):
            continue
        source_name = str(row.get("source_name") or "Fuente KE sin titulo").strip()
        source = str(row.get("document_uri") or row.get("file_id") or source_name).strip()
        reference_url = str(row.get("reference_url") or "").strip()
        metadata = {
            "provider": "henkia_ke",
            "title": source_name,
            "source": source,
            "source_name": source_name,
            "file_id": row.get("file_id"),
            "document_uri": row.get("document_uri"),
            "knowledge_base_id": row.get("knowledge_base_id"),
            "chunk_id": row.get("chunk_id"),
            "ordinal": row.get("ordinal"),
            "document_kind": row.get("document_kind"),
            "document_date": row.get("document_date"),
            "reference_url": row.get("reference_url"),
            "vector_score": row.get("vector_score"),
            "rerank_score": row.get("rerank_score"),
            "page_unknown": row.get("page") in (None, ""),
        }
        # page intentionally remains empty when KE does not supply a real page.
        if row.get("page") not in (None, ""):
            metadata["page"] = row.get("page")
            metadata["page_label"] = row.get("page")
        evidence.append({
            "id": f"KE{index}",
            "title": source_name,
            "source": source,
            "url": reference_url,
            "score": row.get("score"),
            "page": str(row.get("page") or ""),
            "text": str(row.get("content") or "")[:1800],
            "metadata": metadata,
        })
    return evidence


def shadow_continuity(result: Mapping[str, Any], previous_shadow_context: Mapping[str, Any] | None) -> dict:
    """Resolve document continuity against the previous KE shadow answer only."""
    return continuity_authority(
        _mapping(result.get("understanding")),
        _mapping(result.get("topic_boundary")),
        _mapping(previous_shadow_context),
    )


def build_shadow_retrieval(
    result: Mapping[str, Any],
    message: str,
    answer_context: Mapping[str, Any] | None = None,
    continuity: Mapping[str, Any] | None = None,
) -> dict:
    """Build the shadow retrieval from KE rows plus the shadow's own context.

    ``answer_context`` must come from the KE shadow ledger (or be empty); the
    published route's ``_answer_context`` is never reused because it carries
    local Chroma evidence from previous turns.
    """
    comparison = _mapping(result.get("knowledge_comparison"))
    normalized = _mapping(comparison.get("normalized_result"))
    published = _mapping(result.get("retrieval"))
    base = {key: deepcopy(published[key]) for key in _BASE_RETRIEVAL_KEYS if key in published}
    evidence = ke_evidence_rows(normalized)
    query = deepcopy(_mapping(base.get("query")))
    query.setdefault("text", str(comparison.get("query") or message or "").strip())
    fields = query.get("fields")
    if isinstance(fields, dict) and continuity is not None:
        fields["previous_evidence_role"] = _mapping(continuity).get("previous_evidence_role") or "none"
    groups = []
    seen = set()
    for item in evidence:
        identity = item.get("source") or item.get("title")
        if identity in seen:
            continue
        seen.add(identity)
        groups.append({"identity": identity, "title": item.get("title"), "pages": [], "chunks": sum(1 for x in evidence if (x.get("source") or x.get("title")) == identity)})
    retrieval = {
        **base,
        "enabled": True,
        "llm_called": False,
        "ok": normalized.get("http_status") == 200 and not normalized.get("error"),
        "adapter": "henkia_knowledge_engine",
        "provider": "henkia_ke",
        "query": query,
        "count": len(evidence),
        "evidence": evidence,
        "document_groups": groups,
        "errors": ([deepcopy(normalized.get("error"))] if normalized.get("error") else []),
        "diagnostic_only": True,
        "shadow_only": True,
        "production_changed": False,
        "procedural_expansion": {"enabled": False, "reason": "ke_shadow_no_same_document_expansion", "llm_called": False},
        "selection": {
            "chosen_mode": "henkia_ke_shadow",
            "quality": None,
            "context_contamination_avoided": True,
            "preselected_document": None,
        },
    }
    answer_context = deepcopy(_mapping(answer_context))
    retrieval["_answer_context"] = answer_context
    retrieval = apply_semantic_fit(retrieval, answer_context)
    retrieval["_answer_context"] = answer_context
    retrieval = apply_unified_evidence_verdict(retrieval, message, _mapping(result.get("understanding")))
    retrieval["documentation_limitation"] = classify_documentation_limitation(retrieval)
    retrieval["_answer_context"] = answer_context
    retrieval = attach_retrieval(dict(result), retrieval, message)
    return retrieval


def _route_summary(route_result: Mapping[str, Any], retrieval: Mapping[str, Any]) -> dict:
    answer = _mapping(route_result.get("answer"))
    documented = _mapping(route_result.get("documented_answer"))
    verdict = _mapping(retrieval.get("evidence_verdict"))
    authority = _mapping(retrieval.get("unified_evidence_authority"))
    return {
        "retrieval_provider": "henkia_ke",
        "retrieval_ok": bool(retrieval.get("ok")),
        "result_count": int(retrieval.get("count") or 0),
        "evidence_status": verdict.get("status"),
        "evidence_accepted": bool(verdict.get("accepted")),
        # Compact verdict detail kept for diagnosing why KE evidence was accepted or not.
        "verdict_reason": verdict.get("reason"),
        "operation_alignment": deepcopy(verdict.get("operation_alignment")),
        "selected_documents": list(dict.fromkeys(
            str((item or {}).get("title") or "")[:120] for item in (verdict.get("selected_evidence") or [])
        ))[:3],
        "candidate_documents": list(dict.fromkeys(
            str((item or {}).get("title") or "")[:120] for item in (retrieval.get("diagnostic_evidence") or retrieval.get("evidence") or [])
        ))[:5],
        "authority_status": authority.get("status") or authority.get("verdict"),
        "answer_generated": bool(str(answer.get("text") or "").strip()),
        "answer_mode": answer.get("mode"),
        "knowledge_used": answer.get("knowledge_used"),
        "documented_answer": documented,
        "answer": deepcopy(answer),
    }


def _is_ke_item(item: Any) -> bool:
    metadata = _mapping(_mapping(item).get("metadata"))
    return metadata.get("provider") == "henkia_ke"


def isolation_report(retrieval: Mapping[str, Any]) -> dict:
    """Count evidence items in the shadow route that did not come from KE."""
    retrieval = _mapping(retrieval)
    groups = {key: list(retrieval.get(key) or []) for key in _EVIDENCE_KEYS}
    groups["selected_evidence"] = list(_mapping(retrieval.get("evidence_verdict")).get("selected_evidence") or [])
    context = _mapping(retrieval.get("_answer_context"))
    groups["answer_context_ledger"] = list(
        context.get("active_document_evidence_ledger") or context.get("cited_evidence") or []
    )
    non_ke = {}
    for name, items in groups.items():
        foreign = [item for item in items if not _is_ke_item(item)]
        if foreign:
            non_ke[name] = [
                str(_mapping(item).get("title") or _mapping(item).get("source") or "")[:120] for item in foreign[:5]
            ]
    return {
        "checked_groups": sorted(groups),
        "non_ke_item_count": sum(len(v) for v in non_ke.values()),
        "non_ke_items": non_ke,
        "isolated": not non_ke,
    }


def execute(result: dict, message: str, config: Any, session: Any, budget: Any, store: Mapping[str, Any], answer_runner: Callable) -> dict:
    """Execute a no-write KE shadow route using the existing Agent Core answer stages."""
    block = {
        "schema_version": SCHEMA_VERSION,
        "enabled": _enabled(config),
        "executed": False,
        "observational_only": True,
        "visible_to_user": False,
        "affects_memory": False,
        "affects_case_state": False,
        "affects_escalation": False,
        "affects_publication": False,
        "published_provider": "local_chroma",
        "shadow_provider": "henkia_ke",
        "production_changed": False,
    }
    result["agent_core_ke_shadow"] = block
    if not block["enabled"]:
        block["skip_reason"] = "disabled_by_configuration"
        return block
    comparison = _mapping(result.get("knowledge_comparison"))
    normalized = _mapping(comparison.get("normalized_result"))
    if not comparison:
        block["skip_reason"] = "knowledge_comparison_unavailable"
        return block
    if normalized.get("http_status") != 200 or normalized.get("error"):
        block["skip_reason"] = "ke_provider_not_evaluable"
        block["provider_error"] = deepcopy(normalized.get("error"))
        return block
    try:
        previous_context = _mapping(store.get(SHADOW_CONTEXT_KEY))
        shadow_result = deepcopy(result)
        shadow_store = deepcopy(dict(store))
        # Composers that read the session answer context see the shadow's own.
        shadow_store["answer_context"] = deepcopy(previous_context)
        continuity = shadow_continuity(shadow_result, previous_context)
        shadow_result["document_continuity"] = {k: v for k, v in continuity.items() if k != "answer_context"}
        shadow_retrieval = build_shadow_retrieval(
            shadow_result, message, continuity.get("answer_context") or {}, continuity
        )
        shadow_result["retrieval"] = shadow_retrieval
        shadow_result["answer"] = {"text": "", "mode": "ke_shadow_pending", "knowledge_used": False}
        shadow_result.pop("documented_answer", None)
        shadow_result.pop("procedural_answer", None)
        shadow_result, conceptual_trace, procedural_trace = answer_runner(
            shadow_result, message, config, session, budget, shadow_store
        )
        local_answer = _mapping(result.get("answer"))
        route = _route_summary(shadow_result, shadow_retrieval)
        isolation = isolation_report(_mapping(shadow_result.get("retrieval")) or shadow_retrieval)
        next_context = sanitize_answer_context(capture_answer_context(shadow_result, previous_context))
        if next_context and isinstance(store, dict):
            # Shadow-only key; the published answer context is never touched.
            store[SHADOW_CONTEXT_KEY] = next_context
        block["context"] = {
            "source": "ke_shadow_ledger" if previous_context else "none",
            "same_topic": bool(continuity.get("same_topic")),
            "primary": bool(continuity.get("primary")),
            "previous_evidence_role": continuity.get("previous_evidence_role"),
            "ledger_items_before": len(
                previous_context.get("active_document_evidence_ledger") or previous_context.get("cited_evidence") or []
            ),
            "ledger_updated": bool(next_context),
        }
        block["isolation"] = isolation
        block.update({
            "executed": True,
            "ke_route": route,
            "published_route": {
                "retrieval_provider": "local_chroma",
                "answer_generated": bool(str(local_answer.get("text") or "").strip()),
                "answer_mode": local_answer.get("mode"),
                "knowledge_used": local_answer.get("knowledge_used"),
            },
            "comparison": {
                "both_generated": bool(str(local_answer.get("text") or "").strip()) and bool(route.get("answer_generated")),
                "answer_mode_agreement": local_answer.get("mode") == route.get("answer_mode"),
                "publication_unchanged": True,
            },
            "traces": {"conceptual": conceptual_trace, "procedural": procedural_trace},
        })
    except Exception as exc:
        block["shadow_error"] = {"type": type(exc).__name__, "message": str(exc)[:500]}
        block["skip_reason"] = "shadow_execution_error"
    return block
