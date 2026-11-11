"""KE-03: run Agent Core answer stages with KE evidence in an isolated shadow route."""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Callable, Mapping

from app.agent_core_v2_clean.semantic_fit import apply_semantic_fit
from app.agent_core_v2_clean.unified_evidence_authority import apply_unified_evidence_verdict
from app.agent_core_v2_clean.documentation_limitation import classify as classify_documentation_limitation
from app.agent_core_v2_clean.decision_observability import attach_retrieval

SCHEMA_VERSION = 1


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


def build_shadow_retrieval(result: Mapping[str, Any], message: str) -> dict:
    comparison = _mapping(result.get("knowledge_comparison"))
    normalized = _mapping(comparison.get("normalized_result"))
    base = deepcopy(_mapping(result.get("retrieval")))
    evidence = ke_evidence_rows(normalized)
    query = deepcopy(_mapping(base.get("query")))
    query.setdefault("text", str(comparison.get("query") or message or "").strip())
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
    answer_context = deepcopy(base.get("_answer_context") or {})
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
        "authority_status": authority.get("status") or authority.get("verdict"),
        "answer_generated": bool(str(answer.get("text") or "").strip()),
        "answer_mode": answer.get("mode"),
        "knowledge_used": answer.get("knowledge_used"),
        "documented_answer": documented,
        "answer": deepcopy(answer),
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
        shadow_result = deepcopy(result)
        shadow_store = deepcopy(dict(store))
        shadow_retrieval = build_shadow_retrieval(shadow_result, message)
        shadow_result["retrieval"] = shadow_retrieval
        shadow_result["answer"] = {"text": "", "mode": "ke_shadow_pending", "knowledge_used": False}
        shadow_result.pop("documented_answer", None)
        shadow_result.pop("procedural_answer", None)
        shadow_result, conceptual_trace, procedural_trace = answer_runner(
            shadow_result, message, config, session, budget, shadow_store
        )
        local_answer = _mapping(result.get("answer"))
        route = _route_summary(shadow_result, shadow_retrieval)
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
