from __future__ import annotations
from dataclasses import dataclass,field,asdict
from typing import Any
from .escalation_models import EscalationState
@dataclass
class PendingGoal:
 summary:str="";intent:str="unknown";known_details:dict[str,str]=field(default_factory=dict);missing_detail:str|None=None;status:str="inactive"
 def is_open(self):return self.status in {"active","waiting_user","partially_answered","blocked_by_evidence"}
@dataclass
class SupportCase:
 status:str="idle";subject:str|None=None;symptoms:list[str]=field(default_factory=list);observations:list[str]=field(default_factory=list);attempts:list[dict[str,Any]]=field(default_factory=list);affected_scope:str|None=None;resolution_status:str|None=None
@dataclass
class ConversationMemory:
 conversation_id:str="v2-clean-lab";active_topic:str|None=None;pending_goal:PendingGoal=field(default_factory=PendingGoal);support_case:SupportCase=field(default_factory=SupportCase);escalation:EscalationState=field(default_factory=EscalationState);last_assistant_question:str|None=None;summary:str="";turn_number:int=0;topic_history:list[dict[str,Any]]=field(default_factory=list);fact_records:dict[str,dict[str,Any]]=field(default_factory=dict);active_subject:str|None=None;subject_history:list[dict[str,Any]]=field(default_factory=list)
 def to_dict(self):return asdict(self)
@dataclass
class TurnUnderstanding:
 user_act:str;intent:str;topic_relation:str;domain_relevance:str;current_goal:str;goal_complete:bool;goal_updates:dict[str,str]=field(default_factory=dict);case_updates:list[dict[str,str]]=field(default_factory=list);needs_clarification:bool=False;clarification_target:str|None=None;should_retrieve:bool=False;confidence:float=0.;reasoning_summary:str="";degraded:bool=False;canonical_subject:str|None=None;subject_origin:str|None=None;reference_relation:str="none";requested_workflow:str="none"
 def to_dict(self):return asdict(self)
@dataclass
class AgentDecision:
 action:str;reason:str;ask_one_question:bool=False;question_target:str|None=None
 def to_dict(self):return asdict(self)
@dataclass
class AgentResponse:
 text:str;mode:str;knowledge_used:bool=False;provider:str|None=None;model:str|None=None;usage:dict[str,int]=field(default_factory=dict);finish_reason:str|None=None
 def to_dict(self):return asdict(self)
