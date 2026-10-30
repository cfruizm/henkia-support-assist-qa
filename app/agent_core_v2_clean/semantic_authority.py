from __future__ import annotations
from dataclasses import dataclass,asdict
import re,unicodedata

def _norm(v):return unicodedata.normalize("NFKD",str(v or "")).encode("ascii","ignore").decode().casefold()
def _tokens(v):
 stop={"que","como","para","con","del","las","los","una","uno","esta","este","ese","esa","eso","por","the","and","with","from","this","that","into","sobre","explicar"}
 return {x for x in re.findall(r"[a-z0-9]+",_norm(v)) if len(x)>2 and x not in stop}
def _referential(message):
 t=_tokens(message); markers={"esa","ese","eso","esta","esto","diferencia","anterior","siguiente","donde","cuando","como","porque","that","this","it","previous","next"}
 raw=set(re.findall(r"[a-z0-9]+",_norm(message)));return bool(raw&markers) or len(t)<=5
@dataclass(frozen=True)
class AuthorityDecision:
 relation:str;material_goal_change:bool;continuation_override:bool;shared_ratio:float;previous_evidence_role:str;reason:str
 def to_dict(self):return asdict(self)
def reconcile_authority(previous_state,understanding,message):
 u=understanding or {};pending=(previous_state or {}).get("pending_goal") or {};old=pending.get("summary") or (previous_state or {}).get("active_topic") or "";new=u.get("current_goal") or message
 old_t,new_t=_tokens(old),_tokens(new);shared=len(old_t&new_t)/max(1,len(old_t|new_t))
 act=str(u.get("user_act") or "");declared=str(u.get("topic_relation") or "");intent=str(u.get("intent") or "")
 continuation=bool(old and ((declared=="same_topic" and (act!="new_request" or shared>=0.18)) or act in {"request_elaboration","answer_to_question","follow_up","attempt_result"} or (act not in {"new_request","topic_change","independent_question"} and _referential(message) and shared>0)))
 changed=bool(old and new and not continuation and shared<0.18 and len(new_t-old_t)>=2)
 if continuation:
  inheritable=bool(str(u.get("user_act") or "") in {"follow_up","answer_to_question","request_elaboration","attempt_result"} and str(u.get("subject_origin") or "") in {"conversation_memory","previous_subject","inherited","current_subject"})
  return AuthorityDecision("same_topic_refinement",False,u.get("domain_relevance")=="out_of_scope" and inheritable,round(shared,3),"primary","referential_or_declared_continuation")
 if changed or declared in {"new_topic","independent"}:return AuthorityDecision("new_topic",True,False,round(shared,3),"none","material_goal_change")
 return AuthorityDecision("same_topic",False,False,round(shared,3),"eligible","continuity_preserved")
def apply_authority(understanding,decision):
 if decision.continuation_override:understanding.domain_relevance="in_scope"
 understanding.topic_relation="new_topic" if decision.material_goal_change else "same_topic" if decision.relation.startswith("same_topic") else understanding.topic_relation
 return understanding
