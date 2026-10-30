from __future__ import annotations
from dataclasses import dataclass,asdict
from typing import Callable,Any
import hashlib,json,re,unicodedata
from .document_resolver import resolve as resolve_document, retrieve as retrieve_resolved_document, retrieve_all_chunks as retrieve_all_document_chunks
@dataclass
class RetrievalQuery:
 text:str;fields:dict[str,Any];fingerprint:str
 def to_dict(self):return asdict(self)
# Domain-neutral language bridges used only for retrieval. They are activated
# by concepts in the current turn and contain no products or document titles.
_CROSS_LANGUAGE_CONCEPTS={
 "disappearance":{"triggers":{"desaparece","desaparecen","desaparecido","faltante","faltantes","missing"},"expansion":("missing","disappearing","disappear")},
 "release":{"triggers":{"liberacion","liberar","libera","release","released"},"expansion":("release","held","hold")},
 "queue":{"triggers":{"cola","colas","queue","queues"},"expansion":("queue","virtual queue")},
 "printing":{"triggers":{"impresion","imprimir","trabajo","trabajos","print","printing","job","jobs"},"expansion":("print job","printing")},
}
def _norm_tokens(value):
 value=unicodedata.normalize("NFKD",str(value or "")).encode("ascii","ignore").decode().casefold()
 return set(re.findall(r"[a-z0-9_-]{3,}",value))
def _cross_language_query(message,subject,intent):
 if str(intent or "").casefold()!="troubleshooting":return None,{"applied":False,"reason":"intent_not_troubleshooting"}
 tokens=_norm_tokens(message);terms=[];concepts=[]
 for name,spec in _CROSS_LANGUAGE_CONCEPTS.items():
  if tokens.intersection(spec["triggers"]):concepts.append(name);terms.extend(spec["expansion"])
 if not concepts:return None,{"applied":False,"reason":"no_cross_language_concept"}
 parts=[]
 for value in (str(subject or "").strip(),*terms):
  if value and value.casefold() not in {x.casefold() for x in parts}:parts.append(value)
 return ". ".join(parts),{"applied":True,"concepts":concepts,"added_terms":terms,"source":"current_turn_only"}
def _attach_ranking_query(rows,text,mode):
 out=[]
 for item in rows or []:
  row=dict(item);queries=list(row.get("ranking_queries") or [])
  candidate={"text":str(text or "").strip(),"mode":str(mode or "").strip(),"source":"current_turn_only"}
  if candidate["text"] and candidate not in queries:queries.append(candidate)
  row["ranking_queries"]=queries[-3:];out.append(row)
 return out
def _text(value):
 if value is None:return ""
 if isinstance(value,str):return value
 if isinstance(value,(int,float,bool)):return str(value)
 if isinstance(value,list):return " ".join(_text(x) for x in value if _text(x))
 if isinstance(value,dict):
  for key in ("summary","subject","operation","product","value","text"):
   if value.get(key) is not None:return _text(value.get(key))
  return ""
 return str(value)
