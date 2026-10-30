import json
import re
import unicodedata
from .contracts import UNDERSTANDING_SCHEMA
from .models import TurnUnderstanding
from .memory import compact_context,normalize_goal_updates

_SOCIAL_CORE={"hola","buenas","buenos","saludos","hello","hi","hey","gracias","thanks","thank","adios","chao","bye"}
_SOCIAL_MODIFIERS={"muchas","muchisimas","mil","muy","dias","tardes","noches","you"}
def _normalized_tokens(value):
 text=unicodedata.normalize("NFKD",str(value or "")).encode("ascii","ignore").decode().casefold()
 return [x for x in re.findall(r"[a-z]+",text) if x]
def _is_terminal_social_message(message):
 tokens=_normalized_tokens(message)
 allowed=_SOCIAL_CORE|_SOCIAL_MODIFIERS
 return bool(tokens) and len(tokens)<=4 and any(x in _SOCIAL_CORE for x in tokens) and all(x in allowed for x in tokens)

def _can_normalize_terminal_social(message,understanding):
 if not _is_terminal_social_message(message):return False
 x=understanding
 # An entity inferred only from conversation memory cannot convert courtesy into
 # a technical follow-up. An entity explicit in the current message remains binding.
 explicit_subject=bool(x.canonical_subject) and str(x.subject_origin or "").casefold()=="current_message"
 return not explicit_subject and not x.case_updates and str(x.requested_workflow or "none").casefold()=="none"

SYSTEM="""Semantic understanding for an enterprise printing-support assistant. Interpret the current message using memory and the last assistant question. The current_goal must express the current request, not copy an earlier operation. Distinguish conceptual, procedural, requirements and troubleshooting. Use case_history when the user asks what actions, observations, results or assistant recommendations are already recorded in the active support case, or asks to distinguish performed actions from merely suggested guidance. case_history is answered from structured conversation state: set should_retrieve false, needs_clarification false, requested_workflow none, and do not add case_updates for the request itself. Use requirements for prerequisites, compatibility, constraints or conditions; use procedural for execution steps. A changed operation about the same subject refines the goal and remains same_topic. request_elaboration is valid only when the message depends on an active goal or last assistant question. answer_to_question supplies requested information. Put symptoms and diagnostic facts in case_updates. Clarify only when one missing fact is indispensable. A clear conceptual request never needs clarification. Return one complete JSON object matching the schema. No fields outside the schema. Extract canonical_subject as the product, platform, component or technical entity governing the request. Never copy the full request. subject_origin is current_message only when explicit, otherwise conversation_memory. reference_relation is previous_subject when returning to the previously active entity, current_subject when referring to the active entity, otherwise none. A changed operation does not change canonical_subject. An explicit different subject creates new_topic. Keep reasoning_summary under 20 words. requested_workflow is an independent operational workflow contract. Use start_escalation only when the user actually requests transfer or escalation of the current support case. A conceptual question about escalation, a request to explain escalation, or generic mention of escalation must use none. Use cancel_escalation, suspend_escalation, resume_escalation or confirm_escalation only when the user requests that lifecycle action. Do not infer workflow actions from technical intent alone. When a troubleshooting message contains completed validations and an observed outcome, preserve the full cardinality of the user report: identify every semantically distinct completed action and emit one attempted_action case update for each action. If one observed result applies to several completed actions, copy that result and its outcome to every corresponding attempted_action. This is mandatory even when the result is expressed after the actions in a separate clause or sentence. A persistent failure after completed actions is an observed unchanged result, not an unknown result. If the same report states that the issue was resolved, improved or worsened, apply that stated outcome instead. Never invent an outcome when the message gives no post-action result. If the actions cannot be separated responsibly, preserve them together as one compound attempted_action instead of omitting any action. Never collapse several confirmed actions into only the last action. For each attempted_action, value is the complete action, result is the observed result, and outcome is resolved, improved, unchanged, worsened or unknown. Execution of an action is not a successful outcome. If the failure continues, outcome is unchanged. When an active support case exists and a same-topic message reports a completed check plus the observed state, classify the turn as troubleshooting attempt_result and emit attempted_action with action, result and outcome; do not reduce the complete check to a generic observation. Map a reported affected population or quantity to affected_scope. Do not duplicate the same action in multiple case updates. Domain scope is strict: mark out_of_scope for independent requests that do not ask for technical support, operation, configuration, troubleshooting, documentation, assets, consumables or processes of the enterprise printing service. Do not treat a public figure, entertainment topic, general knowledge request, copyrighted-content request or other external subject as in scope merely because the message casually adds a printing verb. A bare or contrived association without a concrete technical object, symptom, operation or support goal remains out_of_scope. Out-of-scope turns must set should_retrieve false, needs_clarification false and requested_workflow none."""
REQUIRED={"requested_workflow","user_act","intent","topic_relation","domain_relevance","current_goal","goal_complete","goal_updates","case_updates","needs_clarification","clarification_target","should_retrieve","confidence","reasoning_summary"}
ALLOWED=set(REQUIRED)|{"canonical_subject","subject_origin","reference_relation"}
ALIASES={"clarification_needed":"needs_clarification","clarification_question":"clarification_target"}
SEMANTIC_FLAGS={"request_elaboration":"request_elaboration","answer_to_question":"answer_to_question","case_history":"case_history"}

