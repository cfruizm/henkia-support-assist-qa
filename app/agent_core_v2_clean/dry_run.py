from .models import TurnUnderstanding
class DryRunUnderstanding:
 """Zero-LLM deterministic harness. It consumes explicit scenario outputs, never user phrases."""
 def __init__(self,outputs):self.outputs=list(outputs);self.index=0;self.last_provider_result={"skipped":True,"reason":"dry_run_zero_llm"}
 def interpret(self,message,memory):
  if self.index>=len(self.outputs):raise IndexError("dry-run scenario exhausted")
  raw=self.outputs[self.index];self.index+=1
  return raw if isinstance(raw,TurnUnderstanding) else TurnUnderstanding(**raw)
class DryRunResponse:
 def __init__(self):self.last_provider_result={"skipped":True,"reason":"dry_run_zero_llm"}
 def compose(self,message,memory,u,d):
  from .models import AgentResponse
  if d.action=="redirect_scope":text="Consulta fuera del alcance; se conserva el caso activo."
  elif d.action in {"defer_to_retrieval","diagnose_with_retrieval"}:text="Objetivo conservado y pendiente de recuperación documental."
  elif d.action=="diagnose":text=f"Caso en diagnóstico; siguiente dato: {d.question_target or 'siguiente evidencia'}"
  elif d.action=="ask_one_question":text=f"Aclaración requerida: {d.question_target}"
  else:text="Turno procesado en laboratorio determinista."
  return AgentResponse(text,"dry_run",False)