class RetrievalQueryBuilder:
 def build(self,message,memory,understanding,effective_topic_relation=None):
  details={str(k):_text(v) for k,v in memory.pending_goal.known_details.items() if _text(v).strip()}
  user_act=str(getattr(understanding,"user_act","") or "");model_topic_relation=str(getattr(understanding,"topic_relation","") or "")
  topic_relation=str(effective_topic_relation or model_topic_relation);new_topic=topic_relation=="new_topic"
  contextual_operation=str(message or "").strip() if not new_topic and (user_act in {"follow_up","answer_to_question","reported_failure","attempt_result"} or model_topic_relation=="same_topic") else ""
  current_updates={str(k):_text(v) for k,v in dict(getattr(understanding,"goal_updates",{}) or {}).items() if _text(v).strip()}
  if new_topic:details=current_updates
  else:
   # Current-turn structured facts refine, but do not erase, accumulated state.
   # This keeps follow-up contracts complete while preserving new-topic isolation.
   details.update(current_updates)
  fields={"goal":understanding.current_goal if new_topic else (memory.pending_goal.summary or understanding.current_goal),"intent":understanding.intent if new_topic else (memory.pending_goal.intent or understanding.intent),"subject":_text(getattr(understanding,"canonical_subject",None)),"details":details,"symptoms":[] if new_topic else list(memory.support_case.symptoms),"observations":[] if new_topic else list(memory.support_case.observations[-3:]),"affected_scope":None if new_topic else memory.support_case.affected_scope,"current_message":message,"contextual_operation":contextual_operation or None,"user_act":user_act,"topic_relation":topic_relation,"model_topic_relation":model_topic_relation,"query_isolation":"new_topic" if new_topic else "contextual"}
  parts=[str(message or "").strip(),_text(fields["goal"]).strip()]
  if contextual_operation and contextual_operation.casefold()!=_text(fields["goal"]).strip().casefold():parts.append(contextual_operation)
  parts += [f"{k}: {v}" for k,v in details.items()]+fields["symptoms"]+fields["observations"]
  if fields["affected_scope"]:parts.append(f"alcance: {fields['affected_scope']}")
  text=". ".join(dict.fromkeys(x for x in parts if x))[:1200];fingerprint=hashlib.sha256(json.dumps(fields,sort_keys=True,ensure_ascii=False).encode()).hexdigest()[:20]
  return RetrievalQuery(text,fields,fingerprint)
 def current_only(self,message,understanding):
  fields={"goal":understanding.current_goal,"intent":understanding.intent,"details":dict(understanding.goal_updates or {}),"symptoms":[],"observations":[],"affected_scope":None,"current_message":message,"context_mode":"current_turn_only","grounded_only":True}
  text=". ".join(dict.fromkeys(x for x in [str(understanding.current_goal or ""),str(message or "")]+[str(v) for v in fields["details"].values()] if x))[:900]
  return RetrievalQuery(text,fields,hashlib.sha256(json.dumps(fields,sort_keys=True,ensure_ascii=False).encode()).hexdigest()[:20])
def _tokens(text):
 text=unicodedata.normalize("NFKD",str(text or "")).encode("ascii","ignore").decode().casefold();stop={"como","para","que","con","del","las","los","una","uno","por","the","and","from","this","realizar","explicar"}
 return {x for x in re.findall(r"[a-z0-9_]{3,}",text) if x not in stop}
def _quality(message,evidence):
 wanted=_tokens(message)
 if not wanted:return 0.0
 return round(max([len(wanted&_tokens((x.get("title") or "")+" "+(x.get("text") or "")))/len(wanted) for x in evidence] or [0.0]),4)
def _request_coverage(message,evidence):
 """Measure whether the current evidence collectively covers the request.

 This is intentionally domain agnostic: only request terms and retrieved content
 participate in the decision.
 """
 wanted=_tokens(message)
 if not wanted:return {"wanted_terms":[],"covered_terms":[],"missing_terms":[],"coverage":1.0,"complete":True}
 available=set()
 for item in evidence or []:available|=_tokens((item.get("title") or "")+" "+(item.get("text") or ""))
 covered=wanted&available;missing=wanted-covered;coverage=round(len(covered)/max(1,len(wanted)),4)
 return {"wanted_terms":sorted(wanted),"covered_terms":sorted(covered),"missing_terms":sorted(missing),"coverage":coverage,"complete":not missing}
def _same_document_rows(items,source):
 rows=[x for x in items or [] if _identity(x)==source];rows.sort(key=_page);return rows
def _focused_query(built):
 f=dict(built.fields or {});message=str(f.get("current_message") or "").strip();details={str(k):_text(v) for k,v in dict(f.get("details") or {}).items() if _text(v).strip()};subject=str(f.get("subject") or details.get("subject") or "").strip()
 if subject:details["subject"]=subject
 text=". ".join(dict.fromkeys(x for x in [message,subject]+[str(v) for v in details.values()] if x))[:700]
 ff={"goal":f.get("goal"),"intent":f.get("intent"),"subject":subject,"details":details,"symptoms":[],"observations":[],"affected_scope":None,"current_message":message,"context_mode":"operation_focused","grounded_only":True,"topic_relation":f.get("topic_relation"),"model_topic_relation":f.get("model_topic_relation"),"query_isolation":f.get("query_isolation")}
 return RetrievalQuery(text,ff,hashlib.sha256(json.dumps(ff,sort_keys=True,ensure_ascii=False).encode()).hexdigest()[:20])
