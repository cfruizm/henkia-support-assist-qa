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
        rows.append(EvidenceItem(evidence_id=chunk,source_name=str(raw.get("filename") or "").strip() or None,content=text,score=_number(raw.get("score")),vector_score=_number(attrs.get("vector_score")),rerank_score=_number(attrs.get("rerank_score")),chunk_id=chunk,ordinal=attrs.get("ordinal"),document_kind=str(attrs.get("document_kind") or "").strip() or None,document_date=str(attrs.get("document_date") or "").strip() or None,page=None,section=None,reference_url=str(attrs.get("reference_url") or "").strip() or None,file_id=str(raw.get("file_id") or "").strip() or None,document_uri=str(attrs.get("document_uri") or "").strip() or None,content_truncated=truncated,knowledge_base_id=kb_id or None,document_title=str(attrs.get("document_title") or "").strip() or None))
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


def _root_url(base_url):
    """KE root for non-/v1 endpoints (the configured base ends in /v1)."""
    base=str(base_url or "").rstrip("/")
    return base[:-3] if base.endswith("/v1") else base


def fetch_document(config_obj,kb_id,document_uri):
    """Read one KE document as text (GET /knowledge-bases/{id}/document?uri=).

    The KE brings the text live from the source and authorizes by identity; the
    service key goes in X-Api-Key (this endpoint is outside /v1). Returns a dict
    with ok, http_status, error_code, document_name, text and latency_ms.
    """
    cfg=config(config_obj);started=time.perf_counter()
    def done(ok,status=None,code=None,name=None,text=""):
        return {"ok":ok,"http_status":status,"error_code":code,"document_name":name,"text":text,
                "latency_ms":round((time.perf_counter()-started)*1000,3)}
    if not cfg["enabled"] or not kb_id or not document_uri:
        return done(False,code="disabled" if not cfg["enabled"] else "missing_document")
    url=f'{_root_url(cfg["base_url"])}/knowledge-bases/{kb_id}/document'
    try:
        response=requests.get(url,params={"uri":str(document_uri)},headers={"accept":"application/json","X-Api-Key":cfg["api_key"]},
                              timeout=(cfg["connect_timeout_seconds"],cfg["read_timeout_seconds"]))
    except req_exc.ConnectTimeout:return done(False,code="connect_timeout")
    except req_exc.ReadTimeout:return done(False,code="read_timeout")
    except requests.RequestException as exc:return done(False,code=type(exc).__name__)
    if not response.ok:
        code="http_error"
        try:
            body=response.json();code=str(body.get("code") or body.get("type") or (body.get("error") or {}).get("code") or body.get("detail") or code)[:80]
        except Exception:pass
        return done(False,response.status_code,redact(code))
    try:body=response.json()
    except Exception:return done(False,response.status_code,"invalid_json")
    return done(True,response.status_code,None,str(body.get("document_name") or ""),str(body.get("text") or ""))


_MCP_HEADERS={"Accept":"application/json, text/event-stream","Content-Type":"application/json","MCP-Protocol-Version":"2025-06-18"}


def _response_text(response):
    """Body as UTF-8. An SSE response without charset is decoded as ISO-8859-1 by
    requests (QA: "configuraciÃ³n"), so the raw bytes are decoded explicitly."""
    content=getattr(response,"content",None)
    if isinstance(content,(bytes,bytearray)):return bytes(content).decode("utf-8",errors="replace")
    return str(getattr(response,"text","") or "")


def _mcp_payload(response):
    """JSON-RPC message from a Streamable HTTP response (JSON or SSE)."""
    import json as _json
    if "text/event-stream" in str(response.headers.get("content-type") or ""):
        for line in _response_text(response).splitlines():
            if line.startswith("data:"):
                try:return _json.loads(line[5:].strip())
                except ValueError:continue
        return {}
    content=getattr(response,"content",None)
    if isinstance(content,(bytes,bytearray)):return _json.loads(_response_text(response))
    return response.json()


def _tool_document_text(text):
    """Plain document text from a leer_documento result.

    The tool returns a JSON object (base, uri, ... and the text) as its text
    content; the document is the longest string value. Plain text is kept.
    """
    value=str(text or "").strip()
    if not value.startswith("{"):return value
    import json as _json
    try:data=_json.loads(value)
    except ValueError:return value
    if not isinstance(data,dict):return value
    strings=[v for v in data.values() if isinstance(v,str)]
    return max(strings,key=len) if strings else value


# The probe is observational and runs once per document: give MCP more room than
# a search, so a slow first exchange is told apart from a real refusal.
MCP_TIMEOUT=(8.0,20.0)


def _mcp_request(cfg,method,params,request_id,steps,timeout=None):
    url=f'{_root_url(cfg["base_url"])}/mcp'
    headers={**_MCP_HEADERS,"Authorization":f'Bearer {cfg["api_key"]}'}
    body={"jsonrpc":"2.0","id":request_id,"method":method,"params":params}
    started=time.perf_counter();step={"step":method}
    steps.append(step)
    try:
        response=requests.post(url,headers=headers,json=body,timeout=timeout or MCP_TIMEOUT)
    except requests.RequestException as exc:
        step.update(error=type(exc).__name__,detail=redact(str(exc))[:160],ms=round((time.perf_counter()-started)*1000))
        raise
    step.update(http_status=response.status_code,content_type=str(response.headers.get("content-type") or "")[:40],ms=round((time.perf_counter()-started)*1000))
    return response.status_code,(_mcp_payload(response) if response.ok else {})


