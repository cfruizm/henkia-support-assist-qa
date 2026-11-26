"""Read-only Henkia Knowledge Engine adapter for KE-01.1."""
from __future__ import annotations
import time
from urllib.parse import urlparse
import requests
from requests import exceptions as req_exc
from .models import EvidenceItem,SearchResult
from .redaction import redact

def _get(c,key,default=None):
    g=getattr(c,"get",None)
    if not callable(g):return default
    try:return g(key,default)
    except TypeError:
        value=g(key);return default if value is None else value
def _bool(v):return v if isinstance(v,bool) else str(v or "").strip().casefold() in {"1","true","yes","on"}
def _float(v,default,minimum,maximum):
    try:return max(minimum,min(float(v),maximum))
    except Exception:return default
def _kb_ids(c):
    """Knowledge bases to search: HENKIA_KE_KB_IDS (list, or comma/space separated) else HENKIA_KE_KB_ID."""
    raw=_get(c,"HENKIA_KE_KB_IDS",None)
    if raw in (None,"",[]):raw=_get(c,"HENKIA_KE_KB_ID","")
    values=raw if isinstance(raw,(list,tuple)) else str(raw or "").replace(";",",").replace(" ",",").split(",")
    out=[]
    for value in values:
        value=str(value or "").strip()
        if value and value not in out:out.append(value)
    return out
def config(c):
    requested=_bool(_get(c,"KNOWLEDGE_COMPARE_ENABLED",False)) and str(_get(c,"KNOWLEDGE_COMPARE_PROVIDER","") or "").strip().casefold()=="henkia_ke"
    base=str(_get(c,"HENKIA_KE_BASE_URL","https://api-ke.lab.henkia.com/v1") or "").rstrip("/")
    key=str(_get(c,"HENKIA_KE_API_KEY","") or "");kb_ids=_kb_ids(c);kb=",".join(kb_ids)
    mode=str(_get(c,"HENKIA_KE_MODE","vector") or "vector").strip().casefold();maximum=max(1,min(int(_get(c,"HENKIA_KE_MAX_RESULTS",10) or 10),50))
    legacy=_float(_get(c,"HENKIA_KE_TIMEOUT_SECONDS",20),20,1,60)
    connect=_float(_get(c,"HENKIA_KE_CONNECT_TIMEOUT_SECONDS",3),3,1,15)
    read=_float(_get(c,"HENKIA_KE_READ_TIMEOUT_SECONDS",min(12,legacy)),min(12,legacy),1,45)
    errors=[]
    if requested and urlparse(base).scheme!="https":errors.append("base_url_must_use_https")
    if requested and not key:errors.append("api_key_missing")
    if requested and not kb:errors.append("knowledge_base_id_missing")
    if mode!="vector":errors.append("ke011_only_supports_vector_mode")
    return {"enabled":requested and not errors,"requested_enabled":requested,"base_url":base,"api_key":key,"knowledge_base_id":kb,"knowledge_base_ids":kb_ids,"mode":mode,"max_results":maximum,"connect_timeout_seconds":connect,"read_timeout_seconds":read,"ranker":"auto","errors":errors}
def _number(v):
    try:return float(v) if v is not None else None
    except Exception:return None
def _text_content(items,max_chars=1600):
    parts=[str(x.get("text") or "").strip() for x in (items or []) if isinstance(x,dict) and x.get("type")=="text" and str(x.get("text") or "").strip()]
    text="\n".join(parts);return text[:max_chars] or None,len(text)>max_chars
