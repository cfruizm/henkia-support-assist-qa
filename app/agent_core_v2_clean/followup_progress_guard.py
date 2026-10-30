from __future__ import annotations
import re,unicodedata

def _norm(v):
 return " ".join(unicodedata.normalize("NFKD",str(v or "")).encode("ascii","ignore").decode().casefold().split())
def _tokens(v):
 stop={"de","del","la","el","los","las","un","una","en","que","y","o","para","por","con","si","se","al","lo","su","es","esta","este","como"}
 return {x for x in re.findall(r"[a-z0-9_-]+",_norm(v)) if len(x)>2 and x not in stop}
def _overlap(a,b):
 x,y=_tokens(a),_tokens(b)
 return (len(x&y)/max(1,min(len(x),len(y)))) if x and y else 0.0
def _prior_actions(store):
 memory=(store or {}).get("memory")
 case=getattr(memory,"support_case",None)
 out=[]
 for item in list(getattr(case,"attempts",[]) or []):
  action=str(getattr(item,"action",None) or (item.get("action") if isinstance(item,dict) else "") or "")
  if action:out.append(action)
 ctx=(store or {}).get("answer_context") or {}
 for item in ctx.get("delivered_guidance") or []:
  if str(item.get("status") or "") == "delivered":out.append(str(item.get("action") or item.get("excerpt") or ""))
 return [x for x in out if x]
def enforce_progress(payload,store):
 prior=_prior_actions(store)
 if not prior or not isinstance(payload,dict):return payload,{"checked":False,"removed":0}
 text=str(payload.get("text") or "")
 blocks=re.split(r"(?m)(?=^\s*(?:\d+[.)]|[-*])\s+)",text)
 kept=[];removed=[]
 for block in blocks:
  candidate=block.strip()
  if candidate and re.match(r"^(?:\d+[.)]|[-*])\s+",candidate) and any(_overlap(candidate,p)>=0.58 for p in prior):
   removed.append(candidate);continue
  kept.append(block)
 new_text="".join(kept).strip()
 if removed:
  new_text=re.sub(r"(?im)^\s*#{1,4}\s*(validaciones adicionales|pasos|comprobaciones)\s*$\n?","",new_text).strip()
  if not new_text or len(_tokens(new_text))<8:
   new_text="Las validaciones ya realizadas permanecen registradas y no es necesario repetirlas. El siguiente avance útil es recopilar los registros del componente afectado y adjuntarlos al escalamiento para revisar el recorrido del trabajo."
  payload=dict(payload);payload["text"]=new_text;payload["progression_guard"]={"removed_repeated_blocks":len(removed)}
 return payload,{"checked":True,"removed":len(removed)}
