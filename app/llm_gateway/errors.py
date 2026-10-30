class LLMGatewayError(RuntimeError):
    def __init__(self,code:str,message:str,recoverable:bool=False,status_code:int|None=None):
        super().__init__(message);self.code=code;self.recoverable=recoverable;self.status_code=status_code

def normalize_error(exc)->LLMGatewayError:
    status=getattr(getattr(exc,"response",None),"status_code",None)
    text=str(exc).lower()
    from app.llm_gateway.rate_limit import rate_limit_metadata
    rate_metadata=rate_limit_metadata(exc)
    if status==402 or "payment required" in text or "depleted" in text:return LLMGatewayError("credits_exhausted","Créditos del proveedor agotados.",True,402)
    if status==429 or "rate limit" in text:
        error=LLMGatewayError("rate_limited","Límite temporal del proveedor alcanzado.",True,429)
        error.metadata={**rate_metadata,"status_code":429}
        return error
    if status in {500,502,503,504} or "timeout" in text:return LLMGatewayError("provider_unavailable","Proveedor temporalmente no disponible.",True,status)
    if status in {401,403}:return LLMGatewayError("authentication_failed","Clave inválida o sin permisos.",False,status)
    if status==404:return LLMGatewayError("model_not_found","Modelo no disponible.",True,404)
    return LLMGatewayError("provider_error",f"Error del proveedor: {type(exc).__name__}",False,status)
