"""KE-03/KE-04: run Agent Core answer stages with KE evidence in an isolated route.

KE-03 keeps the route observational. KE-04 (KNOWLEDGE_PUBLISH_MODE=complement)
publishes the KE answer only when the local answer used no documentation and the
KE answer is documented and isolated.
"""
from __future__ import annotations

import re
from copy import deepcopy
from typing import Any, Callable, Mapping

from app.agent_core_v2_clean.documented_answer import KE_SAME_DOCUMENT_FETCHER
from app.agent_core_v2_clean.semantic_fit import apply_semantic_fit, capture_answer_context
from app.agent_core_v2_clean.unified_evidence_authority import apply_unified_evidence_verdict
from app.agent_core_v2_clean.documentation_limitation import classify as classify_documentation_limitation
from app.agent_core_v2_clean.decision_observability import attach_retrieval
from app.agent_core_v2_clean.document_continuity import continuity_authority
from app.agent_core_v2_clean.guidance_action_filter import sanitize_answer_context
from app.knowledge_gateway import ke_full_document

SCHEMA_VERSION = 3

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


# Answer modes that publish documented content (degraded fallbacks excluded).
DOCUMENTED_MODES = frozenset({
    "documented_answer", "documented_answer_partial",
    "procedural_documented_answer", "procedural_documented_answer_partial",
})
PUBLISH_MODES = ("off", "complement", "primary")

# Local answers that come from the documentary pipeline and may be replaced in
# primary mode. Clarifications, escalation, social and budget answers are never
# replaced: the KE route only competes on documentary answers.
_REPLACEABLE_LOCAL_PREFIXES = ("controlled_internal_knowledge", "documented_degraded")
_REPLACEABLE_LOCAL_MODES = frozenset({
    "documented_insufficient", "documented_citation_guard", "documented_provider_degraded",
    "documented_truncation_safe_defer", "procedural_evidence_guard", "procedural_citation_guard",
    "procedural_provider_degraded", "procedural_evidence_contradiction_guard",
})


def publish_mode(config: Any) -> str:
    """KNOWLEDGE_PUBLISH_MODE: off (default, observational), complement or primary."""
    getter = getattr(config, "get", lambda *_: None)
    raw = str(getter("KNOWLEDGE_PUBLISH_MODE", "off") or "off").strip().casefold()
    return raw if raw in PUBLISH_MODES else "off"


def _is_documented(answer: Mapping[str, Any]) -> bool:
    answer = _mapping(answer)
    return (
        answer.get("mode") in DOCUMENTED_MODES
        and bool(answer.get("documented_evidence_used", True))
        and bool(str(answer.get("text") or "").strip())
    )


def _local_replaceable(local_answer: Mapping[str, Any]) -> bool:
    mode = str(_mapping(local_answer).get("mode") or "")
    return mode in DOCUMENTED_MODES or mode in _REPLACEABLE_LOCAL_MODES or mode.startswith(_REPLACEABLE_LOCAL_PREFIXES)


def _primary_decision(local_answer: Mapping[str, Any], ke_answer: Mapping[str, Any],
                      ke_route: Mapping[str, Any], isolation: Mapping[str, Any]) -> dict:
    """KE-06: KE is the primary source and local is the fallback.

    The KE answer is published when it is documented, its evidence was accepted
    and the route used no local evidence. Local stays when KE has no
    documentation, when the local answer is not documentary (clarification,
    escalation...), or when KE is partial while local is complete.
    """
    local_answer, ke_answer = _mapping(local_answer), _mapping(ke_answer)
    local_documented = _local_documented(local_answer)
    ke_partial = str(ke_answer.get("mode") or "").endswith("_partial")
    local_partial = str(local_answer.get("mode") or "").endswith("_partial")
    checks = {
        "local_replaceable": _local_replaceable(local_answer),
        "ke_documented": _is_documented(ke_answer),
        "ke_evidence_accepted": _mapping(ke_route).get("evidence_status") in {"sufficient", "partial"},
        "ke_isolated": bool(_mapping(isolation).get("isolated")),
        "ke_not_less_complete": not (ke_partial and local_documented and not local_partial),
    }
    applied = all(checks.values())
    failed = next((k for k, ok in checks.items() if not ok), None)
    if applied:
        reason = "ke_primary_over_documented_local" if local_documented else "ke_primary_over_undocumented_local"
    else:
        reason = f"not_{failed}"
    return {"mode": "primary", "applied": applied, "reason": reason, "checks": checks,
            "local_mode": local_answer.get("mode"), "ke_mode": ke_answer.get("mode")}