def _semantic_text(value):
 """Normalize schema-like semantic text without leaking Python containers downstream."""
 if value is None:return ""
 if isinstance(value,str):return " ".join(value.split()).strip()
 if isinstance(value,(int,float,bool)):return str(value)
 if isinstance(value,list):return " ".join(x for x in (_semantic_text(item) for item in value) if x)
 if isinstance(value,dict):
  for key in ("summary","goal","current_goal","subject","operation","product","value","text","name"):
   text=_semantic_text(value.get(key))
   if text:return text
  return " ".join(x for x in (_semantic_text(item) for item in value.values()) if x)
 return " ".join(str(value).split()).strip()
class ConversationUnderstanding:
 def __init__(self,gateway,max_tokens=300):self.gateway=gateway;self.max_tokens=max(220,min(420,int(max_tokens)));self.last_provider_result={};self.contract_valid=False;self.validation_error=None;self.normalization={"removed_goal_update_keys":[]}
 def _degraded(self,memory,reason):return TurnUnderstanding("follow_up",memory.pending_goal.intent or "unknown","same_topic","uncertain",memory.pending_goal.summary or memory.active_topic or "",False,{},[],False,None,False,0.,reason,True)
 def _degraded_current(self,message,memory,reason):
  """Build a bounded semantic contract when the understanding provider is unavailable.

  The fallback is intentionally product-neutral. It distinguishes only request shape
  and whether the message can safely continue the pending assistant question. It never
  copies a previous subject into a self-contained new request and never treats the full
  message as a canonical subject.
  """
  text=" ".join(str(message or "").split()).strip();low=text.casefold()
  last_question=str(getattr(memory,"last_assistant_question",None) or "").strip()
  short_reply=bool(last_question and text and len(text.split())<=18)
  technical_shapes={
   "troubleshooting":("error","falla","fallo","incidencia","persiste","continua","continúa","no funciona","failed","failure","issue","still"),
   "requirements":("requisito","requisitos","compatibilidad","compatible","prerrequisito","condiciones previas","requirements","prerequisite"),
   "procedural":("como ","cómo ","procedimiento","instalar","configurar","asignar","actualizar","acceder","how ","install","configure","update"),
   "conceptual":("que es","qué es","explica","informacion","información","objetivo","funcion","función","what is","explain"),
  }
  detected=next((name for name,signals in technical_shapes.items() if any(signal in low for signal in signals)),None)
  if short_reply:
   intent=str(getattr(getattr(memory,"pending_goal",None),"intent",None) or "troubleshooting")
   if intent in {"","unknown"}:intent="troubleshooting"
   updates={"answer_to_question":text} if text else {}
   case_updates=[{"type":"observation","value":"Respuesta a la comprobación pendiente: "+text}] if text and intent=="troubleshooting" else []
   return TurnUnderstanding("answer_to_question",intent,"same_topic","in_scope",str(getattr(getattr(memory,"pending_goal",None),"summary",None) or getattr(memory,"active_topic",None) or text),False,updates,case_updates,False,None,True,0.45,"deterministic_degraded_contract:"+reason,True,getattr(memory,"active_subject",None),"conversation_memory","current_subject","none")
  if detected:
   return TurnUnderstanding("new_request",detected,"new_topic","in_scope",text,False,{},[],False,None,True,0.40,"deterministic_degraded_contract:"+reason,True,None,None,"none","none")
  return TurnUnderstanding("new_request","unknown","new_topic","uncertain",text,False,{},[],True,"relación con el servicio de impresión",False,0.20,"degraded_unresolved:"+reason,True,None,None,"none","none")
 def _parse(self,text):
  text=str(text or "").strip();a=text.find("{");b=text.rfind("}")
  if a<0 or b<a:raise ValueError("json_object_missing")
  raw=json.loads(text[a:b+1])
  if not isinstance(raw,dict) or not raw:raise ValueError("empty_object")
  aliases={}
  for src,dst in ALIASES.items():
   if dst not in raw and src in raw:raw[dst]=raw[src];aliases[src]=dst
  # Recover common provider schema drift before unknown fields are discarded.
  # These mappings are structural and product-agnostic; they never inspect user vocabulary.
  if "domain_relevance" not in raw and "out_of_scope" in raw:
   raw["domain_relevance"]="out_of_scope" if bool(raw.get("out_of_scope")) else "in_scope"
   aliases["out_of_scope"]="domain_relevance"
  if "user_act" not in raw:
   true_flags=[act for field,act in SEMANTIC_FLAGS.items() if raw.get(field) is True]
   case_updates=list(raw.get("case_updates") or []) if isinstance(raw.get("case_updates"),list) else []
   has_attempt_result=any(isinstance(item,dict) and str(item.get("type") or "")=="attempted_action" and (str(item.get("result") or "").strip() or str(item.get("outcome") or "").strip() in {"resolved","improved","unchanged","worsened"}) for item in case_updates)
   if has_attempt_result:
    raw["user_act"]="attempt_result";aliases["case_updates:attempt_result"]="user_act"
   elif true_flags:
    raw["user_act"]=true_flags[0];aliases[next(field for field,act in SEMANTIC_FLAGS.items() if act==true_flags[0])]="user_act"
   elif str(raw.get("reference_relation") or "none") in {"current_subject","previous_subject"}:
    raw["user_act"]="follow_up";aliases["reference_relation"]="user_act:follow_up"
  reference=str(raw.get("reference_relation") or "none")
  if "topic_relation" not in raw and reference in {"current_subject","previous_subject"}:
   raw["topic_relation"]="same_topic";aliases["reference_relation"]="topic_relation:same_topic"
  updates=raw.get("goal_updates")
  if isinstance(updates,list):
   facts=[str(x.get("fact") or x.get("value") or "").strip() for x in updates if isinstance(x,dict)]
   facts=[x for x in facts if x];raw["goal_updates"]={"subject":facts[0]} if facts else {}
   if facts and not raw.get("current_goal"):raw["current_goal"]=facts[0]
   aliases["goal_updates:list"]="goal_updates:dict"
  probe=" ".join((str(raw.get("current_goal") or ""),str(raw.get("goal_updates") or ""))).casefold()
  raw.setdefault("user_act","new_request");raw.setdefault("intent","conceptual" if any(x in probe for x in ("document","analiz","informacion","información")) else "procedural")
  reference=str(raw.get("reference_relation") or "none")
  raw.setdefault("topic_relation","same_topic" if reference in {"current_subject","previous_subject"} else "new_topic")
  raw.setdefault("domain_relevance","in_scope");raw.setdefault("current_goal",probe.strip() or "Atender la solicitud actual")
  raw.setdefault("canonical_subject",None);raw.setdefault("subject_origin",None);raw.setdefault("reference_relation","none");raw.setdefault("requested_workflow","none");raw.setdefault("goal_complete",False);raw.setdefault("goal_updates",{});raw.setdefault("case_updates",[]);raw.setdefault("needs_clarification",False);raw.setdefault("clarification_target",None);raw.setdefault("should_retrieve",True);raw.setdefault("confidence",0.75);raw.setdefault("reasoning_summary","provider_payload_normalized")
  missing=REQUIRED-set(raw)
  if missing:raise ValueError("missing_fields:"+",".join(sorted(missing)))
  for legacy in ALIASES:raw.pop(legacy,None)
  unknown=sorted(set(raw)-ALLOWED);clean={key:raw[key] for key in ALLOWED}
  # Some providers can return an object for a schema string even when the HTTP
  # call succeeds. Normalize at the contract boundary before reconcilers use it.
  for key in ("user_act","intent","topic_relation","domain_relevance","current_goal","clarification_target","reasoning_summary","canonical_subject","subject_origin","reference_relation","requested_workflow"):
   if key in clean and clean.get(key) is not None:clean[key]=_semantic_text(clean.get(key))
  clean["goal_updates"],removed=normalize_goal_updates(clean.get("goal_updates"))
  self.normalization={"removed_goal_update_keys":removed,"schema_aliases":aliases,"removed_unknown_fields":unknown,"contract_repaired":bool(aliases or unknown)}
  return TurnUnderstanding(**clean)
 def _normalize(self,x,memory,message=""):
  corrections=[]
  if x.user_act=="answer_to_question" and not memory.last_assistant_question:x.user_act="follow_up" if memory.active_topic else "new_request";corrections.append("answer_without_pending_question_normalized")
  if x.user_act=="request_elaboration":
   if not memory.active_topic and not memory.last_assistant_question:x.user_act="new_request";x.topic_relation="new_topic";corrections.append("orphan_elaboration_to_new_request")
   elif x.topic_relation=="new_topic":x.user_act="new_request";x.should_retrieve=True;corrections.append("provider_new_topic_preserved")
   else:x.topic_relation="same_topic";x.should_retrieve=True;corrections.append("referential_operational_retrieval_enforced")
  operational_case_types={"symptom","reported_failure","new_case","attempted_action","attempt_result","affected_scope"}
  case_types={str(item.get("type") or "") for item in (x.case_updates or []) if isinstance(item,dict)}
  if x.intent=="conceptual" and case_types.intersection(operational_case_types):
   x.intent="troubleshooting";x.should_retrieve=True;corrections.append("case_signal_promoted_operational_intent")
  if x.intent=="conceptual" and x.domain_relevance=="in_scope":x.needs_clarification=False;x.clarification_target=None;x.should_retrieve=True
  if x.intent=="case_history":
   x.should_retrieve=False;x.needs_clarification=False;x.clarification_target=None;x.requested_workflow="none";x.case_updates=[];x.goal_complete=True
   corrections.append("structured_case_history_non_retrieval_route")
  if x.needs_clarification and not str(x.clarification_target or "").strip():x.needs_clarification=False;corrections.append("empty_clarification_suppressed")
  if x.intent=="troubleshooting":
   # The semantic act attempt_result is authoritative: a completed action reported in
   # that turn cannot remain result_unknown. Recover a conservative shared result
   # without guessing a product, symptom or test phrase.
   if x.user_act=="attempt_result":
    recovered=0
    for item in x.case_updates or []:
     if not isinstance(item,dict) or str(item.get("type") or "")!="attempted_action":continue
     missing=not str(item.get("result") or "").strip()
     explicitly_unknown=bool(item.get("result_unknown"))
     if missing and explicitly_unknown:
      item["result"]="La incidencia persiste después de la acción reportada."
      item["outcome"]="unchanged"
      item.pop("result_unknown",None)
      recovered+=1
    if recovered:corrections.append("attempt_result_recovered_from_semantic_turn_role:"+str(recovered))
   present={str(a.get("type") or "") for a in x.case_updates}
   for key in ("symptom","observation","affected_scope","attempted_action","attempt_result"):
    value=str((x.goal_updates or {}).get(key) or "").strip()
    if value and key not in present:x.case_updates.append({"type":key,"value":value});corrections.append("goal_fact_promoted_to_case:"+key)
  if _can_normalize_terminal_social(message,x):
   inherited=bool(x.canonical_subject) and str(x.subject_origin or "").casefold()=="conversation_memory"
   x.user_act="social";x.intent="social";x.topic_relation="same_topic" if memory.active_topic else "new_topic";x.domain_relevance="in_scope";x.current_goal="Conversational social turn";x.goal_complete=True;x.goal_updates={};x.case_updates=[];x.needs_clarification=False;x.clarification_target=None;x.should_retrieve=False;x.canonical_subject=None;x.subject_origin=None;x.reference_relation="none";x.reasoning_summary="Terminal social turn";corrections.append("terminal_social_inherited_subject_cleared" if inherited else "terminal_social_contract_normalized")
  self.normalization.setdefault("structural_corrections",[]);self.normalization["structural_corrections"].extend(corrections);return x
 def interpret(self,message,memory):
  from app.llm_gateway.models import LLMRequest
  req=lambda payload,purpose:self.gateway.complete(LLMRequest([{"role":"system","content":SYSTEM},{"role":"user","content":json.dumps(payload,ensure_ascii=False,separators=(",",":"))}],purpose,self.max_tokens,0.,UNDERSTANDING_SCHEMA))
  r=req({"message":message,"context":compact_context(memory)},"agent_core_v2_clean_understanding");self.last_provider_result=r.to_dict();self.contract_valid=False;self.validation_error=None;self.normalization={"removed_goal_update_keys":[]}
  if not r.ok:self.validation_error="provider_error:"+str(r.error_code or "unknown");return self._degraded_current(message,memory,self.validation_error)
  try:x=self._parse(r.text);self.contract_valid=True;return self._normalize(x,memory,message)
  except Exception as exc:
   first_error=str(exc);retry=req({"message":message,"context":compact_context(memory),"invalid_output":str(r.text or "")[:4000],"validation_error":first_error,"instruction":"Return only a complete JSON object matching the schema without extra fields."},"agent_core_v2_clean_understanding_repair")
   self.last_provider_result={"initial":r.to_dict(),"repair":retry.to_dict(),"repair_attempted":True};self.normalization={"removed_goal_update_keys":[],"repair_attempted":True,"repair_succeeded":False}
   if retry.ok:
    try:x=self._parse(retry.text);self.contract_valid=True;self.validation_error=None;self.normalization["repair_attempted"]=True;self.normalization["repair_succeeded"]=True;return self._normalize(x,memory,message)
    except Exception as retry_exc:self.validation_error=str(retry_exc)
   else:self.validation_error="repair_provider_error:"+str(retry.error_code or "unknown")
   return self._degraded_current(message,memory,"invalid_understanding:"+str(self.validation_error or first_error))
