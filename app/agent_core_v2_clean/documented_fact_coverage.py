from __future__ import annotations
from copy import deepcopy
import re
import unicodedata

_GENERIC_WORDS={
 "cual","cuales","que","como","donde","cuando","esos","esas","este","esta","estos","estas",
 "documenta","documentado","fuente","utiliza","utilizan","usa","usan","tiene","tienen","para","con",
 "del","las","los","una","uno","unos","unas","and","the","which","what","that","those","uses","use",
 "documented","source","required","requerido","requeridos","son","is","are"
}
_EXHAUSTIVE_MARKERS=(r"\bcuales\b",r"\blista\b",r"\blistar\b",r"\btodos\b",r"\btodas\b",r"\bwhich\b",r"\blist\b",r"\ball\b")
_TABLE_ROW_RE=re.compile(r"(?<![A-Za-z0-9])(\d{2,6})\s+[iIlL]\s+(?:[lL]\s*/\s*[rR]|[rR]\s*/\s*[lL]|[lLrR])\s+(?:UDP|TCP)\b",re.I)

def _norm(value):
 text=unicodedata.normalize("NFKD",str(value or "")).encode("ascii","ignore").decode("ascii").casefold()
 return re.sub(r"\s+"," ",text).strip()

def _property_terms(question):
 raw=re.findall(r"[a-z0-9][a-z0-9_.+/-]*",_norm(question))
 return {x for x in raw if x not in _GENERIC_WORDS and (len(x)>=3 or any(ch.isdigit() for ch in x))}

def _numeric_values(text):
 values=set(re.findall(r"(?<![A-Za-z0-9])\d{2,6}(?![A-Za-z0-9])",str(text or "")))
 return {value for value in values if not (len(value)==4 and 1900<=int(value)<=2099)}

def _identity(item):
 return str(item.get("url") or item.get("source") or (item.get("metadata") or {}).get("canonical_url") or "")

def expects_exhaustive_numeric_list(question):
 value=_norm(question)
 return bool(any(re.search(pattern,value) for pattern in _EXHAUSTIVE_MARKERS) and _property_terms(question))

def _fetched_rows(fetch_same_document,question,target):
 """Same-document fragments fetched on demand, normalized to the evidence contract."""
 try:raw=fetch_same_document(question,target,12) or {}
 except Exception:return []
 rows=[]
 for item in raw.get("evidence") or []:
  meta=dict(item.get("metadata") or {});text=" ".join(str(item.get("text") or "").split())
  if not text or str(item.get("source") or "")!=target:continue
  # Only fragments carrying values can complete a numeric enumeration; skipping
  # the rest keeps the generation prompt small (QA: 13 fragments exhausted the
  # output budget with an empty response).
  if not _numeric_values(text):continue
  page=meta.get("page_label") or meta.get("page") or item.get("page") or ""
  rows.append({"title":item.get("title") or meta.get("title") or "","source":target,"url":item.get("url") or "","page":str(page),"text":text,"metadata":meta,"origin":"exhaustive_same_document_fetch"})
 return rows

_FOLLOWUP_ACTS={"follow_up","request_elaboration","answer_to_question"}

def followup_value_request(retrieval,question):
 """A follow-up that asks for a property whose values the document lists.

 QA: "¿Y los puertos?" after the SDS requirements answered with no port because
 the exhaustive read required marker words ("cuáles", "lista", "todos"). Without
 a word list: a same-topic follow-up whose requested terms appear, by stem, in
 fragments of the accepted document that carry numeric values.
 """
 from .text_stems import stem_index,term_matches
 fields=((retrieval or {}).get("query") or {}).get("fields") or {}
 if str(fields.get("user_act") or "") not in _FOLLOWUP_ACTS:return False
 if str(fields.get("topic_relation") or "") not in {"same_topic","same_topic_refinement"}:return False
 terms={t for t in _property_terms(question) if not t.isdigit()}
 if not terms:return False
 rows=list((retrieval or {}).get("generation_evidence") or (retrieval or {}).get("evidence") or [])+list((retrieval or {}).get("diagnostic_evidence") or [])
 for row in rows:
  text=str(row.get("text") or "")
  if len(_numeric_values(text))<2:continue
  available=stem_index({w for w in re.findall(r"[a-z0-9]+",_norm(text)) if len(w)>=3})
  if any(term_matches(t,available) for t in terms):return True
 return False

def augment_exhaustive_numeric_evidence(retrieval,question,fetch_same_document=None):
 diagnostic={"activated":False,"reason":"not_exhaustive_numeric_request","selected_document":None,"base_count":0,"added_count":0,"final_count":0}
 if not (expects_exhaustive_numeric_list(question) or followup_value_request(retrieval,question)):return deepcopy(retrieval or {}),diagnostic
 out=deepcopy(retrieval or {});verdict=out.get("evidence_verdict") or {}
 base=list(verdict.get("selected_evidence") or out.get("generation_evidence") or out.get("evidence") or [])
 diagnostic["base_count"]=len(base);identities=[_identity(x) for x in base if _identity(x)]
 if not identities:return out,{**diagnostic,"reason":"no_authorized_document_identity"}
 target=identities[0];diagnostic["selected_document"]=target;candidates=list(out.get("diagnostic_evidence") or [])
 # The retrieval pool can be thin (e.g. a turn routed as conceptual keeps few
 # candidates), so the table holding the requested values may be missing. When a
 # same-document fetcher is available, read more fragments of the selected document.
 if fetch_same_document is not None:
  fetched=_fetched_rows(fetch_same_document,question,target);candidates+=fetched;diagnostic["fetched_count"]=len(fetched)
 merged=[];seen=set()
 for row in base+[x for x in candidates if _identity(x)==target]:
  text=" ".join(str(row.get("text") or "").split());signature=(str(row.get("page") or ""),text.casefold())
  if not text or signature in seen:continue
  seen.add(signature);merged.append(deepcopy(row))
 if len(merged)<=len(base):return out,{**diagnostic,"reason":"no_additional_same_document_fragments","final_count":len(base)}
 for index,row in enumerate(merged,1):row["id"]=f"R{index}"
 out["generation_evidence"]=merged;out["evidence"]=merged
 if verdict.get("selected_evidence") is not None:
  out["evidence_verdict"]={**verdict,"selected_evidence":deepcopy(merged),"evidence_ids":[x["id"] for x in merged]}
 diagnostic.update({"activated":True,"reason":"same_document_diagnostic_fragments_added","added_count":len(merged)-len(base),"final_count":len(merged)})
 return out,diagnostic

