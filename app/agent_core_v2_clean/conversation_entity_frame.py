from copy import deepcopy
import re
import unicodedata

def c(v):return " ".join(str(v or "").split()).strip()
def same(a,b):return c(a).casefold()==c(b).casefold()
def _fold(v):return unicodedata.normalize("NFKD",c(v)).encode("ascii","ignore").decode().casefold()
def _mentioned(message, subject):
 value=_fold(subject); return bool(value and value in _fold(message))
def _related_subjects(message, old, history, explicit):
 candidates=[]
 for value in [old, explicit]+[x.get("subject") for x in history if isinstance(x,dict)]:
  value=c(value)
  if value and not any(same(value,x) for x in candidates) and _mentioned(message,value):candidates.append(value)
 return candidates

def _explicit_named_span(message):
 """Recover a structured named span without a product dictionary."""
 text=str(message or "");tokens=list(re.finditer(r"[A-Za-zÀ-ÖØ-öø-ÿ0-9][A-Za-zÀ-ÖØ-öø-ÿ0-9_.-]*",text))
 weak={"que","cual","cuales","como","para","por","con","del","los","las","una","uno","este","esta","eso","segun","sobre","what","which","how","for","the","this","that"}
 def shape(value):
  raw=str(value or "");letters=re.sub(r"[^A-Za-zÀ-ÖØ-öø-ÿ]","",raw)
  acronym=bool(letters and len(letters)>=2 and letters.upper()==letters)
  mixed=bool(re.search(r"[a-zà-öø-ÿ][A-ZÀ-ÖØ-Þ]",raw))
  identifier=bool(re.search(r"[A-Za-z].*\d|\d.*[A-Za-z]",raw))
  title=bool(letters and letters[:1].isupper() and letters[1:].islower())
  return acronym,mixed,identifier,title
 rows=[]
 for start in range(len(tokens)):
  for end in range(start+2,min(len(tokens),start+5)+1):
   group=tokens[start:end];values=[m.group(0) for m in group];folded=[_fold(x) for x in values]
   if any(x in weak for x in folded):continue
   forms=[shape(x) for x in values];strong=sum(1 for a,m,i,_ in forms if a or m or i);titled=sum(1 for *_,t in forms if t)
   if not strong or strong+titled<len(values):continue
   value=text[group[0].start():group[-1].end()].strip(" .,:;!?()[]{}")
   if value:rows.append((strong,len(values),len(value),value))
 if not rows:return None
 rows.sort(reverse=True,key=lambda x:(x[0],x[1],x[2]));return rows[0][3]

def _declared_intent(goal,summary):
 """Recover an intent explicitly declared by the provider's normalized goal.

 This is intentionally limited to semantic categories, not products, domains,
 customers, document names, or campaign phrases.
 """
 text=" ".join((_fold(goal),_fold(summary)))
 signals={
  "requirements":("requirements","requirement","requisitos","requisito","requerimientos","prerequisites","prerequisite"),
  "troubleshooting":("troubleshooting","diagnose","diagnostico","diagnosticar","failure","falla","symptom","sintoma"),
  "conceptual":("conceptual","definition","definicion","explain what","explicar que"),
  "procedural":("procedural","procedure","procedimiento","configure","configurar","how to","como hacer"),
 }
 matches=[intent for intent,terms in signals.items() if any(term in text for term in terms)]
 return matches[0] if len(matches)==1 else None

