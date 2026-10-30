from __future__ import annotations
from dataclasses import dataclass,asdict
import json,re,unicodedata
from .escalation_contract import BY_KEY
SCHEMA={"type":"object","properties":{"turn_role":{"type":"string","enum":["field_value","unknown_value","correction","independent_question","workflow_action","ambiguous"]},"workflow_action":{"type":"string","enum":["none","cancel","suspend","resume","confirm","restart"]},"field":{"type":["string","null"]},"value":{"type":["string","null"]},"confidence":{"type":"number"},"reason":{"type":"string"}},"required":["turn_role","workflow_action","field","value","confidence","reason"]}
SYSTEM="""Classify one message within an existing support-escalation workflow using only meaning and context. Lifecycle intent outranks field capture. Return workflow_action for cancel, suspend, resume, confirm or restart; independent_question for a temporary separate question; correction when the user asks to change the reviewed summary, identifies the field to change, supplies its new value, or combines those details; during review, a request to correct is never confirmation and must return turn_role correction with workflow_action none; Use unknown_value whenever the user communicates that the requested field is unavailable, unknown, absent, not applicable or cannot be provided, including a brief negative answer to the pending question; semantic absence is a valid answer and must advance the workflow. Use field_value only for substantive information that answers the pending question; otherwise use ambiguous. Do not use product assumptions or keyword rules. Return only schema JSON."""
@dataclass
class WorkflowUnderstanding:
 turn_role:str="ambiguous";workflow_action:str="none";field:str|None=None;value:str|None=None;confidence:float=0.;reason:str=""
 def to_dict(self):return asdict(self)

def _normalized_words(value):
 text=unicodedata.normalize("NFKD",str(value or "")).encode("ascii","ignore").decode().casefold()
 return [x for x in re.findall(r"[a-z]+",text) if x]

def _deterministic_lifecycle(message,status):
 """Resolve short, unambiguous workflow commands without provider dependency.

 The vocabulary is limited to lifecycle semantics from the workflow contract. It
 contains no product, customer, symptom, campaign or escalation-field values.
 """
 words=_normalized_words(message)
 if not words or len(words)>4:return None
 joined=" ".join(words)
 stems={
  "confirm":("confirm", "aprobar", "aceptar", "finalizar"),
  "cancel":("cancel", "salir", "abortar", "descartar"),
  "suspend":("pausar", "suspender"),
  "resume":("reanudar", "continuar", "retomar"),
  "restart":("reiniciar",),
 }
 matches=[]
 for action,prefixes in stems.items():
  if any(any(word.startswith(prefix) for prefix in prefixes) for word in words):matches.append(action)
 if len(matches)!=1:return None
 action=matches[0]
 if action=="confirm" and status!="review":return None
 if action in {"suspend","resume","restart"} and len(words)>2:return None
 return WorkflowUnderstanding("workflow_action",action,None,None,1.0,"deterministic_lifecycle_contract")

class WorkflowInterpreter:
 def __init__(self,gateway,max_tokens=96):self.gateway=gateway;self.max_tokens=max(72,min(112,int(max_tokens)));self.last_provider_result={};self.contract_valid=False
 def interpret(self,message,state):
  deterministic=_deterministic_lifecycle(message,state.status)
  if deterministic:
   self.last_provider_result={"skipped":True,"reason":"deterministic_lifecycle_contract"};self.contract_valid=True
   return deterministic
  from app.llm_gateway.models import LLMRequest
  pending=state.pending_field;spec=BY_KEY.get(pending)
  payload={"status":state.status,"field":pending,"question":spec.question if spec else None,"message":message}
  r=self.gateway.complete(LLMRequest([{"role":"system","content":SYSTEM},{"role":"user","content":json.dumps(payload,ensure_ascii=False,separators=(",",":"))}],"agent_core_v2_clean_workflow_understanding",self.max_tokens,0.,SCHEMA));self.last_provider_result=r.to_dict();self.contract_valid=False
  if not r.ok:return WorkflowUnderstanding(reason="provider_unavailable")
  try:
   raw=json.loads(str(r.text or "").strip());role=str(raw.get("turn_role") or "ambiguous");action=str(raw.get("workflow_action") or "none");field=raw.get("field");value=raw.get("value");confidence=float(raw.get("confidence") or 0);reason=str(raw.get("reason") or "")
   if role not in {"field_value","unknown_value","correction","independent_question","workflow_action","ambiguous"}:raise ValueError("invalid_role")
   if action not in {"none","cancel","suspend","resume","confirm","restart"}:raise ValueError("invalid_action")
   action_normalized=False
   if action!="none" and role!="workflow_action":role="workflow_action";action_normalized=True
   if role=="workflow_action" and action=="none":role="ambiguous"
   if role=="field_value":field=pending;value=str(value or message).strip()
   if role=="unknown_value":field=pending;value=None
   if action_normalized:reason=(reason+"; lifecycle action promoted to authoritative role").strip("; ")
   self.contract_valid=True;return WorkflowUnderstanding(role,action,field,value,confidence,reason)
  except Exception:return WorkflowUnderstanding(reason="invalid_contract")
