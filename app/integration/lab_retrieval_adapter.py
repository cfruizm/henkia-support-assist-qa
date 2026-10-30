from __future__ import annotations
from dataclasses import dataclass, asdict
from typing import Any

@dataclass
class RetrievedEvidence:
    text: str
    title: str = ""
    source: str = ""
    url: str = ""
    score: float | None = None
    metadata: dict | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def _normalize_document(doc: Any) -> RetrievedEvidence:
    metadata = getattr(doc, "metadata", {}) or {}
    if not isinstance(metadata, dict):
        metadata = {}

    text = str(getattr(doc, "page_content", "") or "").strip()
    title = str(metadata.get("title") or metadata.get("name") or "").strip()
    source = str(
        metadata.get("source")
        or metadata.get("source_url")
        or metadata.get("canonical_url")
        or ""
    ).strip()
    url = str(
        metadata.get("source_url")
        or metadata.get("canonical_url")
        or metadata.get("url")
        or ""
    ).strip()

    raw_score = metadata.get("rerank_score")
    if raw_score is None:
        raw_score = metadata.get("score")
    try:
        score = None if raw_score is None else float(raw_score)
    except (TypeError, ValueError):
        score = None

    return RetrievedEvidence(
        text=text[:12000],
        title=title[:500],
        source=source[:2000],
        url=url[:2000],
        score=score,
        metadata=metadata,
    )


def retrieve_from_productive_runtime(query: str, k: int = 6) -> dict:
    """Use the productive retrieval boundary without calling an LLM.

    app.retrieval_runtime.retrieve_context returns:
        (retrieved_context_text, retrieved_documents)

    Only retrieved_documents are converted into Agent Core V2 Clean evidence.
    The adapter does not import app.backend and does not alter chat state.
    """
    try:
        from app.retrieval_runtime import retrieve_context
    except Exception as exc:
        return {
            "ok": False,
            "adapter": "app.retrieval_runtime.retrieve_context",
            "query": query,
            "evidence": [],
            "count": 0,
            "error_code": "retriever_import_failed",
            "errors": [f"{type(exc).__name__}: {exc}"],
        }

    try:
        raw_result = retrieve_context(query, top_k=max(1, min(10, int(k))))
    except Exception as exc:
        return {
            "ok": False,
            "adapter": "app.retrieval_runtime.retrieve_context",
            "query": query,
            "evidence": [],
            "count": 0,
            "error_code": "retrieval_execution_failed",
            "errors": [f"{type(exc).__name__}: {exc}"],
        }

    if not isinstance(raw_result, tuple) or len(raw_result) < 2:
        return {
            "ok": False,
            "adapter": "app.retrieval_runtime.retrieve_context",
            "query": query,
            "evidence": [],
            "count": 0,
            "error_code": "unexpected_retrieval_contract",
            "errors": [f"Expected tuple(context, docs), received {type(raw_result).__name__}"],
        }

    retrieved_context, retrieved_docs = raw_result[0], raw_result[1]
    docs = list(retrieved_docs or [])
    evidence = [
        _normalize_document(doc).to_dict()
        for doc in docs[: max(1, min(10, int(k)))]
        if str(getattr(doc, "page_content", "") or "").strip()
    ]

    return {
        "ok": True,
        "adapter": "app.retrieval_runtime.retrieve_context",
        "query": query,
        "evidence": evidence,
        "count": len(evidence),
        "retrieved_context_chars": len(str(retrieved_context or "")),
        "document_count_before_normalization": len(docs),
        "errors": [],
        "llm_called": False,
        "production_state_changed": False,
    }


def retrieve_exact_document(source_identity: str, k: int = 40) -> dict:
    identity=str(source_identity or "").strip()
    if not identity:return {"ok":False,"evidence":[],"count":0,"error_code":"missing_source_identity"}
    try:
        from app.vectorstore_runtime import get_vectorstore
        raw=get_vectorstore()._collection.get(include=["documents","metadatas"],limit=20000)
    except Exception as exc:return {"ok":False,"evidence":[],"count":0,"error_code":"document_scan_failed","errors":[f"{type(exc).__name__}: {exc}"]}
    rows=[]
    for ordinal,(text,meta) in enumerate(zip(raw.get("documents") or [],raw.get("metadatas") or [])):
        meta=meta or {};identities={str(meta.get(x) or "").strip() for x in ("canonical_url","source","source_url")}
        if identity not in identities or not str(text or "").strip():continue
        try:page=int(meta.get("page",999999))
        except Exception:page=999999
        try:chunk=int(meta.get("chunk",meta.get("chunk_index",ordinal)))
        except Exception:chunk=ordinal
        rows.append((page,chunk,ordinal,RetrievedEvidence(text=str(text)[:6000],title=str(meta.get("title") or ""),source=identity,url=identity,score=None,metadata=meta).to_dict()))
    rows.sort(key=lambda x:(x[0],x[1],x[2]));e=[x[3] for x in rows[:max(1,min(60,int(k)))] ]
    return {"ok":True,"adapter":"exact_document_continuation","source_identity":identity,"evidence":e,"count":len(e),"same_page_chunks_preserved":True}