def complement_decision(mode: str, local_answer: Mapping[str, Any], ke_answer: Mapping[str, Any],
                        ke_route: Mapping[str, Any], isolation: Mapping[str, Any]) -> dict:
    """Decide whether the KE answer replaces the local one (KE-04 complement, KE-06 primary)."""
    if mode == "primary":
        return _primary_decision(local_answer, ke_answer, ke_route, isolation)
    local_answer = _mapping(local_answer)
    local_documented = _local_documented(local_answer)
    checks = {
        "mode_complement": mode == "complement",
        "local_not_documented": not local_documented,
        "ke_documented": _is_documented(ke_answer),
        "ke_evidence_accepted": _mapping(ke_route).get("evidence_status") in {"sufficient", "partial"},
        "ke_isolated": bool(_mapping(isolation).get("isolated")),
    }
    applied = all(checks.values())
    failed = next((k for k, ok in checks.items() if not ok), None)
    reason = "ke_complements_undocumented_local_answer" if applied else f"not_{failed}"
    return {"mode": mode, "applied": applied, "reason": reason, "checks": checks}


def _ordinal(item: Mapping[str, Any], position: int) -> tuple:
    raw = _mapping(_mapping(item).get("metadata")).get("ordinal")
    try:
        return (0, int(raw), position)
    except (TypeError, ValueError):
        return (1, 0, position)


DOCUMENT_FETCH_LIMIT = 12
EXPANDED_CHUNK_LIMIT = 10


def ke_document_fetcher(config: Any, evidence: list[Mapping[str, Any]]) -> Callable | None:
    """Return fetch(query, source, k) that searches inside one KE document.

    The knowledge base of each document comes from the KE rows already retrieved
    (metadata.knowledge_base_id), so the fetcher never searches a base the turn
    did not use. Output follows the same-document adapter contract.
    """
    bases = {}
    for item in evidence or []:
        md = _mapping(_mapping(item).get("metadata"))
        if md.get("provider") == "henkia_ke" and item.get("source") and md.get("knowledge_base_id"):
            bases.setdefault(str(item["source"]), str(md["knowledge_base_id"]))
    if not bases:
        return None

    def fetch(query: Any, source: str, k: int = DOCUMENT_FETCH_LIMIT) -> dict:
        from app.knowledge_gateway.henkia_knowledge_engine import search_document
        kb_id = bases.get(str(source))
        if not kb_id:
            return {"ok": False, "adapter": "henkia_ke_document_filter", "evidence": [], "errors": ["unknown_document"]}
        result = search_document(query, config, kb_id, source, k)
        if result.error or result.http_status != 200:
            return {"ok": False, "adapter": "henkia_ke_document_filter", "evidence": [],
                    "errors": [str((result.error or {}).get("code") or result.http_status)]}
        rows = [row for row in ke_evidence_rows(result.to_dict()) if row.get("source") == str(source)]
        return {"ok": True, "adapter": "henkia_ke_document_filter", "evidence": rows, "errors": []}
    return fetch


def _chunk_key(item: Mapping[str, Any]) -> str:
    md = _mapping(_mapping(item).get("metadata"))
    return str(md.get("chunk_id") or md.get("ordinal") or str(_mapping(item).get("text") or "")[:120])


def _expand_from_document(selected: list, fetcher: Callable | None, query: Any, source: str) -> tuple[list, dict]:
    """Add the most relevant chunks of the same KE document to the accepted ones."""
    if fetcher is None:
        return selected, {"fetched": False, "reason": "no_fetcher"}
    try:
        raw = fetcher(query, source, DOCUMENT_FETCH_LIMIT) or {}
    except Exception as exc:  # network or contract failure: keep the accepted chunks
        return selected, {"fetched": False, "reason": "fetch_error", "errors": [type(exc).__name__]}
    if not raw.get("ok"):
        return selected, {"fetched": False, "reason": "fetch_failed", "errors": raw.get("errors") or []}
    seen = {_chunk_key(x) for x in selected}
    added = []
    for row in raw.get("evidence") or []:
        key = _chunk_key(row)
        if key in seen or len(selected) + len(added) >= EXPANDED_CHUNK_LIMIT:
            continue
        seen.add(key)
        added.append({**deepcopy(row), "origin": "ke_same_document_search"})
    return selected + added, {"fetched": True, "fetched_count": len(raw.get("evidence") or []), "added_count": len(added)}