def _merge_evidence(*groups):
 merged=[];positions={}
 for group in groups:
  for item in group or []:
   key=(_identity(item),_page(item),hashlib.sha256(str(item.get("text") or "").casefold().encode()).hexdigest()[:12])
   if key not in positions:positions[key]=len(merged);merged.append(item);continue
   # Preserve query provenance when the same chunk is retrieved by more than one
   # current-turn query. Other evidence fields keep their first-seen authority.
   existing=merged[positions[key]];queries=list(existing.get("ranking_queries") or [])
   for candidate in item.get("ranking_queries") or []:
    if candidate not in queries:queries.append(candidate)
   if queries:existing["ranking_queries"]=queries[-3:]
 return merged
def _candidate_documents(evidence,maximum=3):
 groups={}
 for position,item in enumerate(evidence or []):
  identity=_identity(item)
  if not identity:continue
  group=groups.setdefault(identity,{"identity":identity,"title":item.get("title"),"items":[],"first_position":position,"best_retrieval_score":None})
  group["items"].append(item)
  try:score=float(item.get("score"))
  except (TypeError,ValueError):score=None
  if score is not None and (group["best_retrieval_score"] is None or score>group["best_retrieval_score"]):group["best_retrieval_score"]=score
 ranked=list(groups.values())
 ranked.sort(key=lambda row:(row["best_retrieval_score"] is not None,row["best_retrieval_score"] if row["best_retrieval_score"] is not None else 0,-row["first_position"]),reverse=True)
 return ranked[:max(1,int(maximum))]

def _procedural_document_score(query,rows):
 # Rank complete single-document expansions without product dictionaries.
 wanted=_tokens(query);available=set();title=set();pages=set();action_rows=0
 action_stems=("select","seleccion","choose","esco","click","clic","press","puls","open","abr","enter","ingres","type","escrib","load","carg","send","env","save","guard","next","luego","after","despues")
 for item in rows or []:
  title|=_tokens(item.get("title"));text=str(item.get("text") or "");available|=_tokens((item.get("title") or "")+" "+text)
  page=str(item.get("page") or "").strip()
  if page:pages.add(page)
  folded=unicodedata.normalize("NFKD",text).encode("ascii","ignore").decode().casefold()
  if sum(1 for stem in action_stems if stem in folded)>=2:action_rows+=1
 covered=wanted&available;title_hits=wanted&title
 coverage=len(covered)/max(1,len(wanted));title_coverage=len(title_hits)/max(1,len(wanted));breadth=min(len(pages),4)/4;structure=min(action_rows,4)/4
 score=round((coverage*.45)+(title_coverage*.25)+(breadth*.15)+(structure*.15),4)
 return score,{"coverage":round(coverage,4),"title_coverage":round(title_coverage,4),"unique_pages":len(pages),"action_chunk_count":action_rows,"covered_terms":sorted(covered),"pages":sorted(pages,key=lambda x:(not x.isdigit(),int(x) if x.isdigit() else x))}

def _expand_candidate_documents(query,evidence,maximum=3,limit=8,select_single_procedural=False):
 candidates=_candidate_documents(evidence,maximum);expanded=[];diagnostic=[];expanded_groups=[]
 for candidate in candidates:
  rows,trace=_expand_procedure(query,candidate["items"],limit);score,signals=_procedural_document_score(query,rows)
  expanded_groups.append((score,candidate["first_position"],candidate,rows,signals));expanded=_merge_evidence(expanded,rows)
  diagnostic.append({"identity":candidate["identity"],"title":candidate["title"],"first_position":candidate["first_position"],"best_retrieval_score":candidate["best_retrieval_score"],"seed_count":len(candidate["items"]),"expanded_count":len(rows),"expansion_ok":bool(trace.get("ok")),"expansion_attempted":bool(trace.get("attempted")),"procedural_score":score,"procedural_signals":signals,"errors":trace.get("errors") or []})
 base={"enabled":True,"policy":"multi_document_candidate_expansion_v2_single_procedural_document" if select_single_procedural else "multi_document_candidate_expansion_v1","candidate_limit":maximum,"candidate_count":len(candidates),"candidates":diagnostic,"expanded_count":len(expanded),"llm_called":False}
 if not select_single_procedural or not expanded_groups:return expanded,base
 expanded_groups.sort(key=lambda x:(x[0],-x[1]),reverse=True);score,_,chosen,rows,signals=expanded_groups[0];selected=_same_document_rows(rows,chosen["identity"])[:limit]
 return selected,{**base,"chosen_identity":chosen["identity"],"chosen_title":chosen["title"],"chosen_score":score,"same_document_only":True,"ordered":True,"pages":signals["pages"],"count":len(selected),"ok":bool(selected),"selection_reason":"best_complete_procedural_document"}

