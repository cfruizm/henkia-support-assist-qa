"""Attach KE comparison and normalize documentary identities."""
from __future__ import annotations
from copy import deepcopy
import re,unicodedata
from typing import Mapping
from .henkia_knowledge_engine import search

def _m(v):return dict(v) if isinstance(v,Mapping) else {}
def normalize_document_name(value):
    text=unicodedata.normalize("NFKD",str(value or "")).encode("ascii","ignore").decode("ascii").casefold().strip()
    text=re.sub(r"\.(pdf|docx?|pptx?|xlsx?)$","",text);return " ".join(re.findall(r"[a-z0-9]+",text))
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
def _docs(items):
    display=[];normalized=[]
    for item in items[:10]:
        title=_title(item)
        if title and title not in display:display.append(title);normalized.append(normalize_document_name(title))
    return display,normalized
def _local_summary(retrieval):
    items=(retrieval or {}).get("generation_evidence") or (retrieval or {}).get("evidence") or [];docs,norm=_docs(items);scores=[x for x in (_score(i) for i in items[:10]) if x is not None]
    return {"provider":"local_chroma","published":True,"result_count":len(items),"top_documents":docs[:5],"normalized_top_documents":norm[:5],"scores":scores[:10],"evidence_status":_m((retrieval or {}).get("evidence_verdict")).get("status"),"latency_ms":(retrieval or {}).get("latency_ms")}
def _ke_summary(ke):
    rows=ke.get("results") or [];names=[]
    for row in rows:
        name=row.get("source_name")
        if name and name not in names:names.append(name)
    return {"provider":"henkia_ke","published":False,"result_count":len(rows),"top_documents":names[:5],"normalized_top_documents":[normalize_document_name(x) for x in names[:5]],"top_score":rows[0].get("score") if rows else None,"scores":[{"score":r.get("score"),"vector_score":r.get("vector_score"),"rerank_score":r.get("rerank_score")} for r in rows[:10]],"latency_ms":ke.get("latency_ms"),"http_status":ke.get("http_status"),"error":deepcopy(ke.get("error")),"request_diagnostic":deepcopy(ke.get("request_diagnostic"))}
def attach(result,retrieval,message,config):
    query=str(_m((retrieval or {}).get("query")).get("text") or message or "").strip();ke=search(query,config).to_dict();local=_local_summary(retrieval);ks=_ke_summary(ke)
    common_norm=sorted(set(local["normalized_top_documents"]) & set(ks["normalized_top_documents"]));display_by_norm={normalize_document_name(x):x for x in local["top_documents"]+ks["top_documents"]}
    top_match=bool(local["normalized_top_documents"] and ks["normalized_top_documents"] and local["normalized_top_documents"][0]==ks["normalized_top_documents"][0])
    block={"schema_version":2,"enabled":_m(ke.get("error")).get("code")!="disabled","observational_only":True,"published_provider":"local_chroma","compared_provider":"henkia_ke","query":query,"local_chroma":local,"henkia_ke":ks,"comparison":{"top_document_match":top_match,"top5_document_match":bool(common_norm),"common_top_documents":[display_by_norm[x] for x in common_norm],"common_normalized_documents":common_norm,"ke_result_count":ks["result_count"],"local_result_count":local["result_count"]},"normalized_result":ke,"production_changed":False,"fallback_used":False}
    result["knowledge_comparison"]=block;return block
