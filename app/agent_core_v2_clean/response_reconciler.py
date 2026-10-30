from .semantic_contract import build_response_contract,validate_response_contract
from .budget_fallback import build_budget_fallback

def reconcile(result,memory):
 u=type("U",(),result.get("understanding") or {})();contract=build_response_contract(memory,u,result.get("retrieval") or {});validation=validate_response_contract((result.get("answer") or {}).get("text"),contract)
 result["response_contract"]=contract;result["response_reconciliation"]=validation
 if (result.get("answer") or {}).get("mode")=="natural_support" and str((result.get("answer") or {}).get("finish_reason") or "").casefold() in {"length","max_tokens"}:
  result.setdefault("functional_events",[]).append({"type":"truncated_natural_response_suppressed","severity":"high"})
  result["answer"]={"text":"La orientación quedó incompleta y no la publicaré de forma parcial. Retomaré la comprobación con evidencia documentada en el siguiente turno.","mode":"natural_length_guard","knowledge_used":False,"documented_evidence_used":False,"internal_knowledge_used":False,"knowledge_mode":"none"}
 if (result.get("answer") or {}).get("mode")=="retrieval_diagnostic":
  result["functional_events"]=[{"type":"diagnostic_text_suppressed","severity":"high"}]
  result["answer"]=build_budget_fallback(result.get("input"),memory,result=result,answer_context=result.get("answer_context") or {},budget_status=result.get("budget_status") or {})
 return result
