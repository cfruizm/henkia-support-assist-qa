from copy import deepcopy
from .models import ConversationMemory,TurnUnderstanding,PendingGoal,SupportCase
STRUCTURAL_GOAL_KEYS={"intent","status","summary","known_details","missing_detail","goal_complete","current_goal","goal_type","goal_updates","answer_to_question"}
def normalize_goal_updates(updates):
 raw=dict(updates or {});clean={str(k):str(v) for k,v in raw.items() if str(k) not in STRUCTURAL_GOAL_KEYS and str(v).strip()};return clean,sorted(set(map(str,raw))-set(clean))
def _attempt_key(v):return " ".join(str(v or "").casefold().split())
def _fold(v):
 import unicodedata
 return unicodedata.normalize("NFKD",str(v or "")).encode("ascii","ignore").decode().casefold()
def _infer_outcome(result):
 import re
 value=_fold(result)
 patterns={
  "resolved":r"\b(?:resuelto|solucionado|funciona|resolved|fixed|working)\b",
  "improved":r"\b(?:mejoro|mejora|parcialmente|improved|better|partially)\b",
  "worsened":r"\b(?:empeoro|empeora|worsened|worse)\b",
  "unchanged":r"\b(?:continua|persiste|sigue|sin cambios|no resolvio|no soluciono|unchanged|persists|still fails|not resolved)\b",
 }
 return next((outcome for outcome,pattern in patterns.items() if re.search(pattern,value)),"unknown")
def _add(xs,v):
 v=" ".join(str(v or "").split())
 if v and v.casefold() not in {x.casefold() for x in xs}:xs.append(v)
def _record_user_facts(m,clean):
 for k,v in clean.items():m.fact_records[str(k)]={"key":str(k),"value":str(v),"origin":"user","status":"confirmed","turn":m.turn_number+1}

def _history_subject(row):
 """Return the technical owner of an archived context.

 A diagnosing/reopened case is more authoritative than the UI subject that
 happened to be active when the archive operation ran.
 """
 row=dict(row or {})
 case=dict(row.get("case") or {})
 case_subject=str(case.get("subject") or "").strip()
 archived_subject=str(row.get("subject") or "").strip()
 pending_subject=str(((row.get("pending_goal") or {}).get("known_details") or {}).get("subject") or "").strip()
 if str(case.get("status") or "").casefold() in {"diagnosing","reopened"} and case_subject:
  return case_subject
 return case_subject or pending_subject or archived_subject

def _history_matches_subject(row,subject):
 target=_fold(subject)
 if not target:return False
 row=dict(row or {});case=dict(row.get("case") or {})
 identities={
  _fold(row.get("subject")),
  _fold(case.get("subject")),
  _fold(((row.get("pending_goal") or {}).get("known_details") or {}).get("subject")),
 }
 identities.discard("")
 if target in identities:return True
 # Compatibility with entries created before subject identity was persisted.
 summary=_fold(" ".join(str(row.get(key) or "") for key in ("topic","goal")))
 return bool(target and target in summary)

