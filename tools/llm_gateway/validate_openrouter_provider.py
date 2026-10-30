import sys,types,pathlib
ROOT=pathlib.Path(__file__).parent
# Package aliases for isolated validation.
app=types.ModuleType("app");pkg=types.ModuleType("app.llm_gateway");providers=types.ModuleType("app.llm_gateway.providers")
app.__path__=[];pkg.__path__=[str(ROOT)];providers.__path__=[str(ROOT/"providers")]
sys.modules.setdefault("app",app);sys.modules.setdefault("app.llm_gateway",pkg);sys.modules.setdefault("app.llm_gateway.providers",providers)
from app.llm_gateway.config import load_gateway_config,model_for
from app.llm_gateway.models import LLMRequest
from app.llm_gateway.providers.openrouter_provider import OpenRouterProvider,inspect_key

def run():
 secrets={"LLM_PROVIDER":"openrouter","OPENROUTER_API_KEY":"sk-or-v1-test","OPENROUTER_ORCHESTRATOR_MODEL":"vendor/orchestrator","OPENROUTER_ANSWER_MODEL":"vendor/answer"}
 cfg=load_gateway_config(secrets)
 assert cfg["provider"]=="openrouter" and model_for(cfg,"openrouter",model_role="orchestrator")=="vendor/orchestrator" and model_for(cfg,"openrouter",model_role="answer")=="vendor/answer"
 assert inspect_key("sk-or-v1-test")["prefix_valid"] is True
 p=OpenRouterProvider("sk-or-v1-test",structured_mode="best_effort")
 r=LLMRequest([{"role":"user","content":"test"}],response_schema={"type":"object"})
 fmt,mode=p._response_format(r);assert mode=="json_object" and fmt["type"]=="json_object"
 r.response_format_mode="schema";fmt,mode=p._response_format(r);assert mode=="json_schema" and fmt["type"]=="json_schema"
 gateway=(ROOT/"gateway.py").read_text();assert 'name=="openrouter"' in gateway
 print({"passed":7,"failed":0,"provider":"openrouter"})
if __name__=="__main__":run()
