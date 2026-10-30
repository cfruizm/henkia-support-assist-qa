"""Attach non-publishable local-vs-KE retrieval diagnostics."""
from __future__ import annotations
from copy import deepcopy
from typing import Mapping
from .henkia_knowledge_engine import search

def _m(v):return dict(v) if isinstance(v,Mapping) else {}
def _title(item):
    if not isinstance(item,dict):return None
    meta=_m(item.get("metadata"));return str(item.get("title") or meta.get("title") or item.get("source") or "").strip() or None
def _score(item):
    if not isinstance(item,dict):return None
    fit=_m(item.get("semantic_fit"))
    for value in (item.get("score"),fit.get("score"),item.get("rerank_score"),item.get("vector_score")):
        try:
            if value is not None:return float(value)
        except Exception:pass
    return None
def _local_summary(retrieval):
    items=(retrieval or {}).get("generation_evidence") or (retrieval or {}).get("evidence") or []
    docs=[];scores=[]
    for item in items[:10]:
        title=_title(item)
        if title and title not in docs:docs.append(title)
        score=_score(item)
        if score is not None:scores.append(score)
    return {"provider":"local_chroma","published":True,"result_count":len(items),"top_documents":docs[:5],"scores":scores[:10],"evidence_status":_m((retrieval or {}).get("evidence_verdict")).get("status"),"latency_ms":(retrieval or {}).get("latency_ms")}
def _ke_summary(ke):
    rows=ke.get("results") or [];names=[]
    for row in rows:
        name=row.get("source_name")
        if name and name not in names:names.append(name)
    return {"provider":"henkia_ke","published":False,"result_count":len(rows),"top_documents":names[:5],"top_score":rows[0].get("score") if rows else None,"scores":[{"score":r.get("score"),"vector_score":r.get("vector_score"),"rerank_score":r.get("rerank_score")} for r in rows[:10]],"latency_ms":ke.get("latency_ms"),"http_status":ke.get("http_status"),"error":deepcopy(ke.get("error"))}
def attach(result,retrieval,message,config):
    query=str(_m((retrieval or {}).get("query")).get("text") or message or "").strip()
    ke=search(query,config).to_dict()
    local=_local_summary(retrieval)
    ke_sum=_ke_summary(ke)
    common=sorted(set(local["top_documents"]) & set(ke_sum["top_documents"]))
    error_code=_m(ke.get("error")).get("code")
    block={"schema_version":1,"enabled":error_code!="disabled","observational_only":True,"published_provider":"local_chroma","compared_provider":"henkia_ke","query":query,"local_chroma":local,"henkia_ke":ke_sum,"comparison":{"top_document_match":bool(local["top_documents"] and ke_sum["top_documents"] and local["top_documents"][0]==ke_sum["top_documents"][0]),"common_top_documents":common,"ke_result_count":ke_sum["result_count"],"local_result_count":local["result_count"]},"normalized_result":ke,"production_changed":False,"fallback_used":False}
    result["knowledge_comparison"]=block
    return block