def restore_historical_context(m,u):
 """Restore one exact archived context for a structured historical return."""
 relation=str(getattr(u,"topic_relation","") or "").casefold()
 reference=str(getattr(u,"reference_relation","") or "").casefold()
 if relation!="return_to_previous" or reference!="previous_subject":
  return {"applied":False,"reason":"not_structured_historical_return"}
 subject=str(getattr(u,"canonical_subject",None) or (getattr(u,"goal_updates",{}) or {}).get("subject") or "").strip()
 history=list(getattr(m,"topic_history",[]) or [])
 index=next((i for i in range(len(history)-1,-1,-1) if _history_matches_subject(history[i],subject)),None)
 if index is None:
  return {"applied":False,"reason":"matching_archived_context_not_found","subject":subject or None}
 archived=deepcopy(history.pop(index))
 current_case=deepcopy(getattr(m,"support_case",SupportCase()).__dict__)
 current_goal=deepcopy(getattr(m,"pending_goal",PendingGoal()).__dict__)
 current_case_subject=str(current_case.get("subject") or "").strip()
 current_pending_subject=str((current_goal.get("known_details") or {}).get("subject") or "").strip()
 current_active_subject=str(getattr(m,"active_subject",None) or "").strip()
 current_subject=current_case_subject or current_pending_subject or current_active_subject or None
 if getattr(m,"active_topic",None) or current_subject or current_case.get("status")!="idle":
  history.append({
   "topic":getattr(m,"active_topic",None),
   "goal":current_goal.get("summary"),
   "pending_goal":current_goal,
   "case":current_case,
   "subject":current_subject,
   "fact_records":deepcopy(getattr(m,"fact_records",{}) or {}),
   "archived_reason":"historical_return_switch",
  })
 m.topic_history=history[-8:]
 pending=dict(archived.get("pending_goal") or {})
 if not pending:
  pending={"summary":archived.get("goal") or archived.get("topic") or "","intent":getattr(u,"intent","unknown"),"known_details":{},"missing_detail":None,"status":"active"}
 m.pending_goal=PendingGoal(**{key:pending.get(key) for key in PendingGoal.__dataclass_fields__ if key in pending})
 case=dict(archived.get("case") or {})
 m.support_case=SupportCase(**{key:case.get(key) for key in SupportCase.__dataclass_fields__ if key in case})
 m.active_topic=archived.get("topic") or archived.get("goal") or m.pending_goal.summary
 m.active_subject=subject or _history_subject(archived) or getattr(m,"active_subject",None)
 if m.active_subject:
  m.pending_goal.known_details={**dict(m.pending_goal.known_details or {}),"subject":m.active_subject}
  if m.support_case.status in {"diagnosing","reopened"} and not m.support_case.subject:m.support_case.subject=m.active_subject
 m.fact_records=deepcopy(archived.get("fact_records") or {})
 return {
  "applied":True,
  "reason":"exact_archived_subject_context_restored",
  "subject":m.active_subject,
  "archived_subject":archived.get("subject"),
  "archived_case_subject":case.get("subject"),
  "restored_case_status":m.support_case.status,
  "restored_attempt_count":len(m.support_case.attempts),
  "restored_observation_count":len(m.support_case.observations),
 }

