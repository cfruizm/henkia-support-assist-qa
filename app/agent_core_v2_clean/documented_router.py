from __future__ import annotations
from copy import deepcopy
from .procedural_answer import ProceduralAnswerComposer,fingerprint as procedural_fingerprint,PROMPT_VERSION as PROCEDURAL_PROMPT_VERSION
from .evidence_sufficiency import assess_procedural_evidence
from .internal_knowledge import ControlledInternalKnowledgeComposer,fingerprint as internal_fingerprint,PROMPT_VERSION as INTERNAL_PROMPT_VERSION
from .topic_boundary import infer_topic_boundary,sanitize_new_topic_state
from .procedural_recovery import compact_documented_instruction,should_compact_retry,compact_retrieval_for_retry
from .evidence_boundary import enforce_evidence_boundary,normalize_citation_groups
from .conceptual_route import prepare_conceptual_retrieval,conceptual_assessment
from .procedural_scope import constrain_generic_procedure,scoped_assessment_override
from .response_plan_router import plan_turn,assessment_from_plan
from .citation_finalizer import enforce_answer_contract
from .state_scope import enrich_understanding
from .documented_fallback import build_documented_fallback
from .progressive_evidence import select_progressive_evidence

def _valid_cached(item):
 a=(item or {}).get('answer') or {};return a.get('mode') in {'procedural_documented_answer','procedural_documented_answer_partial','controlled_internal_knowledge','controlled_internal_knowledge_partial'}
def _get_cache(store,name,key):
 item=store.setdefault(name,{}).get(key)
 if item and not _valid_cached(item):store[name].pop(key,None);return None
 return item
def _flags(validation,valid):
 documented=bool((validation or {}).get('documented_citations'));return {'documented_evidence_used':documented,'internal_knowledge_used':valid,'knowledge_mode':'documented_plus_internal' if documented and valid else 'internal_only' if valid else 'none'}
def _boundary(result,store):
 before=result.get('state_before') or {};u=result.get('understanding') or {};b=infer_topic_boundary(before,u);result['topic_boundary']=b.to_dict()
 if b.relation=='new_topic':u['user_act']='new_request';u['topic_relation']='new_topic';sanitize_new_topic_state(store['memory'],u,before);result['understanding']=u;result['state_after']=deepcopy(store['memory'].to_dict())
 result['retrieval']=enforce_evidence_boundary(result.get('retrieval') or {},b.relation);return result

def _norm_terms(value):
 return {x for x in ''.join(ch if ch.isalnum() else ' ' for ch in str(value or '').casefold()).split() if len(x)>2}
def _authorize_requirement_context(retrieval,understanding,case_context):
 """Authorize subject-aligned diagnostic excerpts as factual context, never as a procedure."""
 r=deepcopy(retrieval or {})
 if r.get('generation_evidence'):return r
 subject=(case_context or {}).get('subject') or understanding.get('canonical_subject')
 subject_terms=_norm_terms(subject)
 if not subject_terms:return r
 selected=[]
 for row in list(r.get('diagnostic_evidence') or []):
  if subject_terms & _norm_terms((row or {}).get('title')):
   item=deepcopy(row);item['evidence_role']='documented_requirements_context';item['procedure_authorized']=False;selected.append(item)
  if len(selected)>=4:break
 if selected:
  r['requirements_context_candidates']=selected
  r['requirements_context_candidate_ids']=[x.get('id') for x in selected]
  r['requirements_context_authorized']=False
  r['requirements_context_authority']='diagnostic_only_unified_verdict_required'
 return r

def _generation_case_context(result,store):
 """Return only case state authorized for the current generation boundary.

 Historical case memory remains stored for audit and an explicit return-to-previous
 turn, but an effective new topic cannot receive symptoms, attempts, scope or facts
 from the prior case. This rule is semantic and independent of products or phrases.
 """
 u=result.get('understanding') or {}
 boundary=result.get('topic_boundary') or {}
 relation=str(boundary.get('relation') or u.get('topic_relation') or '').casefold()
 isolated=relation in {'new_topic','independent'}
 if isolated:
  return {'subject':None,'symptoms':[],'affected_scope':None,'observations':[],'attempts':[],'confirmed_facts':{},'case_context_authority':'isolated_current_topic'}
 memory=store['memory'];case=memory.support_case
 return {'subject':getattr(case,'subject',None) or memory.active_subject,'symptoms':deepcopy(getattr(case,'symptoms',[]) or []),'affected_scope':getattr(case,'affected_scope',None),'observations':deepcopy(getattr(case,'observations',[]) or []),'attempts':deepcopy(getattr(case,'attempts',[]) or []),'confirmed_facts':deepcopy(getattr(memory,'fact_records',{}) or {}),'case_context_authority':'active_same_topic'}

