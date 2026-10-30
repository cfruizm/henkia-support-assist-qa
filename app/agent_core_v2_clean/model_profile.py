from __future__ import annotations
from dataclasses import dataclass,asdict
@dataclass(frozen=True)
class ModelProfile:
 model:str;family:str="generic";understanding_mode:str="schema";schema_strict:bool=False;reasoning_effort:str|None=None;repair_once:bool=True;safe_output_tokens:int=620
 def to_dict(self):return asdict(self)
def profile_for(model):
 value=str(model or "").casefold()
 if "gpt-oss" in value:return ModelProfile(str(model or ""),"gpt_oss","text_json",False,"low",True,620)
 if "qwen" in value:return ModelProfile(str(model or ""),"qwen","schema",False,None,True,620)
 return ModelProfile(str(model or ""),"generic","schema",False,None,True,560)
def is_quota_error(result):
 if not result:return False
 data=result if isinstance(result,dict) else getattr(result,"to_dict",lambda:{})()
 text=" ".join(str(data.get(k) or "") for k in ("error_code","provider_error_code","error_message","message")).casefold()
 return "rate_limit" in text or "tokens per day" in text or "tpd" in text or "quota" in text


def resolve_model_name(config=None,secrets=None):
 for name in ("model","primary_model","model_name","default_model","groq_model","llm_model"):
  value=getattr(config,name,None) if config is not None else None
  if isinstance(value,str) and value.strip():return value.strip()
 if secrets is not None:
  for key in ("GROQ_MODEL","LLM_MODEL","MODEL_ID","model","groq_model"):
   try:value=secrets.get(key)
   except Exception:value=None
   if isinstance(value,str) and value.strip():return value.strip()
 return ""

def is_json_validation_error(result):
 if not result:return False
 data=result if isinstance(result,dict) else getattr(result,"to_dict",lambda:{})()
 metadata=data.get("metadata") or {}
 text=" ".join(str(x or "") for x in (data.get("error_code"),data.get("error_message"),metadata.get("provider_error_code"),metadata.get("response_format_mode"))).casefold()
 return "json_validate_failed" in text or "failed to validate json" in text or "failed to generate json" in text
