from __future__ import annotations
from copy import deepcopy
import hashlib, re, unicodedata
from typing import Any

def norm(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()

def normalized(value: Any) -> str:
    return unicodedata.normalize("NFKD", norm(value)).encode("ascii", "ignore").decode().casefold()

def tokens(value: Any) -> set[str]:
    stop={"que","como","para","con","del","las","los","una","uno","esta","este","ese","esa","por","and","the","with","from","this","that"}
    return {x for x in re.findall(r"[a-z0-9]+",normalized(value)) if len(x)>2 and x not in stop}

def fact_id(value: Any) -> str:
    return "confirmed."+hashlib.sha256(normalized(value).encode()).hexdigest()[:16]

def build_case_context(memory: Any) -> dict[str, Any]:
    case=getattr(memory,"support_case",None); records=getattr(memory,"fact_records",{}) or {}
    observations=[]
    for x in getattr(case,"observations",[]) or []:
        value=norm(x)
        if value and normalized(value) not in {normalized(y) for y in observations}: observations.append(value)
    attempts=[]
    for item in getattr(case,"attempts",[]) or []:
        action=norm((item or {}).get("action")); result=norm((item or {}).get("result"))
        if action: attempts.append({"action":action,"result":result or None})
    facts=[deepcopy(x) for x in records.values() if isinstance(x,dict) and x.get("status")=="confirmed"]
    return {"observations":observations,"attempts":attempts,"affected_scope":norm(getattr(case,"affected_scope",None)) or None,"confirmed_facts":facts,"last_assistant_request":norm(getattr(memory,"last_assistant_question",None)) or None}

def prompt_constraints(memory: Any) -> str:
    c=build_case_context(memory); lines=["CONFIRMED CASE CONTEXT:"]
    for x in c["observations"]: lines.append(f"- Observation: {x}")
    for x in c["attempts"]:
        lines.append(f"- Already performed: {x['action']}")
        if x.get("result"): lines.append(f"  Result: {x['result']}")
    for x in c["confirmed_facts"]: lines.append(f"- Confirmed fact: {x.get('value')}")
    lines += ["MANDATORY RULES:","- Never contradict a confirmed fact.","- Never ask again for a fact already confirmed.","- Never repeat an action already performed unless the variation and diagnostic purpose are explicit.","- Use the affected scope to prefer shared or local hypotheses.","- Ask at most one new discriminating question or provide one reversible next action."]
    return "\n".join(lines)

def inject_context(target: dict, memory: Any) -> dict:
    out=deepcopy(target or {});out["_confirmed_case_context"]=build_case_context(memory);out["_confirmed_case_constraints"]=prompt_constraints(memory);return out