def _table_numeric_candidates(row,terms):
 rid=str(row.get("id") or "").strip();body=str(row.get("text") or row.get("content") or "")
 normalized=_norm(body);title=_norm(row.get("title"));context=normalized+" "+title
 property_context=any(re.search(rf"\b{re.escape(term.rstrip('s'))}\w*\b",context) for term in terms)
 candidates={};variants=sorted({term.rstrip("s") for term in terms if len(term)>=3},key=len,reverse=True)
 if variants:
  property_pattern="|".join(re.escape(value) for value in variants)
  for match in re.finditer(rf"\b(?:{property_pattern})\w*\s*(?:numero|number|no\.?|#|:|-)?\s*(\d{{2,6}})\b",normalized,re.I):
   value=match.group(1)
   if value not in _numeric_values(value):continue
   left=max(0,match.start()-90);right=min(len(body),match.end()+220)
   candidates.setdefault(value,{"id":rid,"page":row.get("page"),"title":row.get("title"),"source":row.get("url") or row.get("source"),"excerpt":" ".join(body[left:right].split()),"method":"explicit_property_value"})
 # The structural columns themselves establish table authority: numeric value,
 # network scope, local/remote direction and protocol. This remains language-
 # independent when the question and the document use different languages.
 matches=list(_TABLE_ROW_RE.finditer(body))
 for index,match in enumerate(matches):
  value=match.group(1)
  if value not in _numeric_values(value):continue
  right=matches[index+1].start() if index+1<len(matches) else min(len(body),match.end()+300)
  excerpt=" ".join(body[match.start():right].strip(" .;,").split())
  candidates.setdefault(value,{"id":rid,"page":row.get("page"),"title":row.get("title"),"source":row.get("url") or row.get("source"),"excerpt":excerpt,"method":"structured_table_row"})
 return candidates

def collect_compact_numeric_rows(question,rows,maximum=16):
 terms=_property_terms(question);out=[];seen=set()
 if not expects_exhaustive_numeric_list(question) or not terms:return out
 for row in rows or []:
  for value,item in _table_numeric_candidates(row,terms).items():
   if value in seen:continue
   seen.add(value)
   out.append({"id":item["id"],"title":item["title"],"page":item["page"],"source":item["source"],"text":item["excerpt"],"numeric_table_value":value,"numeric_table_method":item["method"]})
 return sorted(out,key=lambda item:int(item["numeric_table_value"]))[:maximum]

def numeric_enumeration_evidence_score(question,row):
 terms=_property_terms(question)
 if not expects_exhaustive_numeric_list(question) or not terms:return 0.0
 candidates=_table_numeric_candidates(row,terms)
 if not candidates:return 0.0
 return 1.0 if any(item["method"]=="structured_table_row" for item in candidates.values()) else .75

def ensure_enumerated_numeric_fact_coverage(text,question,evidence,minimum=2,maximum=16,repair_limit=12):
 terms=_property_terms(question)
 diagnostic={"checked":False,"exhaustive_request":expects_exhaustive_numeric_list(question),"property_terms":sorted(terms),"documented_values":[],"response_values":sorted(_numeric_values(text),key=int),"missing_values":[],"repaired":False,"extraction_methods":{},"candidate_rows":[]}
 if not diagnostic["exhaustive_request"] or not terms:return text,diagnostic
 candidates={}
 for row in evidence or []:
  for value,item in _table_numeric_candidates(row,terms).items():candidates.setdefault(value,item)
 values=sorted(candidates,key=int);diagnostic["documented_values"]=values
 diagnostic["candidate_rows"]=[{"value":value,"evidence_id":candidates[value]["id"],"method":candidates[value]["method"],"excerpt":candidates[value]["excerpt"][:420]} for value in values]
 diagnostic["extraction_methods"]={method:sum(1 for item in candidates.values() if item["method"]==method) for method in sorted({item["method"] for item in candidates.values()})}
 if not (minimum<=len(values)<=maximum):return text,diagnostic
 diagnostic["checked"]=True;present=_numeric_values(text);missing=[value for value in values if value not in present];diagnostic["missing_values"]=missing
 if not missing or len(missing)>repair_limit:return text,diagnostic
 lines=[]
 for value in missing:
  item=candidates[value];citation=f" [{item['id']}]" if item["id"] else "";lines.append(f"- {item['excerpt'].rstrip(' .')}.{citation}")
 diagnostic["repaired"]=True;diagnostic["added_values"]=missing
 return str(text or "").rstrip()+"\n\n**Elementos documentados adicionales**\n\n"+"\n".join(lines),diagnostic
