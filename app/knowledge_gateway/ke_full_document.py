"""KE-05.3: use the full text of an accepted KE document for procedures.

The KE route normally composes a procedure from up to 10 chunks of the
accepted document. When enabled (HENKIA_KE_FULL_DOCUMENT=procedural) and the
KE answer is the one the user will see (the local answer has no
documentation), the full text is read once per document and conversation
through MCP leer_documento, split into ordered sections and the relevant
sections replace the chunks. Any failure keeps the current chunks.
"""
from __future__ import annotations

import re
from copy import deepcopy
from typing import Any, Callable, Mapping

from app.agent_core_v2_clean.text_stems import collapse_by_stem, stem_index, term_matches, normalize

TEXT_CACHE_KEY = "ke_document_text_cache"
# Bases where a full-document read failed in this conversation. QA: leer_documento
# failed twice on the Impresion base (ConnectionError after 13-16 s) while it works
# on OperacionSIMP; retrying on every turn only made users wait.
FAILED_BASES_KEY = "ke_full_document_failed_bases"
MAX_CACHED_DOCUMENTS = 3
SECTION_CHARS = 1500
MAX_SECTIONS = 8
MAX_SELECTED_CHARS = 9000
MIN_TERM_LENGTH = 4


def enabled(config: Any) -> bool:
    getter = getattr(config, "get", lambda *_: None)
    return str(getter("HENKIA_KE_FULL_DOCUMENT", "off") or "off").strip().casefold() == "procedural"


def _mapping(value: Any) -> dict:
    return dict(value) if isinstance(value, Mapping) else {}


REPEATED_LINE_MIN = 3
REPEATED_LINE_CHARS = 12


def strip_repeated_lines(text: str) -> str:
    """Keep only the first occurrence of lines repeated across the document.

    PDF page headers and footers (title, area, code, date) come back on every
    page; in QA they filled most of each carried section. Detected by
    repetition, not by content, so no word list is involved.
    """
    lines = str(text or "").splitlines()
    counts: dict[str, int] = {}
    for line in lines:
        key = " ".join(line.split()).casefold()
        if len(key) >= REPEATED_LINE_CHARS:
            counts[key] = counts.get(key, 0) + 1
    seen: set[str] = set()
    kept = []
    for line in lines:
        key = " ".join(line.split()).casefold()
        if counts.get(key, 0) >= REPEATED_LINE_MIN:
            if key in seen:
                continue
            seen.add(key)
        kept.append(line)
    return "\n".join(kept)


def split_sections(text: str, size: int = SECTION_CHARS) -> list[str]:
    """Ordered sections of about ``size`` characters, cut at paragraph breaks."""
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", str(text or "")) if p.strip()]
    sections, current = [], ""
    for paragraph in paragraphs:
        while len(paragraph) > size:  # a very long paragraph is cut at a sentence end
            cut = paragraph.rfind(". ", 0, size)
            cut = cut + 1 if cut > size // 2 else size
            if current:
                sections.append(current)
                current = ""
            sections.append(paragraph[:cut].strip())
            paragraph = paragraph[cut:].strip()
        if current and len(current) + len(paragraph) + 2 > size:
            sections.append(current)
            current = paragraph
        else:
            current = f"{current}\n\n{paragraph}" if current else paragraph
    if current:
        sections.append(current)
    return sections


def _request_terms(request_text: str) -> set[str]:
    words = {w for w in re.findall(r"[a-z0-9]+", normalize(request_text)) if len(w) >= MIN_TERM_LENGTH and not w.isdigit()}
    return collapse_by_stem(words)