def _best_document(query,evidence):
 groups={}
 for item in evidence or []:groups.setdefault(_identity(item),[]).append(item)
 ranked=[]
 for identity,items in groups.items():
  title=" ".join(dict.fromkeys(str(x.get("title") or "") for x in items))
  title_quality=_quality(query,[{"title":title,"text":""}]);content_quality=_quality(query,items)
  score=round((title_quality*.65)+(content_quality*.35),4)
  ranked.append({"identity":identity,"title":items[0].get("title"),"score":score,"title_quality":title_quality,"content_quality":content_quality,"items":items})
 ranked.sort(key=lambda x:x["score"],reverse=True)
 return (ranked[0] if ranked else None),[{k:v for k,v in x.items() if k!="items"} for x in ranked]

def _page(e):
 m=e.get("metadata") or {};raw=m.get("page_label") or m.get("page") or e.get("page") or 0
 try:return int(str(raw).strip())
 except:return 10**9
def _identity(e):return str(e.get("url") or e.get("source") or (e.get("metadata") or {}).get("source") or e.get("title") or "")
def _normalize_items(items):
 out=[]
 for i,x in enumerate(items or [],1):
  m=dict(x.get("metadata") or {});out.append({"id":f"R{i}","title":str(x.get("title") or m.get("title") or "Fuente sin título"),"source":str(x.get("source") or m.get("source") or ""),"url":str(x.get("url") or m.get("source_url") or m.get("canonical_url") or ""),"score":x.get("score"),"page":str(m.get("page_label") or m.get("page") or ""),"text":str(x.get("text") or "")[:1800],"metadata":m})
 return out
def _expand_procedure(query,evidence,k=8):
 if not evidence:return evidence,{"enabled":True,"attempted":False,"reason":"no_seed_evidence","llm_called":False}
 seed=evidence[0];source=_identity(seed)
 if not source:return evidence,{"enabled":True,"attempted":False,"reason":"seed_without_identity","llm_called":False}
 try:
  from app.integration.document_expansion_adapter import retrieve_same_document
  raw=retrieve_same_document(query,source,k)
 except Exception as exc:return evidence,{"enabled":True,"attempted":True,"ok":False,"llm_called":False,"errors":[f"{type(exc).__name__}: {exc}"]}
 expanded=_normalize_items(raw.get("evidence") or [])
 merged=[];seen=set()
 for x in evidence+expanded:
  key=(_identity(x),_page(x),hashlib.sha256(str(x.get("text") or "").casefold().encode()).hexdigest()[:12])
  if key not in seen:seen.add(key);merged.append(x)
 same=_same_document_rows(merged,source)
 selected=same[:max(8,int(k))] if same else evidence
 for i,x in enumerate(selected,1):x["id"]=f"R{i}"
 pages=[x.get("page") for x in selected if x.get("page")]
 return selected,{"enabled":True,"attempted":True,"ok":bool(raw.get("ok")),"llm_called":False,"adapter":raw.get("adapter"),"seed_document":source,"seed_page":seed.get("page"),"pages":pages,"count":len(selected),"ordered":True,"same_document_only":all(_identity(x)==source for x in selected),"errors":raw.get("errors") or [],"generation_enabled":False}
