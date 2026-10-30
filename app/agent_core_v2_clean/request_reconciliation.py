from __future__ import annotations
import re,unicodedata
_CORRECTION=("me refiero","queria decir","quise decir","documento correcto","fuente correcta","especificamente","en realidad")
_NEGATIVE=re.compile(r"\b(?:no quiero (?:usar|utilizar)|sin utilizar|sin usar|no utilizar|no usar|que no sea|no mediante|excepto|sin)\s+(.+?)(?:[.,;!?]|$)",re.I)
def norm(v):return unicodedata.normalize("NFKD",str(v or "")).encode("ascii","ignore").decode().casefold().strip()
def reconcile(message,understanding,state_before):
 u=dict(understanding or {});old=str(((state_before or {}).get("pending_goal") or {}).get("summary") or "");text=norm(message);correction=any(x in text for x in _CORRECTION);subject=str(u.get("canonical_subject") or (u.get("goal_updates") or {}).get("subject") or "")
 if correction and old and subject:u["current_goal"]=old+". Usar fuente corregida: "+subject;u["topic_relation"]="same_topic";u["reference_relation"]="corrected_subject"
 constraints=[" ".join(x.strip().split()) for x in _NEGATIVE.findall(str(message or "")) if x.strip()]
 if constraints:u["negative_constraints"]=constraints;u["current_goal"]=(str(u.get("current_goal") or old or message)+". Excluir: "+"; ".join(constraints));u["topic_relation"]="same_topic";u["reference_relation"]="negative_constraint"
 return u,{"correction_detected":correction,"preserved_previous_operation":bool(correction and old),"negative_constraints":constraints}
def filter_excluded(items,constraints):
 kept=[];rejected=[]
 for item in items or []:
  hay=norm(" ".join(str(x or "") for x in (item.get("title"),item.get("source"),item.get("url"))))
  (rejected if any(norm(c) in hay for c in constraints) else kept).append(item)
 return kept,rejected
