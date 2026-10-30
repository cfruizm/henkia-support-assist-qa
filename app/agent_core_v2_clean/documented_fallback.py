from __future__ import annotations
import re
from .source_footer import compact_sources

_VERIFY_MARKERS=("verifica","validar","confirma","comprobar","revisa","comprueba","verify","validate","confirm","check","review")
_REQUIREMENT_MARKERS=("requiere","requisito","compatible","compatibilidad","debe","necesita","requires","requirement","compatible","must","needs")
_HIGH_IMPACT=("elimina","eliminar","borra","borrar","desinstala","desinstalar","formatea","formatear","restablece","restablecer","disable","deshabilita","delete","remove","uninstall","format","reset")

def _clean(value):return " ".join(str(value or "").split()).strip()
def _sentences(value):return [x.strip() for x in re.split(r"(?<=[.!?])\s+|[•\n]+",_clean(value)) if len(x.strip())>=28]
def _safe(sentence):
 low=sentence.casefold()
 return not any(marker in low for marker in _HIGH_IMPACT) and len(sentence)<=420

def _candidate(evidence,intent):
 markers=_REQUIREMENT_MARKERS if intent=="requirements" else _VERIFY_MARKERS
 for item in evidence:
  for sentence in _sentences(item.get("text")):
   low=sentence.casefold()
   if _safe(sentence) and any(marker in low for marker in markers):
    return sentence,item
 return None,None

def build_documented_fallback(retrieval,reason="provider_degraded"):
 """Publish one conservative, cited fact when composition is unavailable.

 The fallback never invents a step, never combines fragments and rejects high-impact
 actions. If no safe complete sentence exists, it keeps the source reference without
 falsely classifying the documentation as insufficient.
 """
 retrieval=retrieval or {}
 evidence=list(retrieval.get("generation_evidence") or retrieval.get("evidence") or [])
 if not evidence:return None
 fields=(retrieval.get("query") or {}).get("fields") or {}
 intent=str(fields.get("intent") or "").casefold()
 sentence,item=_candidate(evidence,intent)
 if sentence and item and item.get("id"):
  if intent=="troubleshooting":
   text="La generación principal no estuvo disponible. Como comprobación documental de bajo impacto, revisa este punto antes de continuar:\n\n- "+sentence+f" [{item['id']}]"
  elif intent=="requirements":
   text="La generación principal no estuvo disponible. Este requisito sí está respaldado por la evidencia recuperada:\n\n- "+sentence+f" [{item['id']}]"
  else:
   text="La generación principal no estuvo disponible. Este punto documental puede publicarse de forma segura:\n\n- "+sentence+f" [{item['id']}]"
  cited=[str(item["id"])]
  mode="documented_degraded_minimal_answer"
 else:
  text="La generación principal no estuvo disponible. Encontré evidencia del tema actual, pero no una oración operativa completa de bajo riesgo que pueda publicar sin síntesis."
  cited=[str(x.get("id")) for x in evidence[:3] if x.get("id")]
  mode="documented_degraded_reference"
 footer=compact_sources(evidence,cited)
 if footer:text += "\n\n"+footer
 return {"text":text,"mode":mode,"knowledge_used":bool(sentence),"finish_reason":"deterministic_degraded","documented_evidence_used":bool(cited),"internal_knowledge_used":False,"knowledge_mode":"documented_only","degraded":True,"degraded_reason":str(reason or "provider_degraded"),"fallback_evidence_ids":cited}