def reconcile_entity_frame(memory,u,message=""):
 old=c(getattr(memory,"active_subject",None)) or None;new=c(getattr(u,"canonical_subject",None)) or None;origin=c(getattr(u,"subject_origin",None));ref=c(getattr(u,"reference_relation",None)) or "none";h=list(getattr(memory,"subject_history",[]) or []);selected=old;transition="inherit"
 recovered=None
 # Narrow recovery for a provider-inherited subject. It is disabled for
 # references/follow-ups and requires an orthographically structured span.
 if old and (not new or same(old,new)) and ref=="none" and not _mentioned(message,old):
  recovered=_explicit_named_span(message)
  if recovered and not same(recovered,old):
   new=recovered;origin="current_message";u.canonical_subject=recovered;u.subject_origin="current_message";u.reference_relation="none";u.topic_relation="new_topic";u.user_act="new_request";u.goal_updates={**dict(getattr(u,"goal_updates",{}) or {}),"subject":recovered}
 independent_current_turn=(
  str(getattr(u,"topic_relation","") or "").casefold() in {"new_topic","independent"}
  and str(getattr(u,"user_act","") or "").casefold() in {"new_request","independent_question","topic_change"}
  and ref=="none"
 )
 related=[] if independent_current_turn else _related_subjects(message,old,h,new)
 if independent_current_turn and not (new and origin=="current_message"):
  # A canonical new-topic decision without a structured reference must not
  # inherit the previous subject merely because no new subject was extracted.
  if old and (not h or not same(h[-1].get("subject"),old)):
   h.append({"subject":old,"turn":getattr(memory,"turn_number",0)})
  selected=None;transition="independent_turn_without_explicit_subject"
  updates=dict(getattr(u,"goal_updates",{}) or {})
  if updates.get("subject") and old and same(updates.get("subject"),old):updates.pop("subject",None)
  if updates.get("document_object") and not _mentioned(message,updates.get("document_object")):updates.pop("document_object",None)
  updates.pop("related_subjects",None);u.goal_updates=updates
  u.canonical_subject=None;u.subject_origin=None;u.reference_relation="none"
  memory.active_subject=None
 elif len(related)>=2:
  # Comparative/applicability turns are relational. Preserve every explicitly
  # mentioned known subject in the structured goal instead of collapsing the
  # request to whichever entity the provider selected as canonical.
  selected=old or new or related[-1];transition="multi_entity_relation"
  u.goal_updates={**dict(getattr(u,"goal_updates",{}) or {}),"subject":selected,"related_subjects":" | ".join(related)}
  u.canonical_subject=selected;u.topic_relation="same_topic"
 elif ref=="previous_subject" and h:
  # Q3.2: a structured historical return targets the subject resolved from the
  # current message when that subject exists in history. The last history row is
  # only a fallback because intermediate topics can appear after the target.
  historical=[c(row.get("subject")) for row in reversed(h) if isinstance(row,dict) and c(row.get("subject"))]
  selected=(
   next((value for value in historical if new and same(value,new)),None)
   or next((value for value in historical if _mentioned(message,value)),None)
   or next((value for value in historical if not old or not same(value,old)),None)
   or new or old
  )
  transition="return_to_previous"
 elif new and origin=="current_message":
  selected=new
  if old and not same(old,new):
   if not h or not same(h[-1].get("subject"),old):h.append({"subject":old,"turn":getattr(memory,"turn_number",0)})
   transition="explicit_subject_change"
 elif new:selected=new
 intent_reconciliation={"applied":False,"reason":"transition_not_eligible"}
 declared=_declared_intent(getattr(u,"current_goal",None),getattr(u,"reasoning_summary",None));previous_intent=str(getattr(u,"intent","") or "")
 same_subject_continuation=bool(old and selected and same(old,selected) and (ref=="current_subject" or str(getattr(u,"topic_relation","") or "") in {"same_topic","same_topic_refinement"}))
 if transition=="explicit_subject_change" or same_subject_continuation:
  source="explicit_subject_change_goal_contract" if transition=="explicit_subject_change" else "same_subject_followup_goal_contract"
  if declared and declared!=previous_intent:
   u.intent=declared;intent_reconciliation={"applied":True,"previous_intent":previous_intent,"selected_intent":declared,"source":source}
  elif declared:intent_reconciliation={"applied":False,"reason":"declared_intent_already_selected","selected_intent":declared,"source":source}
  else:intent_reconciliation={"applied":False,"reason":"no_unique_declared_category","source":source}
 if selected:
  memory.active_subject=selected;u.canonical_subject=selected;u.goal_updates={**dict(getattr(u,"goal_updates",{}) or {}),"subject":selected}
 if transition=="explicit_subject_change":u.topic_relation="new_topic";u.user_act="new_request"
 elif transition=="return_to_previous":u.topic_relation="return_to_previous"
 memory.subject_history=h[-8:]
 return u,{"version":"entity_frame_v5_subject_and_followup_intent_reconciliation","active_before":old,"explicit":new,"recovered_explicit":recovered,"reference":ref,"selected":selected,"related_subjects":related,"transition":transition,"intent_reconciliation":intent_reconciliation,"history":deepcopy(memory.subject_history)}
