"""Offline checks for per-purpose output caps (no provider calls)."""

from app.llm_gateway.config import load_gateway_config
from app.llm_gateway.gateway import LLMGateway
from app.llm_gateway.models import LLMRequest


def _granted(purpose, requested, secrets=None):
    gateway = LLMGateway(load_gateway_config(secrets or {}))
    request = LLMRequest([{"role": "user", "content": "x"}], purpose, requested, 0.0, None)
    return gateway._reserve_output(request).max_tokens


def test_procedural_answer_gets_document_cap_not_conversational_cap():
    assert _granted("agent_core_v2_clean_procedural_answer", 1800) == 1800
    assert _granted("agent_core_v2_clean_documented_answer", 900) == 900
    assert _granted("agent_core_v2_clean_natural_response", 1800) == 900


def test_document_cap_is_configurable():
    assert _granted("agent_core_v2_clean_procedural_answer", 1800, {"LLM_DOCUMENT_ANSWER_MAX_TOKENS": 1200}) == 1200


def test_procedural_contract_carries_output_budget():
    from app.agent_core_v2_clean.procedural_answer import ProceduralAnswerComposer, _response_contract

    assert ProceduralAnswerComposer(None, 5000).max_tokens == 1800
    contract = _response_contract({}, {"query": {"fields": {"topic_relation": "new_topic", "user_act": "new_request"}}}, [], 1800)
    assert contract["output_budget_tokens"] == 1800 and contract["mode"] == "full_document_procedure"


def test_understanding_contract_has_room_for_reported_attempts():
    from app.agent_core_v2_clean.budget import BudgetPolicy
    from app.agent_core_v2_clean.understanding import ConversationUnderstanding

    policy = BudgetPolicy()
    assert ConversationUnderstanding(None, policy.understanding_max_tokens).max_tokens == 800
    assert _granted("agent_core_v2_clean_understanding", policy.understanding_max_tokens) == 800