class ReadOnlyRetrieval:
 def __init__(self,retrieve_fn:Callable|None=None,k=6):self.retrieve_fn=retrieve_fn or self._existing;self.k=max(1,min(10,int(k)))
 def _existing(self,query,k):
  from app.integration.lab_retrieval_adapter import retrieve_from_productive_runtime
  return retrieve_from_productive_runtime(query,k)
 def _normalize(self,raw):return _normalize_items(raw.get("evidence") or [])
 def search(self,built,current_only=None,preferred_sources=None):
  preferred_sources=[str(x) for x in (preferred_sources or []) if str(x).strip()]
  f=built.fields or {};d=f.get("details") or {};resolution=resolve_document(f.get("current_message"),f.get("goal"),d.get("subject"),d.get("product"))
  if resolution.get("enabled"):
   evidence=self._normalize({"evidence":retrieve_resolved_document(resolution,built.text,24)})
   if resolution.get("status")=="exact_match" and evidence:
    evidence,exp=_expand_procedure(built.text,evidence,24);groups={}
    for x in evidence:
     identity=_identity(x);g=groups.setdefault(identity,{"identity":identity,"title":x["title"],"pages":[],"chunks":0});g["chunks"]+=1
     if x["page"] and x["page"] not in g["pages"]:g["pages"].append(x["page"])
    return {"enabled":True,"llm_called":False,"production_changed":False,"query":built.to_dict(),"ok":True,"adapter":"metadata_catalog+same_document","count":len(evidence),"evidence":evidence,"document_groups":list(groups.values()),"errors":[],"diagnostic_only":True,"selection":{"chosen_mode":"deterministic_document_resolver","quality":1.0,"context_contamination_avoided":True,"exact_identifier_match":True},"procedural_expansion":exp,"document_resolution":resolution,"exact_document_match":{"matched":True,"identifiers":resolution.get("identifiers"),"source":resolution["matches"][0]["source"]}}
   return {"enabled":True,"llm_called":False,"production_changed":False,"query":built.to_dict(),"ok":True,"adapter":"metadata_catalog","count":0,"evidence":[],"document_groups":[],"errors":[],"diagnostic_only":True,"selection":{"chosen_mode":"deterministic_document_resolver","quality":0.0,"context_contamination_avoided":True,"exact_identifier_match":False},"procedural_expansion":{"enabled":False,"reason":"document_"+resolution.get("status")},"document_resolution":resolution,"exact_document_match":{"matched":False,"identifiers":resolution.get("identifiers"),"source":None}}
  preferred_attempt=None
  if current_only is not None and preferred_sources:
   try:
    from app.integration.document_expansion_adapter import retrieve_same_document
    source=preferred_sources[0];rawp=retrieve_same_document(current_only.text,source,self.k) or {};ep=self._normalize(rawp);current_message=current_only.fields.get("current_message") or current_only.text;qp=_quality(current_message,ep);coverage_before=_request_coverage(current_message,ep);expanded_for_coverage=False;expansion_raw_count=0
    # The first retrieval is intentionally small. If its combined content does
    # not cover the current request, inspect the same resolved document more
    # deeply, regardless of the words used by the user.
    exhaustive_diagnostic={"attempted":False,"ok":False,"strategy":"metadata_exact_source_scan_v1","raw_count":0,"errors":[]}
    structured_object=bool(str((current_only.fields.get("details") or {}).get("document_object") or "").strip())
    if ep and (structured_object or not coverage_before["complete"]):
     full,exhaustive_diagnostic=retrieve_all_document_chunks(source);full=self._normalize({"evidence":full});expansion_raw_count=len(full)
     same_full=_same_document_rows(_merge_evidence(ep,full),source)
     if same_full and exhaustive_diagnostic.get("ok"):ep=same_full;expanded_for_coverage=True
    coverage_after=_request_coverage(current_message,ep);qp=_quality(current_message,ep)
    object_document_lock=bool(structured_object and expanded_for_coverage and exhaustive_diagnostic.get("ok") and ep and all(_identity(x)==source for x in ep))
    preferred_attempt={"mode":"active_document","query":current_only.to_dict(),"source":source,"quality":qp,"count":len(ep),"coverage_before":coverage_before,"coverage_after":coverage_after,"coverage_expansion":{"attempted":expanded_for_coverage,"same_document_only":True,"trigger":"structured_document_object" if structured_object else "incomplete_request_coverage" if expanded_for_coverage else "none","method":"metadata_exact_source_scan_v1" if expanded_for_coverage else "bounded_semantic_retrieval","raw_count":expansion_raw_count,"exhaustive_scan":exhaustive_diagnostic},"object_document_lock":object_document_lock}
    if ep and (qp>=0.5 or object_document_lock):
     # Reuse the active document only when it still covers the current request.
     # A low-fit active document remains diagnostic but cannot block global recovery.
     if expanded_for_coverage:
      ep=_same_document_rows(ep,source);pages=[x.get("page") for x in ep if x.get("page")]
      exp={"enabled":True,"attempted":True,"ok":True,"llm_called":False,"adapter":rawp.get("adapter"),"seed_document":source,"seed_page":ep[0].get("page") if ep else None,"pages":pages,"count":len(ep),"ordered":True,"same_document_only":all(_identity(x)==source for x in ep),"errors":rawp.get("errors") or [],"generation_enabled":False}
     else:
      limit=18 if str(current_only.fields.get("intent") or "")=="requirements" else 8;ep,exp=_expand_procedure(current_only.text,ep,limit)
     exp["coverage_expansion"]=preferred_attempt["coverage_expansion"];exp["request_coverage_before"]=coverage_before;exp["request_coverage_after"]=coverage_after;groups={}
     for x in ep:
      identity=_identity(x);g=groups.setdefault(identity,{"identity":identity,"title":x["title"],"pages":[],"chunks":0});g["chunks"]+=1
      if x["page"] and x["page"] not in g["pages"]:g["pages"].append(x["page"])
     return {"enabled":True,"llm_called":False,"production_changed":False,"query":current_only.to_dict(),"ok":bool(rawp.get("ok",True)),"adapter":rawp.get("adapter"),"count":len(ep),"evidence":ep,"document_groups":list(groups.values()),"errors":rawp.get("errors") or [],"diagnostic_only":True,"selection":{"chosen_mode":"active_document","quality":qp,"attempts":[preferred_attempt],"context_contamination_avoided":True,"active_document_reused":True,"preferred_document_locked":True,"object_document_lock":object_document_lock},"procedural_expansion":exp}
   except Exception as exc:preferred_attempt={"mode":"active_document","quality":0.0,"count":0,"error":f"{type(exc).__name__}: {exc}"}
  raw1=self.retrieve_fn(built.text,self.k) or {};e1=self._normalize(raw1);q1=_quality(built.fields.get("current_message"),e1);attempts=([preferred_attempt] if preferred_attempt else [])+[{"mode":"contextual","query":built.to_dict(),"quality":q1,"count":len(e1)}]
  # Conceptual questions are wording-sensitive. A second vector lookup using only
  # the canonical subject broadens documentary coverage without an LLM call and
  # without authorizing the results; semantic fit and evidence authority remain
  # responsible for final selection.
  subject=str(built.fields.get("subject") or "").strip();conceptual_expansion={"attempted":False,"subject":subject or None,"count":0,"merged_count":len(e1)}
  if str(built.fields.get("intent") or "").casefold()=="conceptual" and subject and subject.casefold()!=built.text.strip().casefold():
   try:
    raw_subject=self.retrieve_fn(subject,self.k) or {};subject_rows=self._normalize(raw_subject);conceptual_expansion={"attempted":True,"subject":subject,"count":len(subject_rows),"merged_count":0}
    merged=[];seen=set()
    for row in e1+subject_rows:
     key=(_identity(row),str(row.get("page") or ""),str(row.get("text") or "")[:320])
     if key in seen:continue
     seen.add(key);merged.append(row)
    e1=merged;conceptual_expansion["merged_count"]=len(e1);q1=max(q1,_quality(built.fields.get("current_message"),e1));attempts.append({"mode":"conceptual_subject_expansion","subject":subject,"quality":q1,"count":len(subject_rows),"merged_count":len(e1)})
   except Exception as exc:conceptual_expansion={"attempted":True,"subject":subject,"count":0,"merged_count":len(e1),"error":f"{type(exc).__name__}: {exc}"}
  chosen=(built,raw1,e1,"contextual",q1)
  if current_only is not None and q1<0.5:
   raw2=self.retrieve_fn(current_only.text,self.k) or {};e2=self._normalize(raw2);q2=_quality(current_only.fields.get("current_message"),e2);attempts.append({"mode":"current_turn_only","query":current_only.to_dict(),"quality":q2,"count":len(e2)})
   if q2>q1:chosen=(current_only,raw2,e2,"current_turn_only",q2)
  query,raw,evidence,mode,quality=chosen;focused_diagnostic={"enabled":False,"reason":"intent_not_operation_sensitive","candidates":[]}
  if str(query.fields.get("intent") or "") in {"procedural","requirements","troubleshooting"}:
   focused=_focused_query(query);raw3=self.retrieve_fn(focused.text,max(self.k,10));e3=self._normalize(raw3);attempts.append({"mode":"operation_focused","query":focused.to_dict(),"quality":_quality(focused.text,e3),"count":len(e3)})
   pooled=_merge_evidence(evidence,e3)
   bridge_text,bridge_diag=_cross_language_query(focused.fields.get("current_message") or query.fields.get("current_message"),focused.fields.get("subject") or (focused.fields.get("details") or {}).get("subject"),focused.fields.get("intent"))
   if bridge_text:
    bridge_fields=dict(focused.fields);bridge_fields.update({"cross_language_expansion":True,"query_isolation":"current_turn_only"})
    bridge_fp=hashlib.sha256(json.dumps({"text":bridge_text,"fields":bridge_fields},sort_keys=True,ensure_ascii=False,default=str).encode()).hexdigest()[:20];bridge=RetrievalQuery(bridge_text,bridge_fields,bridge_fp)
    raw4=self.retrieve_fn(bridge.text,max(self.k,10));e4=_attach_ranking_query(self._normalize(raw4),bridge.text,"cross_language_current_turn")
    attempts.append({"mode":"cross_language_current_turn","query":bridge.to_dict(),"quality":_quality(bridge.text,e4),"count":len(e4),"diagnostic":bridge_diag});pooled=_merge_evidence(pooled,e4)
   limit=18 if str(query.fields.get("intent") or "")=="requirements" else 8
   expanded,focused_diagnostic=_expand_candidate_documents(focused.text,pooled,maximum=3,limit=limit,select_single_procedural=str(query.fields.get("intent") or "")=="procedural")
   focused_diagnostic.update({"query":focused.to_dict(),"pool_count":len(pooled),"cross_language_expansion":bridge_diag,"policy_version":"cross_language_current_turn_v2_query_provenance"})
   if expanded:evidence=expanded;query=focused;raw=raw3;mode="multi_document_candidate_expansion";quality=_quality(focused.text,evidence)
  expansion={"enabled":False,"reason":"candidate_expansion_not_applied","llm_called":False}
  if str(query.fields.get("intent") or "") in {"procedural","requirements","troubleshooting"}:
   if str(focused_diagnostic.get("policy") or "").startswith("multi_document_candidate_expansion_v"):expansion=focused_diagnostic
   else:limit=18 if str(query.fields.get("intent") or "")=="requirements" else 8;evidence,expansion=_expand_procedure(query.text,evidence,limit)
  groups={}
  for x in evidence:
   identity=_identity(x);g=groups.setdefault(identity,{"identity":identity,"title":x["title"],"pages":[],"chunks":0});g["chunks"]+=1
   if x["page"] and x["page"] not in g["pages"]:g["pages"].append(x["page"])
  return {"enabled":True,"llm_called":False,"production_changed":False,"query":query.to_dict(),"ok":bool(raw.get("ok")),"adapter":raw.get("adapter"),"count":len(evidence),"evidence":evidence,"document_groups":list(groups.values()),"errors":raw.get("errors") or [],"diagnostic_only":True,"selection":{"chosen_mode":mode,"quality":quality,"attempts":attempts,"context_contamination_avoided":mode in {"current_turn_only","multi_document_candidate_expansion"},"operation_focused_recovery":focused_diagnostic,"preselected_document":None},"procedural_expansion":expansion,"conceptual_expansion":conceptual_expansion}
def retrieval_summary(r):
 if not r.get("ok"):return "No fue posible consultar el índice documental. El error quedó registrado para diagnóstico."
 if not r.get("count"):return "Consulté el índice documental, pero no encontré fragmentos para esta solicitud."
 titles=[]
 for g in r.get("document_groups") or []:
  if g["title"] not in titles:titles.append(g["title"])
 exp=r.get("procedural_expansion") or {};extra=f" Evidencia procedimental ordenada en {len(exp.get('pages') or [])} página(s) del documento principal." if exp.get("attempted") and exp.get("ok") else ""
 return f"Encontré {r['count']} fragmentos en {len(r.get('document_groups') or [])} documento(s). Fuentes principales: "+"; ".join(titles[:3])+"."+extra+" La respuesta documentada procedimental se habilitará después de validar esta evidencia."
