from __future__ import annotations
from copy import deepcopy

def consolidated_details(result:dict)->dict:
 state=(result.get('state_after') or {}).get('pending_goal') or {}
 known=deepcopy(state.get('known_details') or {})
 updates=deepcopy((result.get('understanding') or {}).get('goal_updates') or {})
 known.update({k:v for k,v in updates.items() if v not in (None,'',[],{})})
 return known

def enrich_understanding(result:dict)->dict:
 u=deepcopy(result.get('understanding') or {})
 u['goal_updates']=consolidated_details(result)
 result['understanding']=u
 result['canonical_scope_input']={'source':'state_after_plus_goal_updates','details':deepcopy(u['goal_updates'])}
 return result