def _local_documented(answer: Any) -> bool:
    answer = _mapping(answer)
    # The answer mode decides, not documented_evidence_used: an internal-knowledge
    # answer that cites one fragment carries that flag (QA: Find-Me follow-up kept a
    # general answer over a documented KE one).
    return _is_documented(answer)


def document_queries(message: str, result: Mapping[str, Any]) -> list[str]:
    """Queries for a same-document search: the message and the goal (multi-query)."""
    goal = str(_mapping(_mapping(result).get("understanding")).get("current_goal") or "").strip()
    return list(dict.fromkeys(q for q in (str(message or "").strip(), goal) if q))


def apply_ke_document_order(retrieval: dict, fetcher: Callable | None = None, query: Any = None) -> dict:
    """Enable procedural composition for one accepted KE document.

    KE search returns chunks of the accepted document ranked by score, without
    pages. When the verdict selects a single KE document, the most relevant other
    chunks of that document are added (KE-05: rag.filters.document_uri, when a
    fetcher is available), everything is put in document order (KE ordinal) and
    the expansion contract is marked ordered and same-document, so the procedural
    composer can write a real procedure instead of the degraded reference.
    """
    selected = list(retrieval.get("generation_evidence") or [])
    verdict = retrieval.get("evidence_verdict") or {}
    identities = {str(x.get("source") or x.get("title") or "") for x in selected}
    if not selected or verdict.get("status") not in {"sufficient", "partial"}:
        retrieval["procedural_expansion"] = {"enabled": False, "reason": "ke_no_accepted_document", "llm_called": False}
        return retrieval
    if len(identities) != 1 or not all(_is_ke_item(x) for x in selected):
        retrieval["procedural_expansion"] = {"enabled": False, "reason": "ke_multiple_documents", "llm_called": False}
        return retrieval
    source = next(iter(identities))
    selected, expansion_trace = _expand_from_document(selected, fetcher, query, source)
    ranked = sorted(((_ordinal(x, i), x) for i, x in enumerate(selected)), key=lambda t: t[0])
    ordered = [deepcopy(x) for _, x in ranked]
    remap = {}
    for index, item in enumerate(ordered, 1):
        remap[str(item.get("id"))] = f"R{index}"
        item["id"] = f"R{index}"
    retrieval["generation_evidence"] = deepcopy(ordered)
    retrieval["evidence"] = deepcopy(ordered)
    verdict = deepcopy(verdict)
    verdict["selected_evidence"] = deepcopy(ordered)
    verdict["evidence_ids"] = [x["id"] for x in ordered]
    retrieval["evidence_verdict"] = verdict
    retrieval["procedural_expansion"] = {
        "enabled": True, "attempted": True, "ok": True, "llm_called": False,
        "adapter": "henkia_ke_document_filter" if expansion_trace.get("fetched") else "henkia_ke_ordinal_order",
        "seed_document": source, "seed_page": None,
        "pages": [], "count": len(ordered), "ordered": True, "same_document_only": True,
        "ordinals": [_mapping(x.get("metadata")).get("ordinal") for x in ordered],
        "document_search": expansion_trace,
        "id_remap": remap, "errors": list(expansion_trace.get("errors") or []), "generation_enabled": False,
    }
    return retrieval


PROBE_CACHE_KEY = "ke_document_probe_cache"


def _probe_enabled(config: Any) -> bool:
    getter = getattr(config, "get", lambda *_: None)
    return str(getter("HENKIA_KE_DOCUMENT_PROBE", "false")).strip().casefold() in {"1", "true", "yes", "on"}


