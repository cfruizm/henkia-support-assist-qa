from __future__ import annotations
import re
import unicodedata
from copy import deepcopy
from .document_resolver import retrieve_all_chunks

_GENERIC={
 "el","la","en","a","como","para","que","cual","cuales","donde","cuando","porque","por","con","sin","del","las","los","una","uno","unos","unas","este","esta","esto","ese","esa","eso","mismo","misma","documento","informacion","incluye","explicar","revisar","favor","dime","sirve","the","and","for","from","with","this","that","what","which","where","same","document","information","explain","review"
}

def _norm(value):
 return " ".join(re.findall(r"[a-z0-9]+",unicodedata.normalize("NFKD",str(value or "")).encode("ascii","ignore").decode().casefold()))

def _ledger(answer_context):
 context=answer_context or {};items=context.get("active_document_evidence_ledger") or context.get("cited_evidence") or []
 identities={str(x).strip() for x in context.get("source_identities") or [] if str(x).strip()}
 out=[]
 for item in items:
  identity=str(item.get("url") or item.get("source") or (item.get("metadata") or {}).get("canonical_url") or "")
  if identities and identity not in identities:continue
  text=_norm(" ".join((str(item.get("title") or ""),str(item.get("text") or ""))))
  if text:out.append((item,text,identity))
 return out,identities

def _message_candidates(message,understanding):
 normalized=_norm(message);tokens=normalized.split();rows=[];seen=set()
 explicit=str((understanding or {}).get("canonical_subject") or "").strip()
 quoted=re.findall(r"[\"'“”‘’]([^\"'“”‘’]{2,160})[\"'“”‘’]",str(message or ""))
 seeds=[explicit]+quoted
 for seed in seeds:
  value=_norm(seed)
  if value and value not in seen:seen.add(value);rows.append((100+len(value.split()),value,seed))
 for size in range(min(7,len(tokens)),1,-1):
  for index in range(0,len(tokens)-size+1):
   phrase=tokens[index:index+size];meaningful=[x for x in phrase if x not in _GENERIC]
   if len(meaningful)<2 and not (len(meaningful)==1 and any(ch.isdigit() for ch in meaningful[0])):continue
   while phrase and phrase[0] in _GENERIC:phrase=phrase[1:]
   while phrase and phrase[-1] in _GENERIC:phrase=phrase[:-1]
   value=" ".join(phrase)
   if not value or value in seen:continue
   seen.add(value);rows.append((10*len(meaningful)+size,value,value))
 rows.sort(reverse=True,key=lambda x:(x[0],len(x[1])))
 return rows

def reconcile_document_object(message,understanding,memory,answer_context):
 """Preserve the active document only when the requested object is evidenced in it."""
 u=deepcopy(understanding or {});ledger,identities=_ledger(answer_context)
 diagnostic={"applied":False,"reason":"no_document_object_match","active_source_count":len(identities),"ledger_count":len(ledger),"exhaustive_membership_scan":{"attempted":False,"ok":False,"raw_count":0,"errors":[]}}
 active_subject=str(getattr(memory,"active_subject",None) or "").strip()
 explicit_subject=str(u.get("canonical_subject") or "").strip()
 explicit_origin=str(u.get("subject_origin") or "").strip().casefold()
 reference_relation=str(u.get("reference_relation") or "none").strip().casefold()
 case_subject=str(getattr(getattr(memory,"support_case",None),"subject",None) or "").strip()
 # Q3.2: once a troubleshooting case has been restored, document-object
 # continuity may focus a section but cannot replace the case subject.
 if reference_relation=="current_subject" and case_subject and explicit_subject and explicit_subject.casefold()==case_subject.casefold():
  active_subject=case_subject
 # The current message has authority over prior-document continuity. A document
 # can mention many products or components; membership alone must not convert an
 # explicit subject switch into an elaboration of the previous document.
 if explicit_origin=="current_message" and explicit_subject and active_subject and explicit_subject.casefold()!=active_subject.casefold():
  diagnostic.update({"reason":"explicit_current_subject_switch_bypasses_active_document","active_subject":active_subject,"explicit_subject":explicit_subject,"subject_switch_authority":True})
  return u,diagnostic
 if not identities:return u,diagnostic
 # The conversational ledger is intentionally compact. For membership only,
 # inspect the exact active source when the compact ledger may omit later text.
 expanded=list(ledger)
 for source in sorted(identities):
  rows,scan=retrieve_all_chunks(source);diagnostic["exhaustive_membership_scan"]={"attempted":True,"ok":bool(scan.get("ok")),"raw_count":int(scan.get("raw_count",0) or 0),"errors":list(scan.get("errors") or []),"strategy":scan.get("strategy")}
  for item in rows:
   text=_norm(" ".join((str(item.get("title") or ""),str(item.get("text") or ""))))
   if text:expanded.append((item,text,source))
 ledger=expanded;diagnostic["expanded_ledger_count"]=len(ledger)
 if not ledger:return u,diagnostic
 active_subject=str(getattr(memory,"active_subject",None) or ((getattr(memory,"pending_goal",None) and memory.pending_goal.known_details.get("subject")) or "")).strip()
 active_normalized=_norm(active_subject)
 for score,candidate,display in _message_candidates(message,u):
  # The active subject proves document continuity but is not itself the newly
  # requested internal object. Prefer a distinct evidenced phrase from the turn.
  if active_normalized and candidate==active_normalized:continue
  matched=[item for item,text,_ in ledger if re.search(r"(?:^|\s)"+re.escape(candidate)+r"(?:$|\s)",text)]
  if not matched:continue
  original_subject=str(u.get("canonical_subject") or "").strip() or None
  updates=dict(u.get("goal_updates") or {});updates["document_object"]=display.strip() or candidate
  if active_subject:updates["subject"]=active_subject
  u.update({"topic_relation":"same_topic","user_act":"request_elaboration","reference_relation":"current_subject","goal_updates":updates})
  if active_subject:u["canonical_subject"]=active_subject;u["subject_origin"]="conversation_memory"
  diagnostic={"applied":True,"reason":"requested_object_found_in_active_document","object":display.strip() or candidate,"normalized_object":candidate,"match_count":len(matched),"matched_pages":sorted({str(x.get("page") or "") for x in matched if x.get("page") not in (None,"")}),"active_sources":sorted(identities),"original_subject":original_subject,"effective_subject":u.get("canonical_subject"),"score":score}
  return u,diagnostic
 return u,diagnostic
