from __future__ import annotations

def facts_from_memory(memory):
 records=getattr(memory,"fact_records",{}) or {}
 if records:return [dict(v) for v in records.values() if isinstance(v,dict) and v.get("status")=="confirmed"]
 return [{"key":str(k),"value":str(v),"origin":"legacy_memory","status":"confirmed","turn":getattr(memory,"turn_number",0)} for k,v in (getattr(memory.pending_goal,"known_details",{}) or {}).items() if str(v).strip()]
def build_response_contract(memory,understanding,retrieval=None):
 confirmed=facts_from_memory(memory);known={x.get("key") for x in confirmed};target=getattr(understanding,"clarification_target",None);missing=[target] if target and target not in known else []
 return {"confirmed_facts":confirmed,"unresolved_facts":missing,"request_scope":getattr(understanding,"request_scope",None) or {},"evidence_scope":(retrieval or {}).get("evidence_scope") or {}}
def validate_response_contract(text,contract):
 value=" ".join(str(text or "").split()).casefold();issues=[]
 denial_markers=("no se ha confirmado","sin confirmar","falta confirmar","not confirmed","has not been confirmed")
 for fact in contract.get("confirmed_facts") or []:
  key=str(fact.get("key") or "").casefold().strip(); fact_value=str(fact.get("value") or "").casefold().strip()
  anchors=[x for x in (key,fact_value) if len(x)>=3]
  contradiction=False
  for sentence in __import__("re").split(r"(?<=[.!?;])\s+", value):
   if any(marker in sentence for marker in denial_markers) and anchors and any(anchor in sentence for anchor in anchors):
    contradiction=True;break
  if contradiction:issues.append({"type":"confirmed_fact_contradiction","key":fact.get("key"),"value":fact.get("value"),"evidence":"local_denial_window"})
 return {"valid":not issues,"issues":issues,"confirmed_fact_count":len(contract.get("confirmed_facts") or []),"unresolved_fact_count":len(contract.get("unresolved_facts") or [])}