def document_probe(config: Any, retrieval: Mapping[str, Any], store: Any) -> dict | None:
    """Observational check of GET /document for the accepted KE document.

    Records only status, error code, size and latency; the text is never stored,
    published or sent to a composer. One request per document and session.
    """
    if not _probe_enabled(config):
        return None
    selected = list(_mapping(retrieval).get("generation_evidence") or [])
    if not selected or not _is_ke_item(selected[0]):
        return {"attempted": False, "reason": "no_accepted_ke_document"}
    item = selected[0]
    uri = str(item.get("source") or "")
    kb_id = str(_mapping(item.get("metadata")).get("knowledge_base_id") or "")
    cache = store.setdefault(PROBE_CACHE_KEY, {}) if isinstance(store, dict) else {}
    if uri in cache:
        return {**cache[uri], "cached": True}
    from app.knowledge_gateway.henkia_knowledge_engine import fetch_document, mcp_read_document

    def outcome(raw: Mapping[str, Any]) -> dict:
        return {"ok": bool(raw.get("ok")), "http_status": raw.get("http_status"), "error_code": raw.get("error_code"),
                "chars": len(raw.get("text") or ""), "latency_ms": raw.get("latency_ms")}
    rest = fetch_document(config, kb_id, uri)
    mcp = mcp_read_document(config, kb_id, uri)
    summary = {
        "attempted": True, "document": str(item.get("title") or "")[:120], "knowledge_base_id": kb_id,
        # REST /document (X-Api-Key) and MCP leer_documento (Bearer); text never kept.
        "rest": outcome(rest),
        "mcp": {**outcome(mcp), "tool_schema": mcp.get("schema"), "steps": mcp.get("steps") or []},
        "ok": bool(rest.get("ok") or mcp.get("ok")), "cached": False,
    }
    cache[uri] = {k: v for k, v in summary.items() if k != "cached"}
    return summary


def _enabled(config: Any) -> bool:
    getter = getattr(config, "get", lambda *_: None)
    raw = getter("KE_AGENT_CORE_SHADOW_ENABLED", True)
    return str(raw).strip().casefold() not in {"0", "false", "no", "off", "disabled"}


_SYNC_SUFFIX = re.compile(r"\s*\[[a-z]+-[0-9a-f]{8}\]\.(?:md|txt|html?)$", re.I)


def _display_name(source_name: str) -> str:
    """Readable title from a KE file name: drops a sync code like " [pcweb-4ab81f21].md"."""
    cleaned = _SYNC_SUFFIX.sub("", str(source_name or "")).strip()
    return cleaned or str(source_name or "")


