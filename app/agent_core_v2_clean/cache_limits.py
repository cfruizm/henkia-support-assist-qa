from __future__ import annotations

DEFAULT_LIMITS={
 "exact_turn_cache":8,
 "retrieval_cache":8,
 "documented_answer_cache":8,
 "procedural_answer_cache":6,
 "internal_knowledge_cache":6,
}

def _positive(value,default):
 try:return max(1,min(64,int(value)))
 except Exception:return default

def enforce_cache_limits(store,overrides=None):
 limits=dict(DEFAULT_LIMITS)
 for key,value in dict(overrides or {}).items():
  if key in limits:limits[key]=_positive(value,limits[key])
 evicted={}
 for name,limit in limits.items():
  cache=store.setdefault(name,{})
  removed=0
  while len(cache)>limit:
   cache.pop(next(iter(cache)));removed+=1
  if removed:evicted[name]=removed
 metrics=store.setdefault("cache_metrics",{})
 metrics["configured_limits"]=limits
 metrics["entries"]={name:len(store.get(name) or {}) for name in limits}
 metrics["evicted"]={**dict(metrics.get("evicted") or {}),**{k:int((metrics.get("evicted") or {}).get(k,0))+v for k,v in evicted.items()}}
 return {"limits":limits,"entries":metrics["entries"],"evicted_this_pass":evicted}
