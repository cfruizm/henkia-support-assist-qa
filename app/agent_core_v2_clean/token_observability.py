from __future__ import annotations
import json

VERSION="token_observability_v1_measurement_only"

def _bytes(value):
    try:return len(json.dumps(value,ensure_ascii=False,separators=(",",":"),default=str).encode("utf-8"))
    except Exception:return 0

def _chars(value):
    try:return len(str(value or ""))
    except Exception:return 0

def _evidence_stats(retrieval):
    rows=list((retrieval or {}).get("evidence") or [])
    texts=[str((x or {}).get("text") or "") for x in rows]
    identities=[]
    for row in rows:
        identity=str((row or {}).get("url") or (row or {}).get("source") or (row or {}).get("title") or "").strip()
        if identity and identity not in identities:identities.append(identity)
    return {"items":len(rows),"documents":len(identities),"text_chars":sum(map(len,texts)),"serialized_bytes":_bytes(rows)}

def turn_diagnostic(result,store):
    result=result or {};store=store or {};u=result.get("understanding") or {};a=result.get("answer") or {};r=result.get("retrieval") or {};tm=result.get("turn_metrics") or {};ctx=result.get("answer_context") or store.get("answer_context") or {}
    route={"intent":u.get("intent"),"user_act":u.get("user_act"),"topic_relation":u.get("topic_relation"),"decision":(result.get("decision") or {}).get("action"),"answer_mode":a.get("mode"),"retrieval_enabled":bool(r.get("enabled")),"finish_reason":a.get("finish_reason")}
    cache={"documented_answer_hit":bool((result.get("documented_answer") or {}).get("cache_hit")),"retrieval_hit":bool((r.get("cache") or {}).get("hit")),"exact_turn_hit":bool((result.get("execution") or {}).get("cache_hit"))}
    sizes={"input_chars":_chars(result.get("input")),"answer_chars":_chars(a.get("text")),"understanding_bytes":_bytes(u),"state_before_bytes":_bytes(result.get("state_before")),"state_after_bytes":_bytes(result.get("state_after")),"answer_context_bytes":_bytes(ctx),"retrieval_bytes":_bytes(r),"documented_diagnostic_bytes":_bytes(result.get("documented_answer")),"provider_trace_bytes":_bytes(result.get("provider_trace"))}
    return {"version":VERSION,"route":route,"tokens":{"calls":int(tm.get("calls") or 0),"prompt":int(tm.get("prompt_tokens") or 0),"completion":int(tm.get("completion_tokens") or 0),"total":int(tm.get("total_tokens") or 0)},"evidence":_evidence_stats(r),"sizes":sizes,"cache":cache,"semantic_memory":{"pending_checks":len(ctx.get("delivered_guidance") or []),"hypotheses":len(ctx.get("documented_hypotheses") or []),"cited_evidence":len(ctx.get("cited_evidence") or [])},"measurement_only":True}

def session_diagnostic(turns):
    rows=[]
    for turn in turns or []:
        row=((turn or {}).get("turn_metrics") or {}).get("token_observability")
        if row:rows.append(row)
    totals={"turns_measured":len(rows),"calls":sum(x["tokens"]["calls"] for x in rows),"prompt_tokens":sum(x["tokens"]["prompt"] for x in rows),"completion_tokens":sum(x["tokens"]["completion"] for x in rows),"total_tokens":sum(x["tokens"]["total"] for x in rows),"evidence_chars":sum(x["evidence"]["text_chars"] for x in rows),"retrieval_bytes":sum(x["sizes"]["retrieval_bytes"] for x in rows),"answer_context_bytes":sum(x["sizes"]["answer_context_bytes"] for x in rows)}
    by_route={}
    for row in rows:
        key=str(row["route"].get("answer_mode") or row["route"].get("decision") or "unknown")
        bucket=by_route.setdefault(key,{"turns":0,"calls":0,"prompt_tokens":0,"completion_tokens":0,"total_tokens":0})
        bucket["turns"]+=1;bucket["calls"]+=row["tokens"]["calls"];bucket["prompt_tokens"]+=row["tokens"]["prompt"];bucket["completion_tokens"]+=row["tokens"]["completion"];bucket["total_tokens"]+=row["tokens"]["total"]
    return {"version":VERSION,"totals":totals,"by_route":by_route,"measurement_only":True}
