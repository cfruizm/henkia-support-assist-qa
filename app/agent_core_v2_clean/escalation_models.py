from __future__ import annotations
from dataclasses import dataclass,field,asdict
from typing import Any
@dataclass
class EscalationValue:
 value:Any=None;source:str='unknown';status:str='unknown';turn:int=0
 def to_dict(self):return asdict(self)
@dataclass
class EscalationState:
 status:str='inactive';pending_field:str|None=None;fields:dict[str,dict[str,Any]]=field(default_factory=dict);unknown_fields:list[str]=field(default_factory=list);corrections:list[dict[str,Any]]=field(default_factory=list);sources_consulted:list[dict[str,Any]]=field(default_factory=list);escalation_reason:dict[str,Any]=field(default_factory=dict);suspended_reason:str|None=None;suspended_pending_field:str|None=None;correction_stage:str|None=None;correction_field:str|None=None;confirmed:bool=False;exported:bool=False;completion_reason:str|None=None;started_turn:int|None=None;completed_turn:int|None=None
 def to_dict(self):return asdict(self)
