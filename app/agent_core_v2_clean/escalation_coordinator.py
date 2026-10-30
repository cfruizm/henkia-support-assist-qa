from __future__ import annotations
from copy import deepcopy
import unicodedata
from .escalation_contract import FIELDS,BY_KEY,ALIASES
from .escalation_export import build_export,build_text
OUTCOME_LABELS={"resolved":"resuelto","improved":"mejoró","unchanged":"sin cambios","worsened":"empeoró","unknown":"desconocido"}
def _norm(v):return " ".join(unicodedata.normalize("NFKD",str(v or "")).encode("ascii","ignore").decode().casefold().split())

def _correction_field(message,field=None):
 if field in BY_KEY:return field
 words=set(_norm(message).split())
 for alias,key in ALIASES.items():
  if _norm(alias) in words:return key
 return None

def _start_correction(state,message,w):
 field=_correction_field(message,getattr(w,"field",None))
 state.correction_field=field;state.correction_stage="value" if field else "field"
 if field:return {"handled":True,"status":"review","mode":"escalation_correction_value","text":"¿Cuál es el nuevo valor para "+BY_KEY[field].label.casefold()+"?","correction_field":field}
 return {"handled":True,"status":"review","mode":"escalation_correction_field","text":"Claro. ¿Qué campo deseas corregir?","correction_field":None}

def _handle_correction(state,message,memory,w,turn):
 if state.correction_stage=="field":
  field=_correction_field(message,getattr(w,"field",None))
  if not field:return {"handled":True,"status":"review","mode":"escalation_correction_field","text":"Indica cuál campo del resumen deseas corregir.","correction_field":None}
  state.correction_field=field;state.correction_stage="value"
  return {"handled":True,"status":"review","mode":"escalation_correction_value","text":"¿Cuál es el nuevo valor para "+BY_KEY[field].label.casefold()+"?","correction_field":field}
 if state.correction_stage=="value" and state.correction_field:
  value=str(getattr(w,"value",None) or message or "").strip()
  if not value:return {"handled":True,"status":"review","mode":"escalation_correction_value","text":"Indica el nuevo valor para "+BY_KEY[state.correction_field].label.casefold()+".","correction_field":state.correction_field}
  _set(state,state.correction_field,value,"user_correction","confirmed",turn)
  state.correction_stage=None;state.correction_field=None
  return response(state,memory)
 return None

def _offered_unknown_answer(message,spec):
 import re
 value=_norm(message).strip(" .,:;!?¡¿\"'")
 question=str(getattr(spec,"question","") or "")
 offered=[]
 for match in re.findall(r'["“”\']([^"“”\']+)["“”\']',question):
  candidate=_norm(match).strip(" .,:;!?¡¿\"'")
  if candidate:offered.append(candidate)
 return bool(value and value in offered)
def _direct_absence_answer(message,spec):
 value=_norm(message).strip(" .,:;!?¡¿\"'")
 if not value:return False
 if _offered_unknown_answer(message,spec):return True
 tokens=set(value.split())
 neg={"no","sin","ningun","ninguna","ninguno","nada"}
 unavailable={"aplica","tengo","hay","disponible","conozco","se","evidencia","evidencias","datos","dato","informacion","capturas","registros","logs"}
 return len(tokens)<=5 and bool(tokens&neg) and bool(tokens&unavailable)
def _substantive_narrative_answer(message,pending):
 if pending not in {'issue_description','troubleshooting_performed','device_data','impact_scope'}:return False
 value=" ".join(str(message or "").split()).strip()
 words=[x for x in _norm(value).split() if x]
 return len(words)>=5 and not (value.endswith('?') and len(words)<9)
def _set(state,key,value,source,status,turn):
 previous=deepcopy(state.fields.get(key));state.fields[key]={"value":value,"source":source,"status":status,"turn":turn}
 if key in state.unknown_fields and status!="unknown":state.unknown_fields.remove(key)
 if previous and previous.get("value")!=value:state.corrections.append({"field":key,"previous":previous.get("value"),"value":value,"turn":turn,"source":source})