def select_sections(sections: list[str], request_text: str) -> list[int]:
    """Indexes of the sections to use, in document order.

    The first section (scope) and the last (closing/validations) are always
    kept; the others are ranked by how many request terms they contain (stem
    match, no word lists). Returns [] when no section matches the request.
    """
    if not sections:
        return []
    terms = _request_terms(request_text)
    scores = []
    for index, section in enumerate(sections):
        available = stem_index({w for w in re.findall(r"[a-z0-9]+", normalize(section)) if len(w) >= 3})
        scores.append(sum(1 for term in terms if term_matches(term, available)))
    if not any(scores):
        return []
    chosen = [0] if len(sections) == 1 else [0, len(sections) - 1]
    used = sum(len(sections[i]) for i in chosen)
    ranked = sorted((i for i in range(len(sections)) if i not in chosen and scores[i] > 0), key=lambda i: (-scores[i], i))
    for index in ranked:
        if len(chosen) >= MAX_SECTIONS or used + len(sections[index]) > MAX_SELECTED_CHARS:
            continue
        chosen.append(index)
        used += len(sections[index])
    return sorted(set(chosen))


def _cached_text(store: Any, uri: str) -> str | None:
    cache = store.get(TEXT_CACHE_KEY) if isinstance(store, dict) else None
    return (cache or {}).get(uri)


def _cache_text(store: Any, uri: str, text: str) -> None:
    if not isinstance(store, dict):
        return
    cache = store.setdefault(TEXT_CACHE_KEY, {})
    cache.pop(uri, None)
    cache[uri] = text
    while len(cache) > MAX_CACHED_DOCUMENTS:
        cache.pop(next(iter(cache)))


def _mark_failed(store: Any, kb_id: str, code: str) -> None:
    if isinstance(store, dict) and kb_id:
        store.setdefault(FAILED_BASES_KEY, {})[kb_id] = str(code)


def apply_full_document(retrieval: dict, reader: Callable, store: Any, request_text: str) -> dict:
    """Replace the accepted KE chunks with the relevant sections of the full text.

    ``reader(kb_id, uri)`` returns the read_full_document dict. The returned
    trace never contains document text.
    """
    selected = list(retrieval.get("generation_evidence") or [])
    if not selected:
        return {"used": False, "reason": "no_accepted_document"}
    seed = selected[0]
    uri = str(seed.get("source") or "")
    metadata = _mapping(seed.get("metadata"))
    kb_id = str(metadata.get("knowledge_base_id") or "")
    text = _cached_text(store, uri)
    trace = {"used": False, "cached": text is not None}
    failed = store.get(FAILED_BASES_KEY) if isinstance(store, dict) else None
    if text is None and kb_id and (failed or {}).get(kb_id):
        return {**trace, "reason": "skipped_after_failure", "error_code": failed[kb_id]}
    if text is None:
        try:
            raw = reader(kb_id, uri) or {}
        except Exception as exc:  # network/contract failure: keep the chunks
            _mark_failed(store, kb_id, type(exc).__name__)
            return {**trace, "reason": "read_error", "error_code": type(exc).__name__}
        trace.update(latency_ms=raw.get("latency_ms"), schema_cached=raw.get("schema_cached"))
        if not raw.get("ok") or not raw.get("text"):
            _mark_failed(store, kb_id, raw.get("error_code") or "read_failed")
            return {**trace, "reason": "read_failed", "error_code": raw.get("error_code")}
        text = strip_repeated_lines(str(raw["text"]))
        _cache_text(store, uri, text)
    sections = split_sections(text)
    chosen = select_sections(sections, request_text)
    trace.update(chars=len(text), sections=len(sections), selected_sections=chosen)
    if not chosen:
        return {**trace, "reason": "no_section_matches_request"}
    rows = []
    for position, index in enumerate(chosen, 1):
        row_metadata = {**deepcopy(metadata), "ordinal": index, "chunk_id": f"full-{index}", "page_unknown": True}
        rows.append({
            "id": f"R{position}", "title": seed.get("title"), "source": uri, "url": seed.get("url") or "",
            "page": "", "text": sections[index], "metadata": row_metadata, "origin": "ke_full_document",
        })
    retrieval["generation_evidence"] = deepcopy(rows)
    retrieval["evidence"] = deepcopy(rows)
    verdict = deepcopy(retrieval.get("evidence_verdict") or {})
    verdict["selected_evidence"] = deepcopy(rows)
    verdict["evidence_ids"] = [r["id"] for r in rows]
    retrieval["evidence_verdict"] = verdict
    trace.update(used=True, reason="full_document_sections")
    return trace