def normalize(payload,query,kb_id,latency_ms,http_status,request_diagnostic=None):
    rows=[]
    for raw in (payload or {}).get("data") or []:
        if not isinstance(raw,dict):continue
        attrs=raw.get("attributes") if isinstance(raw.get("attributes"),dict) else {};text,truncated=_text_content(raw.get("content"));chunk=str(attrs.get("chunk_id") or "").strip() or None
        rows.append(EvidenceItem(evidence_id=chunk,source_name=str(raw.get("filename") or "").strip() or None,content=text,score=_number(raw.get("score")),vector_score=_number(attrs.get("vector_score")),rerank_score=_number(attrs.get("rerank_score")),chunk_id=chunk,ordinal=attrs.get("ordinal"),document_kind=str(attrs.get("document_kind") or "").strip() or None,document_date=str(attrs.get("document_date") or "").strip() or None,page=None,section=None,reference_url=str(attrs.get("reference_url") or "").strip() or None,file_id=str(raw.get("file_id") or "").strip() or None,document_uri=str(attrs.get("document_uri") or "").strip() or None,content_truncated=truncated,knowledge_base_id=kb_id or None))
    return SearchResult(provider="henkia_ke",query=query,latency_ms=round(latency_ms,3),knowledge_base_id=kb_id,mode="vector",http_status=http_status,results=rows,has_more=(payload or {}).get("has_more"),next_page=(payload or {}).get("next_page"),published=False,request_diagnostic=request_diagnostic)
def _error_result(query,cfg,started,status,code,message=None,retryable=False,phase=None):
    return SearchResult(provider="henkia_ke",query=query,latency_ms=round((time.perf_counter()-started)*1000,3),knowledge_base_id=cfg.get("knowledge_base_id") or None,mode="vector",http_status=status,error={"code":code,"message":redact(message),"retryable":retryable,"timeout_phase":phase},published=False,request_diagnostic={"ranker":"auto","max_num_results":cfg.get("max_results"),"connect_timeout_seconds":cfg.get("connect_timeout_seconds"),"read_timeout_seconds":cfg.get("read_timeout_seconds")})
def search(query,config_obj):
    cfg=config(config_obj);diag={"ranker":"auto","max_num_results":cfg["max_results"],"connect_timeout_seconds":cfg["connect_timeout_seconds"],"read_timeout_seconds":cfg["read_timeout_seconds"]}
    if not cfg["enabled"]:
        code="disabled" if not cfg["requested_enabled"] else "invalid_configuration"
        return SearchResult(provider="henkia_ke",query=query,knowledge_base_id=cfg["knowledge_base_id"] or None,mode=cfg["mode"],error={"code":code,"details":cfg["errors"],"retryable":False},published=False,request_diagnostic=diag)
    ids=cfg["knowledge_base_ids"]
    if len(ids)==1:return _search_with_retry(query,cfg,ids[0])
    return _search_many(query,cfg,ids)
# Transient failures that happen while opening the connection (TCP/TLS on a cold
# start) are reported as connect or read timeouts at about the connect timeout.
_QUICK_RETRY_CODES={"connect_timeout","read_timeout","connection_error"}
def _search_with_retry(query,cfg,kb_id,extra=None):
    """One retry for a base that failed fast with a transient connection error.

    A real slow search (read timeout near the read limit) is not retried, so the
    worst case stays bounded at about connect timeout + one full request.
    """
    first=_search_one(query,cfg,kb_id,extra)
    code=(first.error or {}).get("code")
    fast=(first.latency_ms or 0)<=(cfg["connect_timeout_seconds"]+1.5)*1000
    if code not in _QUICK_RETRY_CODES or not fast:return first
    second=_search_one(query,cfg,kb_id,extra)
    diag=dict(second.request_diagnostic or {})
    diag.update({"retried":True,"first_error_code":code,"first_latency_ms":first.latency_ms})
    second.request_diagnostic=diag
    return second
