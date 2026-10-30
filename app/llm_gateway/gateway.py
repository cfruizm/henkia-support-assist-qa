from __future__ import annotations
from app.llm_gateway.config import model_for
from app.llm_gateway.errors import LLMGatewayError
from app.llm_gateway.models import LLMResult
from app.llm_gateway.circuit_breaker import default_state, evaluate as evaluate_circuit, success as circuit_success, failure as circuit_failure
import time
import random
from app.llm_gateway.providers.groq_provider import GroqProvider
from app.llm_gateway.providers.huggingface_provider import HuggingFaceProvider

SESSION_KEYS=("llm_gateway_calls","llm_gateway_tokens","llm_gateway_history","llm_gateway_output_ledger","llm_gateway_budget_diagnostic","llm_gateway_circuit_breakers")

def reset_gateway_session(session_state):
    if session_state is None:return
    for key in SESSION_KEYS:session_state.pop(key,None)

class LLMGateway:
    def __init__(self,config,session_state=None):self.config=config;self.session=session_state
    def _provider(self,name,inference_route=None):
        cfg=self.config["providers"][name]
        if name=="groq":return GroqProvider(cfg["api_key"],cfg["base_url"],cfg["structured_mode"])
        if name=="huggingface":
            route=inference_route or cfg.get("primary_provider")
            return HuggingFaceProvider(cfg["token"],route,cfg.get("bill_to"),cfg.get("disable_thinking",True),cfg.get("timeout_seconds",75),cfg.get("structured_mode","json_schema"))
        raise LLMGatewayError("unsupported_provider",f"Proveedor no soportado: {name}")
    def _budget_snapshot(self,request=None):
        calls=int((self.session or {}).get("llm_gateway_calls",0));tokens=int((self.session or {}).get("llm_gateway_tokens",0))
        requested=max(0,int(getattr(request,"max_tokens",0) or 0))
        maximum=int(self.config["max_total_tokens_per_session"]);reserve=int(self.config.get("session_reserve_tokens",0));usable=max(0,maximum-reserve)
        if calls>=int(self.config["max_calls_per_session"]):state,reason="exhausted","session_call_budget_exhausted"
        elif tokens>=maximum:state,reason="exhausted","session_token_budget_exhausted"
        elif tokens+requested>usable:state,reason="reserve_protected","session_token_budget_would_exceed_reserve"
        elif tokens>=int(usable*0.85):state,reason="near_limit",None
        else:state,reason="available",None
        return {"state":state,"reason":reason,"calls":calls,"tokens":tokens,"requested_output_tokens":requested,"projected_minimum_tokens":tokens+requested,"max_session_calls":int(self.config["max_calls_per_session"]),"max_session_tokens":maximum,"reserve_tokens":reserve,"usable_session_tokens":usable,"remaining_tokens":max(0,maximum-tokens),"source":dict(self.config.get("budget_configuration") or {})}
    def _budget(self,request=None):
        if self.session is None:return
        snapshot=self._budget_snapshot(request);self.session["llm_gateway_budget_diagnostic"]=snapshot
        if snapshot["reason"]:
            exc=LLMGatewayError(snapshot["reason"],"Límite de llamadas de la sesión alcanzado." if snapshot["reason"]=="session_call_budget_exhausted" else "La siguiente llamada excedería el presupuesto disponible de la sesión.")
            exc.metadata={"gateway_budget":snapshot};raise exc
    def _record(self,result):
        if self.session is None:return
        self.session["llm_gateway_calls"]=int(self.session.get("llm_gateway_calls",0))+1
        self.session["llm_gateway_tokens"]=int(self.session.get("llm_gateway_tokens",0))+int(result.usage.get("total_tokens",0))
        history=list(self.session.get("llm_gateway_history",[]) or []);history.append(result.to_dict());self.session["llm_gateway_history"]=history[-100:]
        self.session["llm_gateway_budget_diagnostic"]=self._budget_snapshot()
    def _error_result(self,provider,model,purpose,exc,fallback_used=False,fallback_provider=None):
        metadata=dict(getattr(exc,"metadata",{}) or {});metadata.setdefault("attempted_model",model);metadata.setdefault("status_code",getattr(exc,"status_code",None))
        return LLMResult(False,provider=provider,model=model,purpose=purpose,error_code=exc.code,error_message=str(exc),fallback_used=fallback_used,fallback_provider=fallback_provider,metadata=metadata)
    def _reserve_output(self,request):
        purpose=str(request.purpose or "").casefold();role=str(getattr(request,"model_role","") or "").casefold()
        if "judge" in purpose:configured=int(self.config.get("evidence_judge_max_tokens",360))
        elif "understanding" in purpose:configured=int(self.config.get("understanding_max_tokens",360))
        elif role=="orchestrator" or "orchestrator" in purpose:configured=int(self.config.get("orchestrator_max_tokens",220))
        else:configured=int(self.config.get("answer_max_tokens",900))
        requested=max(1,int(request.max_tokens or configured));granted=min(requested,configured);request.max_tokens=granted
        setattr(request,"_token_debug",{"requested_max_tokens":requested,"configured_cap":configured,"effective_max_tokens":granted,"policy":"role_cap_v2_no_rolling_clamp"});return request
    def _record_output(self,result):
        if self.session is None:return
        now=time.time();ledger=[x for x in list(self.session.get("llm_gateway_output_ledger",[]) or []) if now-float(x.get("time",0))<60]
        used=int((result.usage or {}).get("completion_tokens",0) or 0)
        if used:ledger.append({"time":now,"tokens":used,"purpose":result.purpose})
        self.session["llm_gateway_output_ledger"]=ledger
    def _now(self):return time.time()
    def _circuit_key(self,route):return f"huggingface:{route}"
    def _circuit_get(self,route):
        if self.session is None:return default_state()
        return dict((self.session.get("llm_gateway_circuit_breakers",{}) or {}).get(self._circuit_key(route)) or default_state())
    def _circuit_set(self,route,state):
        if self.session is None:return
        all_states=dict(self.session.get("llm_gateway_circuit_breakers",{}) or {});all_states[self._circuit_key(route)]=dict(state);self.session["llm_gateway_circuit_breakers"]=all_states
    def _circuit_before(self,route,hf):
        state=self._circuit_get(route)
        if not hf.get("circuit_breaker_enabled",True):return state,True,{"reason":"circuit_disabled","remaining_seconds":0.0}
        state,allowed,decision=evaluate_circuit(state,self._now(),hf.get("circuit_cooldown_seconds",60),hf.get("circuit_half_open_max_calls",1));self._circuit_set(route,state);return state,allowed,decision
    def _circuit_success(self,route,hf):
        if hf.get("circuit_breaker_enabled",True):self._circuit_set(route,circuit_success(self._circuit_get(route)))
    def _circuit_failure(self,route,hf,error):
        if hf.get("circuit_breaker_enabled",True):self._circuit_set(route,circuit_failure(self._circuit_get(route),self._now(),hf.get("circuit_failure_threshold",2),getattr(error,"code",None)))
    def _rate_limit_wait(self,exc,hf):
        metadata=dict(getattr(exc,"metadata",{}) or {});suggested=metadata.get("rate_limit_wait_suggested_seconds");source=metadata.get("rate_limit_wait_source")
        if suggested is None:suggested=float(hf.get("rate_limit_default_wait_seconds",10));source="configured_default"
        suggested=max(0.0,float(suggested));maximum=float(hf.get("rate_limit_max_wait_seconds",45));jitter_max=float(hf.get("rate_limit_jitter_seconds",2))
        if suggested>maximum:return {"retry_allowed":False,"suggested_wait_seconds":suggested,"wait_seconds":0.0,"wait_source":source,"skip_reason":"suggested_wait_exceeds_maximum"}
        jitter=random.uniform(0.0,jitter_max) if jitter_max>0 else 0.0
        return {"retry_allowed":True,"suggested_wait_seconds":suggested,"wait_seconds":min(maximum,suggested+jitter),"wait_source":source,"jitter_seconds":jitter,"skip_reason":None}
    def _sleep(self,seconds):time.sleep(max(0.0,float(seconds)))
    def complete(self,request):
        request=self._reserve_output(request);self._budget(request);primary=self.config["provider"];primary_model=model_for(self.config,primary,request.purpose,getattr(request,"model_role",None))
        if primary=="huggingface":
            hf=self.config["providers"]["huggingface"];primary_route=hf.get("primary_provider");fallback_route=hf.get("fallback_provider");route_fallback=bool(hf.get("route_fallback_enabled") and fallback_route and fallback_route!=primary_route);retry_trace=[]
            circuit_before,primary_allowed,circuit_decision=self._circuit_before(primary_route,hf)
            if not primary_allowed:
                if not route_fallback:
                    error=LLMGatewayError("circuit_open","Ruta primaria temporalmente suspendida por circuit breaker.",True)
                    result=self._error_result(primary,primary_model,request.purpose,error);result.metadata={**dict(result.metadata or {}),"circuit_state_before":circuit_before,"circuit_state_after":self._circuit_get(primary_route),"circuit_decision":circuit_decision,"primary_skipped_by_circuit":False,"provider_route_initial":primary_route,"provider_route_final":primary_route,"route_fallback_used":False,"circuit_state_before":circuit_before,"circuit_state_after":self._circuit_get(primary_route),"circuit_decision":circuit_decision,"primary_skipped_by_circuit":True};self._record(result);return result
                try:
                    result=self._provider(primary,fallback_route).complete(request,primary_model);result.fallback_used=True;result.fallback_provider=fallback_route;result.metadata={**dict(result.metadata or {}),"circuit_state_before":circuit_before,"circuit_state_after":self._circuit_get(primary_route),"circuit_decision":circuit_decision,"primary_skipped_by_circuit":False,"provider_route_initial":primary_route,"provider_route_final":fallback_route,"route_fallback_used":True,"route_fallback_reason":"circuit_open","rate_limit_retry_count":0,"rate_limit_retry_trace":[],"circuit_state_before":circuit_before,"circuit_state_after":self._circuit_get(primary_route),"circuit_decision":circuit_decision,"primary_skipped_by_circuit":True,"token_budget_debug":getattr(request,"_token_debug",{}),"gateway_budget":self._budget_snapshot(request)};self._record(result);self._record_output(result);return result
                except LLMGatewayError as second:
                    result=self._error_result(primary,primary_model,request.purpose,second,True,fallback_route);result.metadata={**dict(result.metadata or {}),"circuit_state_before":circuit_before,"circuit_state_after":self._circuit_get(primary_route),"circuit_decision":circuit_decision,"primary_skipped_by_circuit":False,"provider_route_initial":primary_route,"provider_route_final":fallback_route,"route_fallback_used":True,"route_fallback_reason":"circuit_open","circuit_state_before":circuit_before,"circuit_state_after":self._circuit_get(primary_route),"circuit_decision":circuit_decision,"primary_skipped_by_circuit":True};self._record(result);return result
            try:
                result=self._provider(primary,primary_route).complete(request,primary_model);self._circuit_success(primary_route,hf);result.metadata={**dict(result.metadata or {}),"circuit_state_before":circuit_before,"circuit_state_after":self._circuit_get(primary_route),"circuit_decision":circuit_decision,"primary_skipped_by_circuit":False,"provider_route_initial":primary_route,"provider_route_final":primary_route,"route_fallback_used":False,"rate_limit_retry_count":0,"rate_limit_retry_trace":retry_trace,"token_budget_debug":getattr(request,"_token_debug",{}),"gateway_budget":self._budget_snapshot(request)};self._record(result);self._record_output(result);return result
            except LLMGatewayError as exc:
                primary_error=exc;max_retries=int(hf.get("rate_limit_max_retries",1))
                if exc.code=="rate_limited" and max_retries>0:
                    wait=self._rate_limit_wait(exc,hf);retry_trace.append({"attempt":1,"error_code":exc.code,**wait})
                    if wait["retry_allowed"]:
                        self._sleep(wait["wait_seconds"])
                        try:
                            result=self._provider(primary,primary_route).complete(request,primary_model);self._circuit_success(primary_route,hf);result.metadata={**dict(result.metadata or {}),"circuit_state_before":circuit_before,"circuit_state_after":self._circuit_get(primary_route),"circuit_decision":circuit_decision,"primary_skipped_by_circuit":False,"provider_route_initial":primary_route,"provider_route_final":primary_route,"route_fallback_used":False,"rate_limit_retry_count":1,"rate_limit_retry_succeeded":True,"rate_limit_retry_trace":retry_trace,"token_budget_debug":getattr(request,"_token_debug",{}),"gateway_budget":self._budget_snapshot(request)};self._record(result);self._record_output(result);return result
                        except LLMGatewayError as retry_exc:primary_error=retry_exc;retry_trace[-1]["retry_error_code"]=retry_exc.code;retry_trace[-1]["retry_succeeded"]=False
                if primary_error.recoverable:self._circuit_failure(primary_route,hf,primary_error)
                if not (primary_error.recoverable and route_fallback):
                    result=self._error_result(primary,primary_model,request.purpose,primary_error);result.metadata={**dict(result.metadata or {}),"circuit_state_before":circuit_before,"circuit_state_after":self._circuit_get(primary_route),"circuit_decision":circuit_decision,"primary_skipped_by_circuit":False,"provider_route_initial":primary_route,"provider_route_final":primary_route,"route_fallback_used":False,"rate_limit_retry_count":len(retry_trace),"rate_limit_retry_trace":retry_trace};self._record(result);return result
                try:
                    result=self._provider(primary,fallback_route).complete(request,primary_model);result.fallback_used=True;result.fallback_provider=fallback_route;result.metadata={**dict(result.metadata or {}),"circuit_state_before":circuit_before,"circuit_state_after":self._circuit_get(primary_route),"circuit_decision":circuit_decision,"primary_skipped_by_circuit":False,"provider_route_initial":primary_route,"provider_route_final":fallback_route,"route_fallback_used":True,"route_fallback_reason":primary_error.code,"rate_limit_retry_count":len(retry_trace),"rate_limit_retry_trace":retry_trace,"token_budget_debug":getattr(request,"_token_debug",{}),"gateway_budget":self._budget_snapshot(request)};self._record(result);self._record_output(result);return result
                except LLMGatewayError as second:
                    result=self._error_result(primary,primary_model,request.purpose,second,True,fallback_route);result.metadata={**dict(result.metadata or {}),"circuit_state_before":circuit_before,"circuit_state_after":self._circuit_get(primary_route),"circuit_decision":circuit_decision,"primary_skipped_by_circuit":False,"provider_route_initial":primary_route,"provider_route_final":fallback_route,"route_fallback_used":True,"route_fallback_reason":primary_error.code,"primary_error_code":primary_error.code,"rate_limit_retry_count":len(retry_trace),"rate_limit_retry_trace":retry_trace};self._record(result);return result
        try:
            result=self._provider(primary).complete(request,primary_model);result.metadata={**dict(result.metadata or {}),"token_budget_debug":getattr(request,"_token_debug",{}),"gateway_budget":self._budget_snapshot(request)};self._record(result);self._record_output(result);return result
        except LLMGatewayError as exc:
            result=self._error_result(primary,primary_model,request.purpose,exc);self._record(result);return result