def ke_evidence_rows(normalized_result: Mapping[str, Any]) -> list[dict]:
    """Adapt KE rows to the canonical evidence contract without inventing pages."""
    rows = list(_mapping(normalized_result).get("results") or [])
    evidence = []
    for index, row in enumerate(rows, 1):
        if not isinstance(row, Mapping):
            continue
        source_name = str(row.get("source_name") or "Fuente KE sin titulo").strip()
        # The page or document title the KE stores (document_title); the file name
        # (e.g. a URL slug) is only a fallback. Title terms weigh in the verdict.
        display_title = str(row.get("document_title") or "").strip() or _display_name(source_name)
        source = str(row.get("document_uri") or row.get("file_id") or source_name).strip()
        reference_url = str(row.get("reference_url") or "").strip()
        metadata = {
            "provider": "henkia_ke",
            "title": display_title,
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
        # Connector documents (SharePoint) have a sharepoint:// URI and no web URL;
        # mark them internal so the footer links the configured internal library.
        if str(row.get("document_uri") or "").casefold().startswith("sharepoint://") and not reference_url.startswith(("http://", "https://")):
            metadata["source_access"] = "internal_sharepoint"
        # page intentionally remains empty when KE does not supply a real page.
        if row.get("page") not in (None, ""):
            metadata["page"] = row.get("page")
            metadata["page_label"] = row.get("page")
        evidence.append({
            "id": f"KE{index}",
            "title": display_title,
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
    config: Any = None,
    store: Any = None,
) -> dict:
    """Build the shadow retrieval from KE rows plus the shadow's own context.

    With ``config`` the accepted KE document is expanded with a search inside that
    document (KE-05); without it (offline tests) only the retrieved chunks are used.

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
        "procedural_expansion": {"enabled": False, "reason": "ke_pending_verdict", "llm_called": False},
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
    # Each search inside a document adds a KE request to the turn, so it is limited
    # to procedures, where more stages of the same document change the answer.
    understanding = _mapping(result.get("understanding"))
    intent = str(understanding.get("intent") or "").casefold()
    fetcher = ke_document_fetcher(config, evidence) if config is not None and intent == "procedural" else None
    queries = document_queries(message, result)
    full_trace = None
    ke_may_publish = publish_mode(config) == "primary" or not _local_documented(result.get("answer"))
    if fetcher is not None and ke_full_document.enabled(config) and ke_may_publish:
        # KE-05.3: the KE answer is the one the user will likely see; read the full text.
        retrieval = apply_ke_document_order(retrieval, None, queries)
        if _mapping(retrieval.get("procedural_expansion")).get("ok"):
            from app.knowledge_gateway.henkia_knowledge_engine import read_full_document
            request_text = " ".join([*queries, *(str(v or "") for v in _mapping(understanding.get("goal_updates")).values())])
            full_trace = ke_full_document.apply_full_document(
                retrieval, lambda kb_id, uri: read_full_document(config, kb_id, uri), store, request_text
            )
        if full_trace and full_trace.get("used"):
            expansion = retrieval["procedural_expansion"]
            expansion.update({
                "adapter": "henkia_ke_full_document",
                "count": len(retrieval.get("generation_evidence") or []),
                "ordinals": [_mapping(x.get("metadata")).get("ordinal") for x in retrieval.get("generation_evidence") or []],
                "full_document": full_trace,
            })
        else:
            retrieval = apply_ke_document_order(retrieval, fetcher, queries)
            if full_trace is not None:
                retrieval["procedural_expansion"]["full_document"] = full_trace
    else:
        retrieval = apply_ke_document_order(retrieval, fetcher, queries)
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
        # KE-05 reads inside the accepted document, kept compact for the audit
        # (documented_answer diagnostics are dropped by runtime memory compaction).
        "document_reads": {
            "procedure": _mapping(_mapping(retrieval.get("procedural_expansion")).get("document_search")) or None,
            "full_document": {k: v for k, v in _mapping(_mapping(retrieval.get("procedural_expansion")).get("full_document")).items()} or None,
            "exhaustive_list": {
                k: v for k, v in _mapping(_mapping(documented.get("validation")).get("exhaustive_evidence_expansion")).items()
                if k in {"activated", "reason", "base_count", "fetched_count", "added_count", "final_count"}
            } or None,
        },
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


def _publish_ke_answer(result: dict, shadow_result: Mapping[str, Any], store: Any, block: dict) -> None:
    """Replace the undocumented local answer with the documented KE answer."""
    local_answer = deepcopy(_mapping(result.get("answer")))
    answer = deepcopy(_mapping(shadow_result.get("answer")))
    answer["retrieval_provider"] = "henkia_ke"
    result["answer"] = answer
    result["local_answer_replaced"] = {
        "mode": local_answer.get("mode"),
        "knowledge_used": local_answer.get("knowledge_used"),
        "text_excerpt": str(local_answer.get("text") or "")[:300],
    }
    # Follow-up turns and the answer context must see the evidence that was published.
    result["retrieval"] = deepcopy(_mapping(shadow_result.get("retrieval")))
    for key in ("documented_answer", "procedural_answer", "conceptual_answer", "evidence_sufficiency"):
        if key in shadow_result:
            result[key] = deepcopy(shadow_result[key])
    memory = store.get("memory") if isinstance(store, Mapping) else None
    pending = getattr(memory, "pending_goal", None)
    if pending is not None:
        pending.status = "complete"
        if hasattr(memory, "to_dict"):
            result["state_after"] = deepcopy(memory.to_dict())
    block.update({
        "observational_only": False,
        "visible_to_user": True,
        "affects_publication": True,
        "published_provider": "henkia_ke",
        "production_changed": True,
    })
    block["comparison"]["publication_unchanged"] = False


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
        "publish_mode": publish_mode(config),
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
            shadow_result, message, continuity.get("answer_context") or {}, continuity, config, store
        )
        shadow_result["retrieval"] = shadow_retrieval
        shadow_result["answer"] = {"text": "", "mode": "ke_shadow_pending", "knowledge_used": False}
        shadow_result.pop("documented_answer", None)
        shadow_result.pop("procedural_answer", None)
        # Composers that read more of a document (exhaustive lists) search inside
        # the KE document instead of the local vectorstore while the KE route runs.
        token = KE_SAME_DOCUMENT_FETCHER.set(ke_document_fetcher(config, shadow_retrieval.get("diagnostic_evidence") or shadow_retrieval.get("evidence") or []))
        try:
            shadow_result, conceptual_trace, procedural_trace = answer_runner(
                shadow_result, message, config, session, budget, shadow_store
            )
        finally:
            KE_SAME_DOCUMENT_FETCHER.reset(token)
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
        probe = document_probe(config, shadow_retrieval, store)
        if probe is not None:
            block["document_probe"] = probe
        decision = complement_decision(
            block["publish_mode"], local_answer, _mapping(shadow_result.get("answer")), route, isolation
        )
        block["publication"] = decision
        if decision["applied"]:
            _publish_ke_answer(result, shadow_result, store, block)
    except Exception as exc:
        block["shadow_error"] = {"type": type(exc).__name__, "message": str(exc)[:500]}
        block["skip_reason"] = "shadow_execution_error"
    return block
