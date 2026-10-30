from .response_planner import build_response_plan,apply_plan
def plan_turn(result,message):
 p=build_response_plan(message,result.get('understanding') or {},result.get('retrieval') or {},result.get('evidence_decision') or {});result['canonical_response_plan']=p.to_dict();result['retrieval']=apply_plan(result.get('retrieval') or {},p);return result,p
def assessment_from_plan(plan,base=None):
 out=dict(base or {});base_decision=dict(out.get('canonical_decision') or {});unified_status=str(base_decision.get('status') or out.get('status') or 'insufficient');mode=plan.response_plan['mode'];plan_status=str(plan.evidence_plan.get('status') or 'insufficient')
 consistent=(unified_status==plan_status and ((unified_status=='sufficient' and mode=='documented') or (unified_status=='partial' and mode=='hybrid') or (unified_status=='insufficient' and mode in {'internal','clarification','general_guidance_with_example'})))
 reasons=list(dict.fromkeys(out.get('reasons') or []));
 if not consistent:reasons.append('authority_consistency_conflict')
 out.update({'status':unified_status,'generation_allowed':bool(out.get('generation_allowed')) and mode=='documented','internal_knowledge_candidate':mode!='documented','reasons':reasons,'coverage_basis':'unified_evidence_verdict','canonical_decision':base_decision,'authority_consistency':{'unified_status':unified_status,'sufficiency_status':str(out.get('status') or unified_status),'response_plan_status':plan_status,'response_mode':mode,'consistent':consistent}})
 return out
