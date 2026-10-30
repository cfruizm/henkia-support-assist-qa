from collections import OrderedDict
import re

def _c(v):return " ".join(str(v or "").split()).strip()
def _label(x):
 for raw in str(x.get("text") or "").splitlines():
  line=_c(raw).strip("-:.;")
  if 3<=len(line)<=90 and line.isupper() and line not in {"OBJETIVO","ALCANCE","CONTENIDO","RESPONSABLE"}:return line.title()
 return _c(x.get("title")) or "Procedimiento documentado"
def build_structured_fallback(evidence,scope=None):
 groups=OrderedDict();vendors=[];products=[]
 for x in evidence or []:
  if not _c(x.get("text")):continue
  groups.setdefault(_label(x),[]).append(x);m=x.get("metadata") or {}
  for k,a in (("vendor",vendors),("product",products)):
   v=_c(m.get(k))
   if v and v.casefold() not in {"unknown","general","arus_internal","sanitized_support_assets"} and v not in a:a.append(v)
 explicit=any((scope or {}).get(k) for k in ("manufacturer","product","model"));specific=bool(vendors or products)
 lines=["**Procedimiento documentado**"]
 if specific and not explicit:lines += [f"\n> **Alcance limitado:** evidencia para {', '.join(vendors+products)}. Confirma fabricante y modelo antes de ejecutar una ruta específica."]
 used=[]
 for i,(label,items) in enumerate(groups.items(),1):
  lines.append(f"\n**Método {i}: {label}**")
  for n,x in enumerate(items,1):
   cid=_c(x.get("id"));lines.append(f"{n}. {_c(x.get('text'))}"+(f" [{cid}]" if cid else ""));used += [cid] if cid else []
 return {"text":"\n".join(lines),"used_evidence_ids":list(dict.fromkeys(used)),"branch_count":len(groups),"evidence_scope":{"manufacturers":vendors,"products":products,"specific":specific},"requires_scope_detail":specific and not explicit}
def apply_structured_procedural_recovery(result):
 a=result.get("answer") or {}
 if a.get("mode")!="procedural_documented_fallback":result["procedural_recovery"]={"applied":False};return result
 r=result.get("retrieval") or {};p=result.get("canonical_response_plan") or r.get("response_plan") or {};built=build_structured_fallback(r.get("generation_evidence") or r.get("evidence") or [],(p.get("request") or {}).get("scope") or {})
 a.update(text=built["text"],mode="procedural_documented_structured_fallback",finish_reason="deterministic_structured_fallback");result["procedural_recovery"]={"applied":True,**{k:v for k,v in built.items() if k!="text"}};return result