def _mcp_arguments(schema,kb_id,document_uri):
    """Map leer_documento input properties to our values by name (schema discovered live)."""
    args={}
    for name in (schema.get("properties") or {}):
        low=name.casefold()
        if "uri" in low or "document" in low or low in {"source","name"}:args[name]=str(document_uri)
        elif "base" in low or "knowledge" in low or low in {"kb","kb_id"}:args[name]=str(kb_id)
    return args


def mcp_read_document(config_obj,kb_id,document_uri,tool="leer_documento",max_chars=None,timeout=None):
    """Read a KE document through the MCP tool, with the M2M key as Bearer.

    /mcp accepts the key in Authorization (outside /v1 that header belongs to
    the BFF service key). Returns ok, http_status, error_code, schema, text and
    latency_ms; the tool's input schema is discovered with tools/list.
    """
    cfg=config(config_obj);started=time.perf_counter()
    steps=[]
    out={"ok":False,"http_status":None,"error_code":None,"schema":None,"text":"","latency_ms":None,"steps":steps}
    def done(**kw):
        out.update(kw);out["latency_ms"]=round((time.perf_counter()-started)*1000,3);return out
    if not cfg["enabled"] or not kb_id or not document_uri:return done(error_code="disabled")
    try:
        status,_=_mcp_request(cfg,"initialize",{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"support-assist","version":"1"}},1,steps,timeout)
        if status>=400:return done(http_status=status,error_code="initialize_failed")
        status,listing=_mcp_request(cfg,"tools/list",{},2,steps,timeout)
        tools={t.get("name"):t for t in ((listing.get("result") or {}).get("tools") or []) if isinstance(t,dict)}
        if status>=400 or tool not in tools:return done(http_status=status,error_code="tool_not_listed" if status<400 else "tools_list_failed")
        schema=tools[tool].get("inputSchema") or {}
        out["schema"]={"properties":sorted((schema.get("properties") or {}).keys()),"required":list(schema.get("required") or [])}
        out["raw_schema"]=schema
        arguments=_mcp_arguments_with_limit(schema,kb_id,document_uri,max_chars) if max_chars else _mcp_arguments(schema,kb_id,document_uri)
        status,called=_mcp_request(cfg,"tools/call",{"name":tool,"arguments":arguments},3,steps,timeout)
    except req_exc.ConnectTimeout:return done(error_code="connect_timeout")
    except req_exc.ReadTimeout:return done(error_code="read_timeout")
    except (requests.RequestException,ValueError) as exc:return done(error_code=type(exc).__name__)
    if status>=400:return done(http_status=status,error_code="tools_call_failed")
    if called.get("error"):return done(http_status=status,error_code=redact(str((called.get("error") or {}).get("code") or "jsonrpc_error")))
    result=called.get("result") or {}
    text=_tool_document_text("\n".join(str(c.get("text") or "") for c in (result.get("content") or []) if isinstance(c,dict) and c.get("type")=="text"))
    if result.get("isError"):return done(http_status=status,error_code=redact(text[:120]) or "tool_error")
    return done(ok=bool(text),http_status=status,text=text,error_code=None if text else "empty_document")


# Tool input schemas discovered with tools/list, per KE host and tool. The MCP
# server is stateless, so after the first discovery a read is a single
# tools/call (about 5 s instead of 8 s measured in QA).
_MCP_SCHEMAS={}
FULL_DOCUMENT_MAX_CHARS=30000
FULL_DOCUMENT_TIMEOUT=(5.0,10.0)


def _mcp_arguments_with_limit(schema,kb_id,document_uri,max_chars):
    args=_mcp_arguments(schema,kb_id,document_uri)
    for name in (schema.get("properties") or {}):
        low=name.casefold()
        if low.startswith("max") and ("caracter" in low or "char" in low):args[name]=int(max_chars)
    return args


def _mcp_text(called):
    result=called.get("result") or {}
    text=_tool_document_text("\n".join(str(c.get("text") or "") for c in (result.get("content") or []) if isinstance(c,dict) and c.get("type")=="text"))
    return text,bool(result.get("isError"))


def read_full_document(config_obj,kb_id,document_uri,max_chars=FULL_DOCUMENT_MAX_CHARS,tool="leer_documento"):
    """Full text of one KE document through MCP leer_documento.

    First call per host discovers the tool schema (initialize + tools/list +
    tools/call); later calls send only tools/call. A failed direct call falls
    back once to the full handshake. Returns ok, text, error_code, latency_ms,
    schema_cached and steps (no text in steps).
    """
    cfg=config(config_obj);started=time.perf_counter()
    key=(_root_url(cfg["base_url"]),tool)
    def done(ok,text="",code=None,cached=False,steps=None):
        return {"ok":ok,"text":text,"error_code":code,"schema_cached":cached,"steps":steps or [],
                "latency_ms":round((time.perf_counter()-started)*1000,3)}
    if not cfg["enabled"] or not kb_id or not document_uri:return done(False,code="disabled")
    schema=_MCP_SCHEMAS.get(key)
    if schema is not None:
        steps=[]
        try:
            status,called=_mcp_request(cfg,"tools/call",{"name":tool,"arguments":_mcp_arguments_with_limit(schema,kb_id,document_uri,max_chars)},3,steps,FULL_DOCUMENT_TIMEOUT)
            text,is_error=_mcp_text(called)
            if status<400 and not called.get("error") and not is_error and text:return done(True,text,cached=True,steps=steps)
        except (requests.RequestException,ValueError):
            pass
    raw=mcp_read_document(config_obj,kb_id,document_uri,tool,max_chars,FULL_DOCUMENT_TIMEOUT)
    if raw.get("schema") is not None and raw.get("raw_schema") is not None:_MCP_SCHEMAS[key]=raw["raw_schema"]
    return done(bool(raw.get("ok")),raw.get("text") or "",raw.get("error_code"),False,raw.get("steps"))
