from __future__ import annotations
from dataclasses import dataclass,asdict
from copy import deepcopy
from .entity_scope import normalize_scope
from .citation_registry import register_evidence
from .response_coverage import response_shape
@dataclass(frozen=True)
class ResponsePlan:
 schema_version:int;request:dict;evidence_plan:dict;response_plan:dict
 def to_dict(self):return asdict(self)
def build_response_plan(message,u,retrieval,decision=None):
 u=u or {};retrieval=retrieval or {};details=u.get('goal_updates') or {};scope=normalize_scope(details);intent=str(u.get('intent') or 'unknown');guard=retrieval.get('procedural_scope_guard') or {};verdict=retrieval.get('evidence_verdict') or {};semantic=retrieval.get('semantic_fit') or {};diagnostic=list(retrieval.get('diagnostic_evidence') or [])
 semantic_rejected=bool(semantic.get('low_fit')) and not bool(semantic.get('accepted_for_generation'));specific_rejected_candidate=semantic_rejected and bool(diagnostic) and any(bool((x.get('semantic_fit') or {}).get('unconfirmed_title_terms')) or float((x.get('semantic_fit') or {}).get('assumption_penalty',0) or 0)>0 for x in diagnostic)
 case_updates=list(u.get('case_updates') or []);confirmed_scope_available=any(str(x.get('type') or '')=='affected_scope' and str(x.get('value') or '').strip() for x in case_updates);current_turn_resolves_pending_detail=(str(u.get('user_act') or '')=='answer_to_question' and not bool(u.get('needs_clarification'))) or (confirmed_scope_available and not bool(u.get('needs_clarification')));explicit_clarification_needed=bool(u.get('needs_clarification')) and bool(str(u.get('clarification_target') or '').strip());variant_unconfirmed=specific_rejected_candidate and explicit_clarification_needed and not current_turn_resolves_pending_detail
 missing=[]
 if variant_unconfirmed:missing.append('la modalidad o variante aplicable')
 if intent=='procedural' and not verdict.get('accepted') and not guard.get('direct_procedure_match_count'):
  if scope.manufacturer and not scope.model:missing.append('model')
  if scope.product and scope.architecture and not scope.operating_system:missing.append('operating_system')
 verdict_status=str(verdict.get('status') or 'insufficient');verdict_mode=str(verdict.get('mode') or verdict.get('generation_mode') or 'internal_only');selected_evidence=list(verdict.get('selected_evidence') or [])
 sufficient=verdict_status=='sufficient' and bool(verdict.get('accepted')) and bool(selected_evidence)
 partial_authorized=verdict_status=='partial' and verdict_mode in {'documented_plus_internal','documented_partial','hybrid'} and bool(selected_evidence)
 documented=sufficient or partial_authorized
 evidence=selected_evidence if documented else []
 example=bool(selected_evidence) and bool(guard.get('restricted_to_example')) and not documented
 registered,mapping=register_evidence(evidence);mode='clarification' if variant_unconfirmed else 'documented' if sufficient else 'hybrid' if partial_authorized else 'general_guidance_with_example' if example else 'internal'
 request={'intent':intent,'response_shape':response_shape(intent),'operation':details.get('operation') or u.get('current_goal') or '','subject':details.get('subject') or u.get('current_goal') or '','scope':scope.to_dict(),'missing_material_details':missing,'message':message}
 ep={'status':verdict_status,'mode':mode,'documented_ids':[x['id'] for x in registered],'example_ids':[str(x.get('id')) for x in selected_evidence[:1]] if example else [],'citation_map':mapping,'citation_namespace':'canonical','selected_evidence':registered,'rejected':{'scope_mismatch':[str(x.get('id')) for x in selected_evidence] if example else [],'carried_context':[],'duplicate':[]}}
 rp={'mode':mode,'must_answer_general':not documented and mode!='clarification','must_ask_one_detail':bool(missing),'question_target':missing[0] if missing else None,'allow_documented_claims':documented,'allow_internal_guidance':(not sufficient) and mode!='clarification','allow_example_claims':example,'complete_goal':sufficient and not missing,'authority_reason':str(verdict.get('reason') or 'unified_evidence_verdict_missing'),'authority_source':'unified_evidence_verdict'}
 return ResponsePlan(5,request,ep,rp)
def apply_plan(retrieval,plan):
 out=deepcopy(retrieval or {});out['response_plan']=plan.to_dict();mode=plan.response_plan['mode']
 if mode in {'documented','hybrid'}:out['generation_evidence']=deepcopy(plan.evidence_plan['selected_evidence']);out['evidence']=deepcopy(plan.evidence_plan['selected_evidence'])
 else:out['generation_evidence']=[];out['evidence']=[];out['_answer_context']={}
 return out