def _internal(result,message,gateway,budget,store,model,assessment):
 u=result.get('understanding') or {};r=result.get('retrieval') or {};r['_case_context']=_generation_case_context(result,store);r=_authorize_requirement_context(r,u,r['_case_context']);result['retrieval']=r;key=internal_fingerprint(message,u,r,assessment,model);cached=_get_cache(store,'internal_knowledge_cache',key)
 if cached:result['answer']=deepcopy(cached['answer']);result['internal_knowledge']={**deepcopy(cached['diagnostic']),'cache_hit':True};return result,{'skipped':True,'reason':'internal_knowledge_cache'}
 allowed,reason=budget.can_call(store['telemetry'],estimated_tokens=1800)
 if not allowed:return result,{'skipped':True,'reason':'internal_knowledge_budget_block','block_reason':reason}
 c=ControlledInternalKnowledgeComposer(gateway,520);a=c.compose(message,u,r,assessment);valid=a.mode in {'controlled_internal_knowledge','controlled_internal_knowledge_partial'};payload=a.to_dict();payload['text']=normalize_citation_groups(payload.get('text',''));payload.update(_flags(c.validation,valid));payload,audit=enforce_answer_contract(payload,result.get('canonical_response_plan'));result['answer']=payload;diag={'enabled':True,'cache_hit':False,'prompt_version':INTERNAL_PROMPT_VERSION,'trigger_status':assessment.get('status'),'trigger_reasons':assessment.get('reasons'),'validation':deepcopy(c.validation),'canonical_plan_used':True,'citation_audit':audit};result['internal_knowledge']=diag
 if valid:store['memory'].pending_goal.status='partially_answered' if a.mode.endswith('_partial') else 'needs_verification';result['state_after']=deepcopy(store['memory'].to_dict());store.setdefault('internal_knowledge_cache',{})[key]={'answer':deepcopy(payload),'diagnostic':deepcopy(diag)}
 return result,c.last_provider_result
