from __future__ import annotations
import re
from .case_context import norm

def assistant_request(text):
 value=norm(text); questions=list(re.finditer(r"¿[^?]{1,500}\?",value))
 if questions:return questions[-1].group(0).strip()
 for sentence in reversed(re.split(r"(?<=[.!])\s+",value)):
  if re.match(r"^(verifica|confirma|revisa|comprueba|indica|valida)\b",sentence,re.I):return sentence.strip()
 return None
def resolution_payload(message,memory):
 request=norm(getattr(memory,"last_assistant_question",None)); short=len(norm(message).split())<=8
 return {"resolved":bool(short and request),"source":"last_assistant_request" if short and request else None,"responding_to":request if short and request else None,"current_message":norm(message)}
