from dataclasses import dataclass,asdict
@dataclass(frozen=True)
class ScopeBoundaryDecision:
 original_relevance:str;final_relevance:str;blocked_before_retrieval:bool;preserve_technical_state:bool;reason:str
 def to_dict(self):return asdict(self)
def reconcile_scope_boundary(u,memory):
 original=str(getattr(u,"domain_relevance","") or "uncertain").casefold();relation=str(getattr(u,"topic_relation","") or "").casefold();act=str(getattr(u,"user_act","") or "").casefold();intent=str(getattr(u,"intent","") or "").casefold();continuation=relation in {"same_topic","return_to_previous"} or act in {"follow_up","answer_to_question","request_elaboration","attempt_result","reported_failure"};blocked=original=="out_of_scope" or (original=="uncertain" and relation in {"new_topic","independent"} and act in {"new_request","independent_question","topic_change"} and intent not in {"social","cancel","escalation","meta","capabilities"} and not continuation)
 if blocked:u.domain_relevance="out_of_scope";u.should_retrieve=False;u.needs_clarification=False;u.clarification_target=None
 return u,ScopeBoundaryDecision(original,str(u.domain_relevance),blocked,blocked,"domain_boundary_pre_retrieval" if blocked else "provider_scope_preserved")