def _source_rows(ctx):
 out=[];seen=set()
 for item in (ctx or {}).get("cited_evidence") or []:
  identity=str(item.get("source") or item.get("url") or item.get("title") or "")
  if identity and identity not in seen:seen.add(identity);out.append({"title":item.get("title"),"source":item.get("source") or item.get("url"),"page":item.get("page")})
 return out
def sync_from_memory(state,memory,ctx=None):
 turn=int(memory.turn_number or 0);case=memory.support_case
 records=getattr(memory,"fact_records",{}) or {}
 for key in ("client_contract_location","impact_scope","device_data","software_version","evidence","product_or_service","issue_description","troubleshooting_performed"):
  row=records.get(key) or {};value=str(row.get("value") or "").strip()
  if value and not state.fields.get(key):_set(state,key,value,"initial_message","confirmed",int(row.get("turn") or turn))
 case_subject=str(getattr(case,"subject",None) or "").strip()
 if (case_subject or memory.active_subject) and not state.fields.get("product_or_service"):_set(state,"product_or_service",case_subject or memory.active_subject,"support_case" if case_subject else "conversation","confirmed",turn)
 issue="; ".join(list(case.symptoms or [])+list(case.observations or []))
 if issue and not state.fields.get("issue_description"):_set(state,"issue_description",issue,"support_case","confirmed",turn)
 if case.attempts and not state.fields.get("troubleshooting_performed"):
  rows=[]
  for x in case.attempts:
   a=str(x.get("action") or "").strip();r=str(x.get("result") or "").strip();o=str(x.get("outcome") or "").strip()
   if a:
    detail=a+(". Resultado: "+r.rstrip(" .")+"." if r else ".")
    if o and o!="unknown":detail+=" Estado: "+OUTCOME_LABELS.get(o,o)+"."
    rows.append(" ".join(detail.split()))
  if rows:_set(state,"troubleshooting_performed","; ".join(dict.fromkeys(rows)),"support_case","confirmed",turn)
 if case.affected_scope and not state.fields.get("impact_scope"):_set(state,"impact_scope",case.affected_scope,"support_case","confirmed",turn)
 rows=_source_rows(ctx)
 if rows:state.sources_consulted=rows
def _advance(state):
 missing=next((x for x in FIELDS if x.required and not (state.fields.get(x.key) or {}).get("value")),None) or next((x for x in FIELDS if x.key not in state.fields),None)
 if missing:state.status="collecting";state.pending_field=missing.key
 else:state.status="review";state.pending_field=None
def start(state,memory,ctx=None,reason="Solicitud explícita del usuario",reuse=False):
 if not reuse:state.fields={};state.unknown_fields=[];state.corrections=[]
 state.status="collecting";state.correction_stage=None;state.correction_field=None;state.started_turn=memory.turn_number;state.completed_turn=None;state.completion_reason=None;state.confirmed=False;state.exported=False;state.suspended_reason=None;state.suspended_pending_field=None;state.escalation_reason={"value":reason,"source":"conversation","status":"confirmed","turn":state.started_turn};sync_from_memory(state,memory,ctx);_advance(state);return response(state,memory)
def response(state,memory):
 if state.status=="collecting":return {"handled":True,"status":"collecting","mode":"escalation_collecting","text":BY_KEY[state.pending_field].question,"pending_field":state.pending_field}
 if state.status=="review":return {"handled":True,"status":"review","mode":"escalation_review","text":build_text(state)+"\n\nPuedes confirmar, corregir un campo o cancelar el proceso.","pending_field":None}
 if state.status=="completed":return {"handled":True,"status":"completed","mode":"escalation_completed","text":"El escalamiento quedó confirmado y cerrado. Puedes realizar una nueva consulta.","export":build_export(state,memory.conversation_id)}
 if state.status=="cancelled":return {"handled":True,"status":"cancelled","mode":"escalation_cancelled","text":"Cancelé el escalamiento y regresé a la conversación normal."}
 return {"handled":False}
