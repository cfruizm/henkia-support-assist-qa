from __future__ import annotations
import hashlib,re,unicodedata
from .memory import normalize_text

def _tokens(text):
    t=normalize_text(text)
    stop={"como","para","que","con","del","las","los","una","uno","por","the","and","from","this","that"}
    return {x for x in re.findall(r"[a-z0-9_]{3,}",t) if x not in stop}

def _identity(item):return str(item.get("url") or item.get("source") or (item.get("metadata") or {}).get("source") or item.get("title") or "").strip()

def _metadata_terms(item):
    m=item.get("metadata") or {}
    return " ".join(str(m.get(k) or "") for k in ("product","vendor","component","title","collection_name","folder_origin"))

def select_evidence(message,evidence,understanding,limit=4):
    qtokens=_tokens(" ".join([message,str(understanding.current_goal or ""),str(understanding.intent or "")]))
    ranked=[];seen=set()
    for raw in evidence or []:
        item=dict(raw or {});item["text"]=str(item.get("text") or "")[:5000]
        ident=_identity(item);content=" ".join([str(item.get("title") or ""),_metadata_terms(item),item["text"]])
        if ident and ident in seen:continue
        if ident:seen.add(ident)
        overlap=len(qtokens&_tokens(content))/max(1,len(qtokens))
        score=float(item.get("score") or 0.0) if str(item.get("score") or "").replace(".","",1).isdigit() else 0.0
        rank=overlap*3.0+score
        item["selection_score"]=round(rank,4);ranked.append((rank,item))
    ranked.sort(key=lambda x:x[0],reverse=True)
    out=[x[1] for x in ranked[:limit]]
    for i,x in enumerate(out,1):x["id"]=f"R{i}"
    return out

def evidence_summary(message,understanding,evidence):
    selected=select_evidence(message,evidence,understanding)
    query_tokens=_tokens(message+" "+str(understanding.current_goal or ""))
    coverage=max([len(query_tokens&_tokens((x.get("title") or "")+" "+(x.get("text") or "")))/max(1,len(query_tokens)) for x in selected] or [0.0])
    return {"selected":selected,"coverage":round(coverage,3),"sufficient":bool(selected and coverage>=0.12)}

def normalize_action(value):return normalize_text(value).strip(" .,:;!?¿¡")

def repeated_failed_action(answer,failed):
    text=normalize_text(answer)
    for action in failed or []:
        n=normalize_action(action)
        if n and n in text:return action
    return None
