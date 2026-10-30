from __future__ import annotations

def default_state():return {"state":"closed","consecutive_failures":0,"opened_at":None,"half_open_calls":0,"last_error_code":None}

def evaluate(state,now,cooldown_seconds,half_open_max_calls):
    current=dict(default_state());current.update(state or {})
    if current["state"]=="open":
        elapsed=max(0.0,float(now)-float(current.get("opened_at") or now))
        if elapsed>=float(cooldown_seconds):
            current.update({"state":"half_open","half_open_calls":0})
        else:return current,False,{"reason":"cooldown_active","remaining_seconds":max(0.0,float(cooldown_seconds)-elapsed)}
    if current["state"]=="half_open":
        if int(current.get("half_open_calls") or 0)>=int(half_open_max_calls):return current,False,{"reason":"half_open_probe_in_progress","remaining_seconds":0.0}
        current["half_open_calls"]=int(current.get("half_open_calls") or 0)+1
        return current,True,{"reason":"half_open_probe","remaining_seconds":0.0}
    return current,True,{"reason":"circuit_closed","remaining_seconds":0.0}

def success(state):
    out=default_state();out["last_transition_reason"]="primary_success";return out

def failure(state,now,threshold,error_code):
    out=dict(default_state());out.update(state or {});previous=out.get("state");count=int(out.get("consecutive_failures") or 0)+1
    if previous=="half_open" or count>=int(threshold):out.update({"state":"open","consecutive_failures":count,"opened_at":float(now),"half_open_calls":0,"last_error_code":error_code,"last_transition_reason":"failure_threshold_reached" if previous!="half_open" else "half_open_probe_failed"})
    else:out.update({"state":"closed","consecutive_failures":count,"last_error_code":error_code,"last_transition_reason":"recoverable_primary_failure"})
    return out