def handle(state,message,memory,w,ctx=None):
 role=w.turn_role;action=w.workflow_action;turn=int(memory.turn_number or 0)+1
 if state.status=="completed":
  state.status="inactive";state.pending_field=None
  if action=="confirm" or role=="workflow_action":
   return {"handled":True,"status":"inactive","mode":"post_escalation_acknowledgement","text":"Listo. El escalamiento ya estaba confirmado y permanece cerrado.","reset_after_completion":True}
  return {"handled":False,"reset_after_completion":True}
 if action=="cancel":state.status="cancelled";state.pending_field=None;state.correction_stage=None;state.correction_field=None;state.suspended_pending_field=None;state.completion_reason="user_cancelled";state.completed_turn=turn;return response(state,memory)
 if action=="suspend" or role=="independent_question":
  if state.status in {"collecting","review"}:state.suspended_pending_field=state.pending_field;state.status="suspended";state.suspended_reason="independent_question" if role=="independent_question" else "user_requested"
  return {"handled":False,"answer_independent":role=="independent_question","suspended":True}
 if action in {"resume","restart"}:
  if state.status=="suspended":state.status="collecting";state.pending_field=state.suspended_pending_field;state.suspended_pending_field=None;state.suspended_reason=None;_advance(state);return response(state,memory)
  if state.status=="cancelled":return start(state,memory,ctx,"Usuario reinició un escalamiento cancelado",reuse=True)
 if state.status=="suspended":return {"handled":False,"suspended":True}
 if state.status=="review":
  if state.correction_stage:
   corrected=_handle_correction(state,message,memory,w,turn)
   if corrected:return corrected
  if role=="correction" and not (w.field in BY_KEY and str(w.value or "").strip()):return _start_correction(state,message,w)
  if action=="confirm":state.status="completed";state.confirmed=True;state.exported=True;state.correction_stage=None;state.correction_field=None;state.completion_reason="user_confirmed";state.completed_turn=turn;return response(state,memory)
  if role=="correction" and w.field in BY_KEY and str(w.value or "").strip():_set(state,w.field,str(w.value).strip(),"user_correction","confirmed",turn);state.correction_stage=None;state.correction_field=None;return response(state,memory)
  return {"handled":True,"status":"review","mode":"escalation_review","text":"El resumen está listo. Puedes confirmarlo, corregir un campo o cancelar el proceso."}
 if state.status=="collecting":
  pending=state.pending_field
  spec=BY_KEY.get(pending)
  if spec and _direct_absence_answer(message,spec):role="unknown_value"
  elif role=="ambiguous" and spec and _offered_unknown_answer(message,spec):role="unknown_value"
  elif role=="ambiguous" and _substantive_narrative_answer(message,pending):
   role="field_value";w.value=" ".join(str(message or "").split()).strip()
  internal_absence_sentinels={"unknown_value","unknown","not_available","not_applicable","none","null"}
  if role=="field_value" and _norm(getattr(w,"value",None)) in internal_absence_sentinels:
   role="unknown_value"
  if role=="unknown_value":
   _set(state,pending,"No disponible","user","unknown",turn)
   if pending not in state.unknown_fields:state.unknown_fields.append(pending)
  elif role=="field_value" and str(w.value or "").strip():
   value=str(w.value).strip();duplicate=next((k for k,v in state.fields.items() if k!=pending and str((v or {}).get("status") or "confirmed")=="confirmed" and _norm((v or {}).get("value"))==_norm(value)),None)
   if duplicate:return {"handled":True,"status":"collecting","mode":"escalation_ambiguity","text":"Ese dato ya quedó registrado en otro campo. ¿Puedes indicar específicamente "+BY_KEY[pending].label.casefold()+"?","pending_field":pending}
   _set(state,pending,value,"user","confirmed",turn)
  else:return {"handled":True,"status":"collecting","mode":"escalation_ambiguity","text":"No pude determinar con seguridad si el mensaje responde a "+BY_KEY[pending].label.casefold()+". "+BY_KEY[pending].question,"pending_field":pending}
  sync_from_memory(state,memory,ctx);_advance(state);return response(state,memory)
 return {"handled":False}
