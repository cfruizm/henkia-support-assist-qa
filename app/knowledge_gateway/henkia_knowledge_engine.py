"""Read-only adapter for Henkia Knowledge Engine /search."""
from __future__ import annotations
import time
from urllib.parse import urlparse
import requests
from .models import EvidenceItem, SearchResult
from .redaction import redact

def _get(c,key,default=None):
    g=getattr(c,"get",None)
    if not callable(g):return default
    try:return g(key,default)
    except TypeError:
        v=g(key);return default if v is None else v

def _bool(v):
    if isinstance(v,bool):return v
    return str(v or "").strip().casefold() in {"1","true","yes","on"}

def config(config):
    enabled=_bool(_get(config,"KNOWLEDGE_COMPARE_ENABLED",False)) and str(_get(config,"KNOWLEDGE_COMPARE_PROVIDER","") or "").strip().casefold()=="henkia_ke"
    base=str(_get(config,"HENKIA_KE_BASE_URL","https://api-ke.lab.henkia.com/v1") or "").rstrip("/")
    key=str(_get(config,"HENKIA_KE_API_KEY","") or "")
    kb=str(_get(config,"HENKIA_KE_KB_ID","") or "")
    mode=str(_get(config,"HENKIA_KE_MODE","vector") or "vector").strip().casefold()
    timeout=max(1.0,min(float(_get(config,"HENKIA_KE_TIMEOUT_SECONDS",20) or 20),60.0))
    maximum=max(1,min(int(_get(config,"HENKIA_KE_MAX_RESULTS",10) or 10),50))
    errors=[]
    if enabled and urlparse(base).scheme!="https":errors.append("base_url_must_use_https")
    if enabled and not key:errors.append("api_key_missing")
    if enabled and not kb:errors.append("knowledge_base_id_missing")
    if mode!="vector":errors.append("ke01_only_supports_vector_mode")
    return {"enabled":enabled and not errors,"requested_enabled":enabled,"base_url":base,"api_key":key,"knowledge_base_id":kb,"mode":mode,"timeout_seconds":timeout,"max_results":maximum,"errors":errors}

def _number(v):
    try:return float(v) if v is not None else None
    except Exception:return None

def _text_content(items,max_chars=1600):
    parts=[]
    for item in items or []:
        if isinstance(item,dict) and item.get("type")=="text" and str(item.get("text") or "").strip():parts.append(str(item["text"]).strip())
    text="\n".join(parts);return text[:max_chars] or None,len(text)>max_chars

def normalize(payload,query,kb_id,latency_ms,http_status):
    rows=[]
    for raw in (payload or {}).get("data") or []:
        if not isinstance(raw,dict):continue
        attrs=raw.get("attributes") if isinstance(raw.get("attributes"),dict) else {}
        text,truncated=_text_content(raw.get("content"))
        chunk=str(attrs.get("chunk_id") or "").strip() or None
        ref=str(attrs.get("reference_url") or "").strip() or None
        date=str(attrs.get("document_date") or "").strip() or None
        rows.append(EvidenceItem(evidence_id=chunk,source_name=str(raw.get("filename") or "").strip() or None,content=text,score=_number(raw.get("score")),vector_score=_number(attrs.get("vector_score")),rerank_score=_number(attrs.get("rerank_score")),chunk_id=chunk,ordinal=attrs.get("ordinal"),document_kind=str(attrs.get("document_kind") or "").strip() or None,document_date=date,page=None,section=None,reference_url=ref,file_id=str(raw.get("file_id") or "").strip() or None,document_uri=str(attrs.get("document_uri") or "").strip() or None,content_truncated=truncated))
    return SearchResult(provider="henkia_ke",query=query,latency_ms=round(latency_ms,3),knowledge_base_id=kb_id,mode="vector",http_status=http_status,results=rows,has_more=(payload or {}).get("has_more"),next_page=(payload or {}).get("next_page"),published=False)

def search(query,config_obj):
    cfg=config(config_obj)
    if not cfg["enabled"]:
        code="disabled" if not cfg["requested_enabled"] else "invalid_configuration"
        return SearchResult(provider="henkia_ke",query=query,knowledge_base_id=cfg["knowledge_base_id"] or None,mode=cfg["mode"],error={"code":code,"details":cfg["errors"],"retryable":False},published=False)
    url=f'{cfg["base_url"]}/vector_stores/{cfg["knowledge_base_id"]}/search'
    started=time.perf_counter();status=None
    try:
        response=requests.post(url,headers={"accept":"*/*","Authorization":f'Bearer {cfg["api_key"]}',"Content-Type":"application/json"},json={"query":query,"max_num_results":cfg["max_results"]},timeout=cfg["timeout_seconds"])
        status=response.status_code;latency=(time.perf_counter()-started)*1000
        if not response.ok:
            code="http_error";detail=None
            try:
                body=response.json();code=str(body.get("type") or body.get("error",{}).get("type") or code);detail=body.get("param") or body.get("detail") or body.get("message")
            except Exception:detail=response.text[:300]
            return SearchResult(provider="henkia_ke",query=query,latency_ms=round(latency,3),knowledge_base_id=cfg["knowledge_base_id"],mode="vector",http_status=status,error={"code":redact(code),"message":redact(detail),"retryable":status in {408,429,500,502,503,504}},published=False)
        return normalize(response.json(),query,cfg["knowledge_base_id"],latency,status)
    except requests.Timeout:
        return SearchResult(provider="henkia_ke",query=query,latency_ms=round((time.perf_counter()-started)*1000,3),knowledge_base_id=cfg["knowledge_base_id"],mode="vector",http_status=status,error={"code":"timeout","retryable":True},published=False)
    except Exception as exc:
        return SearchResult(provider="henkia_ke",query=query,latency_ms=round((time.perf_counter()-started)*1000,3),knowledge_base_id=cfg["knowledge_base_id"],mode="vector",http_status=status,error={"code":type(exc).__name__,"message":redact(exc),"retryable":True},published=False)
