from __future__ import annotations
from copy import deepcopy
import re,unicodedata
from .text_stems import collapse_by_stem,stem_index,term_matches

_STOP={"para","pero","como","cuando","donde","desde","hasta","sobre","entre","esta","este","estos","estas","that","this","with","from","into","then","also","have","been","your","the","and","are","was","were","por","los","las","del","una","uno","unos","unas","que","con","sin","se","en","de","el","la","un","y","o","a","al","es","si","no"}
_DEFER_MARKERS=("no pude completar","intenta nuevamente","try again","provider","rate limit","limite de","documentacion directamente relacionada")

def _norm(value):
 text=unicodedata.normalize("NFKD",str(value or "")).encode("ascii","ignore").decode().casefold()
 return " ".join(text.split())

def _terms(value):
 return {x for x in re.findall(r"[a-z0-9][a-z0-9_-]{2,}",_norm(value)) if x not in _STOP}

def _overlap(a,b):
 if not a or not b:return 0.0
 return len(a&b)/max(1,min(len(a),len(b)))

def _history(retrieval):
 context=retrieval.get("_answer_context") or {}
 case=retrieval.get("_case_context") or {}
 attempted=[]
 for item in case.get("attempts") or []:
  action=item.get("action") if isinstance(item,dict) else item
  if action:attempted.append(str(action))
 delivered=[];ignored=[]
 for item in context.get("delivered_guidance") or []:
  action=item.get("action") if isinstance(item,dict) else item
  normalized=_norm(action)
  if not normalized:continue
  if any(marker in normalized for marker in _DEFER_MARKERS):ignored.append(str(action));continue
  delivered.append(str(action))
 return attempted,delivered,ignored

# Acts where the user asks for something specific rather than reporting an attempt.
# There the request decides which chunk is used; a chunk already delivered may be
# used again when it is the one that answers the question.
_REQUEST_ACTS={"follow_up","answer_to_question","request_elaboration"}

def _request_terms(understanding,retrieval):
 u=understanding or {};fields=((retrieval.get("query") or {}).get("fields") or {})
 details=u.get("goal_updates") or {}
 text=" ".join(str(x or "") for x in (u.get("current_goal"),fields.get("current_message"),*(details.values() if isinstance(details,dict) else ())))
 subject=_terms(" ".join(str(x or "") for x in (u.get("canonical_subject"),details.get("subject") if isinstance(details,dict) else None)))
 return collapse_by_stem({t for t in _terms(text)-subject if len(t)>=4 and not t.isdigit()})

def _relevance(terms,item):
 if not terms:return 0.0
 available=stem_index(_terms(item.get("text")))
 return sum(1 for t in terms if term_matches(t,available))/len(terms)

def select_progressive_evidence(retrieval,understanding,maximum=4):
 out=deepcopy(retrieval or {})
 evidence=list(out.get("generation_evidence") or out.get("evidence") or [])
 act=str((understanding or {}).get("user_act") or "")
 relation=str((understanding or {}).get("topic_relation") or "")
 attempted,delivered,ignored=_history(out)
 active=bool(evidence and (attempted or delivered) and act in {"attempt_result","follow_up","answer_to_question","request_elaboration"} and relation in {"same_topic","same_topic_refinement","return_to_previous"})
 if not active:
  out["progressive_evidence_selection"]={"active":False,"reason":"no_progressive_followup_context","input_count":len(evidence),"selected_count":len(evidence)}
  return out
 attempt_terms=[_terms(x) for x in attempted];delivered_terms=[_terms(x) for x in delivered]
 request_driven=act in _REQUEST_ACTS
 request_terms=_request_terms(understanding,out) if request_driven else set()
 rows=[]
 for position,item in enumerate(evidence):
  terms=_terms(" ".join((str(item.get("title") or ""),str(item.get("text") or ""))))
  attempted_overlap=max([_overlap(terms,x) for x in attempt_terms] or [0.0])
  delivered_overlap=max([_overlap(terms,x) for x in delivered_terms] or [0.0])
  semantic=float((item.get("semantic_fit") or {}).get("score",0.0) or 0.0)
  novelty=max(0.0,1.0-max(attempted_overlap,delivered_overlap))
  relevance=_relevance(request_terms,item) if request_driven else 0.0
  if request_driven:
   # The question decides: relevance first, novelty second. Only what the user
   # reported as tried counts against a chunk (not what was merely delivered).
   novelty=max(0.0,1.0-attempted_overlap)
   score=(relevance*0.60)+(novelty*0.25)+(semantic*0.15)
  else:
   # Novelty dominates on unchanged follow-ups; semantic fit remains a tie-breaker.
   score=(novelty*0.70)+(semantic*0.25)+(min(len(terms),80)/80*0.05)
  rows.append((score,novelty,-attempted_overlap,-delivered_overlap,semantic,-position,deepcopy(item),relevance))
 rows.sort(reverse=True,key=lambda x:x[:6])
 best_relevance=max((r[7] for r in rows),default=0.0)
 selected=[]
 for row in rows:
  item=row[6]
  # Chunks unrelated to a specific request are left out when related ones exist.
  if request_driven and best_relevance>0 and row[7]<best_relevance*0.5:continue
  # Strongly exhausted chunks are retained only if the progressive pool would be empty.
  if row[1]<0.48 and selected:continue
  selected.append((row[5],item))
  if len(selected)>=max(2,min(maximum,len(evidence))):break
 # A specific request keeps document order among the chosen chunks (row[5] is -position).
 if request_driven and best_relevance>0:selected.sort(key=lambda x:-x[0])
 selected=[item for _,item in selected]
 if not selected:selected=[row[6] for row in rows[:min(maximum,len(rows))]]
 for index,item in enumerate(selected,1):item["id"]=f"R{index}"
 out["generation_evidence"]=deepcopy(selected);out["evidence"]=deepcopy(selected)
 verdict=out.get("evidence_verdict") or {};verdict["selected_evidence"]=deepcopy(selected);verdict["evidence_ids"]=[x["id"] for x in selected];verdict["progressive_selection_applied"]=True;out["evidence_verdict"]=verdict
 out["progressive_evidence_selection"]={"active":True,"policy":"request_relevance_then_novelty_v2" if request_driven else "semantic_novelty_before_composition_v1","request_driven":request_driven,"request_terms":sorted(request_terms)[:12],"best_relevance":round(best_relevance,3),"input_count":len(evidence),"selected_count":len(selected),"attempted_count":len(attempted),"delivered_count":len(delivered),"ignored_non_action_guidance":len(ignored),"maximum":maximum,"selected_original_ids":[row[6].get("id") for row in rows if any(row[6].get("text")==x.get("text") for x in selected)]}
 return out
