from __future__ import annotations
import re,unicodedata
from .escalation_contract import ALIASES

def _norm(value):
 return " ".join(unicodedata.normalize("NFKD",str(value or "")).encode("ascii","ignore").decode().casefold().split())

def _explicit_escalation_goal(u):
 if str(getattr(u,"requested_workflow","none") or "none")=="start_escalation":return True
 if str(getattr(u,"intent","") or "").casefold()=="escalation" or str(getattr(u,"user_act","") or "").casefold()=="escalation":return True
 goal=_norm(getattr(u,"current_goal",None))
 # Generic lifecycle vocabulary only. Product, customer, symptom and campaign values
 # are deliberately absent from this reconciliation.
 return bool(re.search(r"\b(?:escalar|escalamiento|escalacion|transferir|remitir)\b",goal))

def _field_key(label):
 label=_norm(label).strip(" .,:;-")
 if label in ALIASES:return ALIASES[label]
 compact=label.replace(" ","_")
 if compact in {"client_contract_location","impact_scope","device_data","issue_description","troubleshooting_performed","software_version","evidence","product_or_service"}:return compact
 if label in {"serial","serie","numero de serie","serial number"}:return "device_serial"
 if label in {"resultado","result","outcome"}:return "attempt_result_shared"
 return None

def _attach_shared_attempt_result(u,shared_result):
 diagnostic={"shared_result":shared_result or None,"actions_updated":0,"preserved_individual_results":0}
 if not shared_result:return diagnostic
 rows=[]
 for item in list(getattr(u,"case_updates",[]) or []):
  row=dict(item or {})
  if str(row.get("type") or "").casefold()=="attempted_action":
   current=str(row.get("result") or "").strip()
   if current:diagnostic["preserved_individual_results"]+=1
   else:
    row["result"]=shared_result;row.pop("result_unknown_reason",None)
    row["outcome"]=str(row.get("outcome") or "unknown")
    diagnostic["actions_updated"]+=1
  rows.append(row)
 u.case_updates=rows
 return diagnostic

def reconcile_escalation_intake(message,u):
 diagnostic={"applied":False,"workflow_promoted":False,"captured_fields":[]}
 if not _explicit_escalation_goal(u):return u,diagnostic
 if str(getattr(u,"requested_workflow","none") or "none")!="start_escalation":
  u.requested_workflow="start_escalation";diagnostic["workflow_promoted"]=True
 u.intent="escalation";u.user_act="escalation";u.should_retrieve=False;u.needs_clarification=False;u.clarification_target=None
 updates=dict(getattr(u,"goal_updates",{}) or {})
 device_values=[]
 for raw in str(message or "").splitlines():
  match=re.match(r"^\s*([^:]{2,80})\s*:\s*(.+?)\s*$",raw)
  if not match:continue
  key=_field_key(match.group(1));value=" ".join(match.group(2).split()).strip()
  if not key or not value:continue
  if key in {"device_data","device_serial"}:device_values.append(value)
  elif key=="attempt_result_shared":updates[key]=value
  else:updates[key]=value
  diagnostic["captured_fields"].append(key)
 if device_values:updates["device_data"]=" ".join(dict.fromkeys(device_values))
 shared_result=str(updates.get("attempt_result_shared") or "").strip()
 attempt_result_binding=_attach_shared_attempt_result(u,shared_result)
 u.goal_updates=updates;diagnostic["applied"]=True;diagnostic["captured_fields"]=list(dict.fromkeys(diagnostic["captured_fields"]))
 diagnostic["attempt_result_binding"]=attempt_result_binding
 return u,diagnostic