def maybe_generate_procedural(result,message,gateway,budget,store,model=''):
 result=_boundary(result,store);result=enrich_understanding(result)
 if (result.get('decision') or {}).get('action') not in {'defer_to_retrieval','diagnose_with_retrieval'}:return result,{'skipped':True,'reason':'decision_does_not_authorize_retrieval'}
 u=result.get('understanding') or {};intent=u.get('intent');r=result.get('retrieval') or {}
 if intent=='conceptual':b=result.get('topic_boundary') or {'relation':u.get('topic_relation'),'changed_dimensions':[]};r=prepare_conceptual_retrieval(r,b,u);result['retrieval']=r;base=conceptual_assessment(r);result['evidence_decision']=base['canonical_decision']
 elif intent in {'procedural','requirements','troubleshooting'}:
  if intent=='procedural':r=constrain_generic_procedure(message,u,r);result['retrieval']=r
  base=assess_procedural_evidence(r,intent).to_dict();base=scoped_assessment_override(r,base);result['evidence_decision']=base.get('canonical_decision')
 else:return result,None
 result,plan=plan_turn(result,message);assessment=assessment_from_plan(plan,base);result['evidence_sufficiency']=assessment;mode=plan.response_plan['mode']
 if mode=='clarification' and plan.response_plan.get('must_ask_one_detail'):
  target=' '.join(str(plan.response_plan.get('question_target') or 'el dato que define el alcance').split()).strip().rstrip('.?:;')
  result['answer']={'text':f'Para orientarte con la documentación adecuada, necesito confirmar {target}. ¿Puedes indicarlo?','mode':'material_clarification','knowledge_used':False,'documented_evidence_used':False,'internal_knowledge_used':False,'knowledge_mode':'none','finish_reason':'deterministic'}
  result['documented_answer']={'enabled':False,'reason':'canonical_response_plan_requires_clarification','canonical_plan_used':True}
  result['internal_knowledge']={'enabled':False,'reason':'semantic_rejection_is_binding'}
  store['memory'].pending_goal.status='waiting_user';result['state_after']=deepcopy(store['memory'].to_dict())
  return result,{'skipped':True,'reason':'canonical_response_plan_material_clarification','calls_avoided':1}
 if mode!='documented':
  continuity=(result.get('document_continuity') or {})
  ctx=r.get('_answer_context') or {};prior=ctx.get('active_document_evidence_ledger') or ctx.get('cited_evidence') or []
  current=r.get('generation_evidence') or r.get('evidence') or []
  if continuity.get('primary') and (prior or current):
   assessment=dict(assessment or {})
   assessment['documentation_continuity_guard']={
    'active':True,'prior_evidence_count':len(prior),'current_evidence_count':len(current),
    'rule':'do_not_assert_global_absence_while_primary_document_evidence_exists'}
  return _internal(result,message,gateway,budget,store,model,assessment)
 r=result.get('retrieval') or {};r=select_progressive_evidence(r,u,maximum=4);result['retrieval']=r;key=procedural_fingerprint(message,u,r,model);cached=_get_cache(store,'procedural_answer_cache',key)
 if cached:result['answer']=deepcopy(cached['answer']);result['procedural_answer']={**deepcopy(cached['diagnostic']),'cache_hit':True};return result,{'skipped':True,'reason':'procedural_answer_cache'}
 allowed,reason=budget.can_call(store['telemetry'],estimated_tokens=2700)
 if not allowed:return result,{'skipped':True,'reason':'procedural_budget_block','block_reason':reason}
 c=ProceduralAnswerComposer(gateway,900);a=c.compose(message,u,r);attempts=[c.last_provider_result]
 if a.mode!='procedural_documented_answer_partial' and should_compact_retry(c.last_provider_result):compact=compact_retrieval_for_retry(r);a=c.compose(message+'\n\n'+compact_documented_instruction(),u,compact);attempts.append(c.last_provider_result);result['procedural_recovery']={'attempted':True,'mode':'ordered_full_stage_compaction','selection':compact.get('procedural_recovery_selection')}
 valid=a.mode in {'procedural_documented_answer','procedural_documented_answer_partial'} and (a.mode=='procedural_documented_answer_partial' or not should_compact_retry(c.last_provider_result));payload=a.to_dict();payload['text']=normalize_citation_groups(payload.get('text',''));payload.update({'documented_evidence_used':valid,'internal_knowledge_used':False,'knowledge_mode':'documented_only' if valid else 'none'});payload,audit=enforce_answer_contract(payload,result.get('canonical_response_plan'));result['answer']=payload;diag={'enabled':True,'cache_hit':False,'prompt_version':PROCEDURAL_PROMPT_VERSION,'assessment':assessment,'validation':deepcopy(c.validation),'retry_used':len(attempts)>1,'citation_audit':audit};result['procedural_answer']=diag
 if valid:store['memory'].pending_goal.status='complete';result['state_after']=deepcopy(store['memory'].to_dict());store.setdefault('procedural_answer_cache',{})[key]={'answer':deepcopy(payload),'diagnostic':deepcopy(diag)};return result,attempts if len(attempts)>1 else attempts[0]
 # When evidence is sufficient, a provider failure must not be mislabeled as insufficient documentation.
 last=attempts[-1] if attempts else {}
 fallback=build_documented_fallback(r,reason=str((last or {}).get('error_code') or (last or {}).get('finish_reason') or 'provider_degraded'))
 if fallback:
  fallback,audit=enforce_answer_contract(fallback,result.get('canonical_response_plan'));result['answer']=fallback
  result['procedural_answer']={**diag,'provider_degraded':True,'deterministic_fallback_used':True,'citation_audit':audit}
  store['memory'].pending_goal.status='complete';result['state_after']=deepcopy(store['memory'].to_dict())
  store.setdefault('procedural_answer_cache',{})[key]={'answer':deepcopy(fallback),'diagnostic':deepcopy(result['procedural_answer'])}
  return result,attempts if len(attempts)>1 else last
 return _internal(result,message,gateway,budget,store,model,assessment)
