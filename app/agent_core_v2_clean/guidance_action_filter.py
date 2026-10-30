from __future__ import annotations


def _clean(value):
    return " ".join(str(value or "").split()).strip()


def sanitize_answer_context(context):
    out=dict(context or {})
    rows=[];seen=set()
    for item in out.get("delivered_guidance") or []:
        if not isinstance(item,dict):continue
        action=_clean(item.get("action"));key=_clean(item.get("check_key")).casefold()
        identity=key or action.casefold()
        if not action or identity in seen:continue
        seen.add(identity);row=dict(item);row["action"]=action
        if key:row["check_key"]=key
        row["guidance_kind"]="pending_check";rows.append(row)
    hypotheses=[];seen=set()
    for item in out.get("documented_hypotheses") or []:
        if not isinstance(item,dict):continue
        summary=_clean(item.get("summary"));key=_clean(item.get("hypothesis_key")).casefold()
        conditions=[_clean(x) for x in item.get("required_conditions") or [] if _clean(x)]
        identity=key or summary.casefold()
        if not summary or not conditions or identity in seen:continue
        seen.add(identity);hypotheses.append({"hypothesis_key":key or identity,"summary":summary,"required_conditions":conditions[:4],"status":"unconfirmed","origin":"assistant_structured_memory"})
    out["delivered_guidance"]=rows
    out["documented_hypotheses"]=hypotheses
    out["guidance_filter"]={"policy":"keyed_semantic_memory_v4","retained":len(rows),"hypotheses":len(hypotheses)}
    return out