def apply_understanding(m,u):
 if u.degraded and not u.should_retrieve:m.turn_number+=1;return
 answering=u.user_act=="answer_to_question" and bool(m.last_assistant_question)
 current_subject=str(getattr(u,"canonical_subject",None) or (u.goal_updates or {}).get("subject") or "").strip()
 case_subject=str(getattr(m.support_case,"subject",None) or "").strip()
 explicit_subject_change=bool(
  str(getattr(u,"subject_origin",None) or "").casefold()=="current_message"
  and current_subject and case_subject and _fold(current_subject)!=_fold(case_subject)
 )
 new_goal=bool(
  not answering and u.domain_relevance=="in_scope" and m.active_topic
  and (
   explicit_subject_change
   or (u.topic_relation in {"new_topic","independent"} and u.current_goal!=m.active_topic)
  )
 )
 active_case_continuation=bool(
  m.support_case.status in {"diagnosing","reopened"}
  and u.intent in {"troubleshooting","procedural","requirements","verification"}
  and not explicit_subject_change
 )
 if new_goal and not active_case_continuation:
  archive_subject=(
   str(getattr(m.support_case,"subject",None) or "").strip()
   or str((m.pending_goal.known_details or {}).get("subject") or "").strip()
   or str(getattr(m,"active_subject",None) or "").strip()
   or None
  )
  m.topic_history.append({"topic":m.active_topic,"goal":m.pending_goal.summary,"pending_goal":deepcopy(m.pending_goal.__dict__),"case":deepcopy(m.support_case.__dict__),"subject":archive_subject,"fact_records":deepcopy(m.fact_records),"archived_reason":"explicit_subject_change" if explicit_subject_change else "new_goal"})
  m.topic_history=m.topic_history[-8:];m.pending_goal=PendingGoal();m.support_case=type(m.support_case)();m.fact_records={}
 if u.domain_relevance=="in_scope":
  if not answering:
   m.active_topic=u.current_goal or m.active_topic
   if u.current_goal:m.pending_goal.summary=u.current_goal
  if u.intent!="unknown" and not answering:m.pending_goal.intent=u.intent
  clean,_=normalize_goal_updates(u.goal_updates);m.pending_goal.known_details.update(clean);_record_user_facts(m,clean)
  if u.needs_clarification and u.clarification_target:m.pending_goal.missing_detail=u.clarification_target;m.pending_goal.status="waiting_user"
  else:m.pending_goal.missing_detail=None;m.pending_goal.status="complete" if u.goal_complete else "active"
  case_updates=list(u.case_updates or [])
  if u.intent=="troubleshooting" and answering and m.last_assistant_question and not case_updates:
   raw=str((u.goal_updates or {}).get("answer_to_question") or "").strip()
   if raw:case_updates.append({"type":"observation","value":"Pregunta: "+m.last_assistant_question+" Respuesta: "+raw})
  if u.intent=="troubleshooting":
   present={str(x.get("type") or "") for x in case_updates}
   for key in ("symptom","observation","affected_scope","attempted_action","attempt_result"):
    value=str(clean.get(key) or "").strip()
    if value and key not in present:case_updates.append({"type":key,"value":value})
  normalized_updates=[]
  for raw in case_updates:
   f=dict(raw or {})
   if not f.get("result"):
    for alias in ("result_detail","result_text","observed_result","result_observed","result_value","result_state"):
     if str(f.get(alias) or "").strip():f["result"]=f.get(alias);break
   if not f.get("outcome"):
    for alias in ("outcome_status","result_status","resolution_outcome","outcome_observed","outcome_text","observed_outcome","outcome_value","outcome_state"):
     if str(f.get(alias) or "").strip():f["outcome"]=f.get(alias);break
   normalized_updates.append(f)
  for index,f in enumerate(normalized_updates):
   k,v=str(f.get("type") or ""),str(f.get("value") or "").strip()
   if k=="scope":k="affected_scope"
   if k=="attempted_action" and not str(f.get("result") or "").strip():
    observed=next((str(x.get("value") or "").strip() for x in normalized_updates[index+1:] if str(x.get("type") or "") in {"observation","attempt_result"} and str(x.get("value") or "").strip()),None)
    if observed:f["result"]=observed
   if k=="attempted_action" and str(f.get("outcome") or "unknown").casefold()=="unknown" and str(f.get("result") or "").strip():
    f["outcome"]=_infer_outcome(f.get("result"))
   if k in {"symptom","reported_failure","new_case"}:
    _add(m.support_case.symptoms,v);m.support_case.status="diagnosing"
    subject=str(getattr(u,"canonical_subject",None) or (u.goal_updates or {}).get("subject") or "").strip()
    if subject and not m.support_case.subject:m.support_case.subject=subject
   elif k=="observation":
    consumed=any(str(x.get("type") or "")=="attempted_action" and _attempt_key(x.get("result"))==_attempt_key(v) for x in normalized_updates[:index])
    if not consumed:_add(m.support_case.observations,v)
    m.support_case.status="diagnosing"
   elif k=="affected_scope":m.support_case.affected_scope=v;m.support_case.status="diagnosing"
   elif k=="attempted_action":
    result=str(f.get("result") or f.get("result_continuation") or "").strip() or None
    outcome=str(f.get("outcome") or f.get("result_outcome") or "unknown").strip().casefold()
    if outcome not in {"resolved","improved","unchanged","worsened","unknown"}:outcome="unknown"
    existing=next((x for x in m.support_case.attempts if _attempt_key(x.get("action"))==_attempt_key(v)),None)
    if existing:
     if result:existing["result"]=result
     if outcome!="unknown" or not existing.get("outcome"):existing["outcome"]=outcome
    else:m.support_case.attempts.append({"action":v,"result":result,"outcome":outcome})
    m.support_case.status="diagnosing"
   elif k=="attempt_result":
    outcome=str(f.get("outcome") or "unknown").strip().casefold()
    if outcome not in {"resolved","improved","unchanged","worsened","unknown"}:outcome="unknown"
    if outcome=="unknown" and result:outcome=_infer_outcome(result)
    if m.support_case.attempts:m.support_case.attempts[-1].update({"result":v,"outcome":outcome})
    else:m.support_case.attempts.append({"action":"previous validation","result":v,"outcome":outcome})
    m.support_case.status="diagnosing"
 m.turn_number+=1
def compact_context(m):return {"active_topic":m.active_topic,"pending_goal":m.pending_goal.__dict__,"confirmed_facts":list(m.fact_records.values()),"support_case":m.support_case.__dict__,"escalation":m.escalation.to_dict(),"last_assistant_question":m.last_assistant_question,"summary":m.summary,"recent_topics":m.topic_history[-2:]}
