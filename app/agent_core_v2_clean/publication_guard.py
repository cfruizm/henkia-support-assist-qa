from __future__ import annotations
import re
from .case_context import build_case_context,tokens,normalized
from .reference_resolution import assistant_request

def _overlap(a,b):
 x,y=tokens(a),tokens(b);return len(x&y)/max(1,min(len(x),len(y)))
def evaluate_publication(text,memory,answer_mode=""):
 c=build_case_context(memory);issues=[];request=assistant_request(text)
 if request:
  for value in c["observations"]+[str(x.get("value") or "") for x in c["confirmed_facts"]]:
   if value and _overlap(request,value)>=0.55:issues.append({"type":"repeated_confirmed_question","matched":value});break
 for attempt in c["attempts"]:
  action=attempt.get("action") or ""
  if action and _overlap(text,action)>=0.72 and not any(x in normalized(text) for x in ("de forma distinta","variante","diferente","porque","para distinguir")):
   issues.append({"type":"repeated_completed_action","matched":action});break
 return {"valid":not issues,"issues":issues,"answer_mode":answer_mode,"checked_observations":len(c["observations"]),"checked_attempts":len(c["attempts"])}
def enforce_publication(result,memory):
 answer=result.get("answer") or {};guard=evaluate_publication(answer.get("text"),memory,answer.get("mode"));result["publication_guard"]=guard
 if not guard["valid"]:
  result.setdefault("functional_events",[]).append({"type":"publication_guard_block","severity":"high","issues":guard["issues"]})
  answer.update({"text":"Con lo ya confirmado, no repetiré esa comprobación. El siguiente paso debe validar un componente aún no descartado y con impacto acorde al alcance del caso.","mode":"publication_guard_safe_fallback","knowledge_used":False,"documented_evidence_used":False,"internal_knowledge_used":False,"knowledge_mode":"none"})
 return result
