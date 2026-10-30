def finalize_published_goal(result,memory):
 u=result.get("understanding") or {};a=result.get("answer") or {};finish=str(a.get("finish_reason") or "").casefold()
 complete=u.get("intent")=="conceptual" and bool(str(a.get("text") or "").strip()) and not a.get("partial") and finish not in {"length","max_tokens"} and not u.get("needs_clarification")
 if complete: memory.pending_goal.status="complete";memory.pending_goal.missing_detail=None;u["goal_complete"]=True
 result["conceptual_completion"]={"applied":complete,"finish_complete":bool(a.get("text")) and finish not in {"length","max_tokens"}}
 result["state_after"]=memory.to_dict();return result
