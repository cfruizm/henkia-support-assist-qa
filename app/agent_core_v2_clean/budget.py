from __future__ import annotations
from dataclasses import dataclass, asdict, replace
from app.llm_gateway.budget_config import load_budget_config

@dataclass(frozen=True)
class BudgetPolicy:
    mode:str="normal"
    max_session_calls:int=60
    max_session_tokens:int=52000
    reserve_tokens:int=2200
    understanding_max_tokens:int=350
    response_max_tokens:int=280
    @classmethod
    def for_mode(cls,mode:str):
        value=str(mode or "normal").strip().casefold()
        if value=="economy":return cls("economy",12,7000,900,180,120)
        if value=="deterministic":return cls("deterministic",0,0,0,0,0)
        return cls()
    @classmethod
    def from_runtime(cls,secrets_obj=None,environ=None,mode="normal"):
        base=cls.for_mode(mode)
        if base.mode!="normal":return base,{"mode":base.mode,"sources":{"max_session_tokens":"mode_policy","reserve_tokens":"mode_policy","max_session_calls":"mode_policy"},"keys":{},"invalid_values":[]}
        b=load_budget_config(secrets_obj)
        policy=replace(base,max_session_calls=b["max_session_calls"],max_session_tokens=b["max_session_tokens"],reserve_tokens=b["session_reserve_tokens"])
        return policy,{"mode":policy.mode,"sources":{"max_session_tokens":b["sources"]["max_session_tokens"],"reserve_tokens":b["sources"]["session_reserve_tokens"],"max_session_calls":b["sources"]["max_session_calls"]},"keys":{"max_session_tokens":b["keys"]["max_session_tokens"],"reserve_tokens":b["keys"]["session_reserve_tokens"],"max_session_calls":b["keys"]["max_session_calls"]},"invalid_values":b["invalid_values"]}
    def to_dict(self):return asdict(self)
    def status(self,telemetry,estimated_tokens:int=0):
        calls=int((telemetry or {}).get("calls",0));tokens=int((telemetry or {}).get("total_tokens",0));estimate=max(0,int(estimated_tokens or 0));usable=max(0,self.max_session_tokens-self.reserve_tokens);near=tokens>=int(usable*.85) if usable else True
        if self.mode=="deterministic":state,reason="deterministic","deterministic_mode"
        elif calls>=self.max_session_calls:state,reason="exhausted","session_call_budget_exhausted"
        elif tokens>=self.max_session_tokens:state,reason="exhausted","session_token_budget_exhausted"
        elif tokens+estimate>usable:state,reason="reserve_protected","session_token_budget_would_exceed_reserve"
        elif near:state,reason="near_limit",None
        else:state,reason="available",None
        return {"state":state,"reason":reason,"calls":calls,"tokens":tokens,"estimated_tokens":estimate,"max_session_calls":self.max_session_calls,"max_session_tokens":self.max_session_tokens,"reserve_tokens":self.reserve_tokens,"remaining_tokens":max(0,self.max_session_tokens-tokens),"usable_remaining_tokens":max(0,usable-tokens),"near_limit":near}
    def can_call(self,telemetry,estimated_tokens:int=0):
        status=self.status(telemetry,estimated_tokens);return status["state"] in {"available","near_limit"},status["reason"]
