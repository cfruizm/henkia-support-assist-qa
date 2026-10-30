import json
from .models import AgentResponse
from .memory import compact_context
SYSTEM="""Natural enterprise printing-support colleague. Use the user's language. Help first. Answer immediately when sufficiently clear. Ask exactly one short targeted question only when one missing fact is indispensable and materially changes the answer. If asking, do not include examples, technology lists, checklists, speculative mechanisms or a second question. Add at most one short sentence explaining why the answer matters. Retrieval is disabled here: never provide exact menus, service names, commands, paths, values or product procedures. Diagnostic hypotheses are possibilities, never confirmed causes or exclusions unless the user supplied confirming evidence. Concise."""
def _case_history_response(memory, answer_context):
 case=getattr(memory,"support_case",None)
 symptoms=[" ".join(str(x or "").split()).strip() for x in list(getattr(case,"symptoms",[]) or []) if str(x or "").strip()]
 observations=[" ".join(str(x or "").split()).strip() for x in list(getattr(case,"observations",[]) or []) if str(x or "").strip()]
 attempts=[]
 for item in list(getattr(getattr(memory,"support_case",None),"attempts",[]) or []):
  action=" ".join(str((item or {}).get("action") or "").split()).strip()
  if not action:continue
  result=" ".join(str((item or {}).get("result") or "").split()).strip()
  outcome=" ".join(str((item or {}).get("outcome") or "unknown").split()).strip()
  attempts.append({"action":action,"result":result or None,"outcome":outcome})
 guidance=[];seen_keys=set();seen_text=set()
 for item in list((answer_context or {}).get("delivered_guidance") or []):
  action=" ".join(str((item or {}).get("action") or "").split()).strip();key=" ".join(str((item or {}).get("check_key") or "").split()).strip().casefold();signature=action.casefold()
  identity=key or signature
  if not action or identity in seen_keys or signature in seen_text:continue
  seen_keys.add(identity);seen_text.add(signature);guidance.append(action)
 labels={"resolved":"Resuelto","improved":"Mejoró","unchanged":"Sin cambios","worsened":"Empeoró"}
 lines=["**Hechos confirmados por el usuario**"]
 if symptoms or observations:
  for value in symptoms:lines.append(f"- Síntoma reportado: {value}")
  for value in observations:lines.append(f"- Observación confirmada: {value}")
 else:lines.append("No hay síntomas u observaciones confirmados en el caso activo.")
 lines.extend(["","**Acciones registradas como realizadas**"])
 if attempts:
  for index,item in enumerate(attempts,1):
   detail=f"{index}. {item['action']}"
   if item.get("result"):detail+=f". Resultado: {item['result']}"
   if item.get("outcome") in labels:detail+=f". Estado: {labels[item['outcome']]}"
   lines.append(detail)
 else:lines.append("No hay acciones confirmadas como realizadas.")
 lines.extend(["","**Orientaciones sugeridas, no confirmadas como ejecutadas**"])
 if guidance:lines.extend(f"{index}. {action}" for index,action in enumerate(guidance,1))
 else:lines.append("No hay orientaciones previas registradas como sugeridas.")
 hypotheses=[];seen_h=set()
 for item in list((answer_context or {}).get("documented_hypotheses") or []):
  key=" ".join(str((item or {}).get("hypothesis_key") or "").split()).strip().casefold();summary=" ".join(str((item or {}).get("summary") or "").split()).strip();conditions=[" ".join(str(x or "").split()).strip() for x in (item or {}).get("required_conditions") or [] if str(x or "").strip()]
  identity=key or summary.casefold()
  if summary and identity not in seen_h:seen_h.add(identity);hypotheses.append((summary,conditions))
 lines.extend(["","**Hipótesis documentales no confirmadas**"])
 if hypotheses:
  for index,(summary,conditions) in enumerate(hypotheses,1):
   detail=f"{index}. {summary}"
   if conditions:detail+=" Condiciones pendientes: "+"; ".join(conditions)+"."
   lines.append(detail)
 else:lines.append("No hay hipótesis estructuradas registradas.")
 return "\n".join(lines)

class NaturalResponseComposer:
 def __init__(self,gateway,max_tokens=220,answer_context_provider=None):
  self.gateway=gateway;self.max_tokens=max(120,min(300,int(max_tokens)));self.last_provider_result={};self.answer_context_provider=answer_context_provider
 def _current_answer_context(self):
  try:
   value=self.answer_context_provider() if callable(self.answer_context_provider) else self.answer_context_provider
   return dict(value or {})
  except Exception:return {}
 def compose(self,message,m,u,d):
  intent=str(u.intent or "").casefold();act=str(u.user_act or "").casefold()
  if intent=="case_history":
   self.last_provider_result={"skipped":True,"reason":"case_history_uses_structured_conversation_state"}
   return AgentResponse(_case_history_response(m,self._current_answer_context()),"deterministic_case_history",False,None,None,{},"deterministic")
  if intent=="social" or act=="social":
   # The semantic contract already identified a social turn. Keep the response terminal,
   # concise and language-neutral without inspecting literal words or calling another LLM.
   self.last_provider_result={"skipped":True,"reason":"social_turn_uses_deterministic_terminal_response"}
   return AgentResponse("Estoy aquí para ayudarte. ¿Qué necesitas revisar?","deterministic_social",False,None,None,{},"deterministic")
  if intent in {"meta","capabilities"} or act=="request_capabilities":return AgentResponse("Puedo explicar conceptos, consultar documentación, orientar procedimientos, apoyar diagnóstico de fallas y preparar información para escalamiento dentro del servicio de impresión.","capabilities")
  if d.action=="redirect_scope":return AgentResponse("Esta consulta está fuera del alcance del asistente, que está orientado al soporte técnico y a los procesos del servicio de impresión. Si necesitas ayuda dentro de ese ámbito, describe el equipo, servicio, síntoma o actividad que deseas revisar.","out_of_scope_closed")
  if d.action=="cancel":m.pending_goal.status="inactive";return AgentResponse("Listo, cancelé el flujo actual. ¿Qué necesitas revisar ahora?","cancelled")
  if d.action=="degraded_continue":return AgentResponse("No pude interpretar este turno de forma confiable. Conservé el estado anterior sin aplicar cambios.","provider_degraded")
  if d.action in {"defer_to_retrieval","diagnose_with_retrieval"}:return AgentResponse("La solicitud quedó lista para contrastarla con la documentación.","retrieval_pending")
  if d.action=="ask_one_question":
   target=" ".join(str(d.question_target or "el dato que define el alcance").split()).strip().rstrip(".?:;")
   self.last_provider_result={"skipped":True,"reason":"material_clarification_uses_understanding_contract","calls_avoided":1}
   return AgentResponse(f"Para orientarte con la documentación adecuada, necesito confirmar {target}. ¿Puedes indicarlo?","material_clarification",False,None,None,{},"deterministic")
  from app.llm_gateway.models import LLMRequest
  r=self.gateway.complete(LLMRequest([{"role":"system","content":SYSTEM},{"role":"user","content":json.dumps({"message":message,"memory":compact_context(m),"understanding":u.to_dict(),"decision":d.to_dict()},ensure_ascii=False,separators=(",",":"))}],"agent_core_v2_clean_response",min(self.max_tokens,150),0.,None));self.last_provider_result=r.to_dict()
  if not r.ok:return AgentResponse("Conservé el contexto, pero no pude generar la siguiente orientación.","provider_degraded")
  return AgentResponse(r.text.strip(),"natural_support",d.action in {"answer","diagnose"},r.provider,r.model,r.usage,r.finish_reason)