def _search_many(query,cfg,ids):
    """Search several knowledge bases in parallel and merge by score.

    The KE searches one base per request. All bases go through the same KE ranker,
    so scores are treated as comparable; the merged list keeps the global top
    max_results and every row records the base it came from. A base that fails
    is reported in request_diagnostic and does not discard the others.
    """
    from concurrent.futures import ThreadPoolExecutor
    started=time.perf_counter()
    with ThreadPoolExecutor(max_workers=min(4,len(ids))) as pool:
        parts=list(pool.map(lambda kb:_search_with_retry(query,cfg,kb),ids))
    per_base=[{"knowledge_base_id":kb,"http_status":part.http_status,"count":len(part.results),"latency_ms":part.latency_ms,"error_code":(part.error or {}).get("code"),"retried":bool((part.request_diagnostic or {}).get("retried"))} for kb,part in zip(ids,parts)]
    diag={"ranker":"auto","max_num_results":cfg["max_results"],"connect_timeout_seconds":cfg["connect_timeout_seconds"],"read_timeout_seconds":cfg["read_timeout_seconds"],"knowledge_bases":per_base,"strategy":"parallel_merge_by_score"}
    ok=[part for part in parts if part.http_status==200 and not part.error]
    if not ok:
        first=parts[0];first.knowledge_base_id=cfg["knowledge_base_id"];first.request_diagnostic=diag;return first
    rows=[row for part in ok for row in part.results]
    rows.sort(key=lambda row:(row.score if row.score is not None else float("-inf")),reverse=True)
    if len(ok)<len(parts):diag["partial_failure"]=True
    return SearchResult(provider="henkia_ke",query=query,latency_ms=round((time.perf_counter()-started)*1000,3),knowledge_base_id=cfg["knowledge_base_id"],mode="vector",http_status=200,results=rows[:cfg["max_results"]],has_more=any(bool(part.has_more) for part in ok),next_page=None,published=False,request_diagnostic=diag)
def search_document(query,config_obj,kb_id,document_uri,max_results=12):
    """Search inside one KE document (rag.filters.document_uri), read-only.

    ``query`` may be a list: the KE merges several queries (e.g. message + goal).
    A filter that matches nothing returns an empty result, not an error.
    """
    cfg=config(config_obj)
    if not cfg["enabled"] or not kb_id or not document_uri:
        return SearchResult(provider="henkia_ke",query=str(query),knowledge_base_id=kb_id or None,mode="vector",error={"code":"disabled" if not cfg["enabled"] else "missing_document","retryable":False},published=False)
    cfg={**cfg,"max_results":max(1,min(int(max_results),50))}
    extra={"rag":{"filters":{"document_uri":[str(document_uri)]}}}
    return _search_with_retry(query,cfg,kb_id,extra)
def _search_one(query,cfg,kb_id,extra=None):
    diag={"ranker":"auto","max_num_results":cfg["max_results"],"connect_timeout_seconds":cfg["connect_timeout_seconds"],"read_timeout_seconds":cfg["read_timeout_seconds"]}
    if extra:diag["filtered_document"]=True
    cfg={**cfg,"knowledge_base_id":kb_id}
    url=f'{cfg["base_url"]}/vector_stores/{kb_id}/search';started=time.perf_counter();status=None
    payload={"query":query,"max_num_results":cfg["max_results"],"ranking_options":{"ranker":"auto"},**(extra or {})}
    try:
        response=requests.post(url,headers={"accept":"*/*","Authorization":f'Bearer {cfg["api_key"]}',"Content-Type":"application/json"},json=payload,timeout=(cfg["connect_timeout_seconds"],cfg["read_timeout_seconds"]))
        status=response.status_code;latency=(time.perf_counter()-started)*1000
        if not response.ok:
            code="http_error";detail=None
            try:
                body=response.json();code=str(body.get("type") or (body.get("error") or {}).get("type") or code);detail=body.get("param") or body.get("detail") or body.get("message")
            except Exception:detail=response.text[:300]
            return _error_result(query,cfg,started,status,redact(code),detail,status in {408,429,500,502,503,504})
        return normalize(response.json(),query,cfg["knowledge_base_id"],latency,status,diag)
    except req_exc.ConnectTimeout as exc:return _error_result(query,cfg,started,status,"connect_timeout",exc,True,"connect")
    except req_exc.ReadTimeout as exc:return _error_result(query,cfg,started,status,"read_timeout",exc,True,"read")
    except requests.Timeout as exc:return _error_result(query,cfg,started,status,"timeout",exc,True,"unknown")
    except req_exc.ConnectionError as exc:return _error_result(query,cfg,started,status,"connection_error",exc,True,None)
    except Exception as exc:return _error_result(query,cfg,started,status,type(exc).__name__,exc,True,None)
