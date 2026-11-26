"""Offline checks for interruption-safe turns and attempt_result memory updates.

Streamlit stops an interrupted run with a control-flow exception that is not an
Exception subclass; it is simulated here with _ScriptInterrupted.
"""

import app.agent_core_v2_clean.lab_session as lab
from app.agent_core_v2_clean.memory import apply_understanding
from app.agent_core_v2_clean.models import ConversationMemory, TurnUnderstanding


class _ScriptInterrupted(BaseException):
    """Stand-in for Streamlit's StopException/RerunException."""


def _fake_process(calls, interrupt_first=0):
    def process(message, secrets_obj, s):
        calls.append(message)
        store = lab.get_store(s)
        store["messages"].append({"role": "user", "content": message})
        store["memory"].turn_number += 1
        if len(calls) <= interrupt_first:
            raise _ScriptInterrupted()
        store["messages"].append({"role": "assistant", "content": f"respuesta a {message}"})
        store["turns"].append({"input": message})
        return {"input": message, "answer": {"text": "ok"}}
    return process


def _run(s):
    try:
        return lab.process_pending({}, s), False
    except _ScriptInterrupted:
        return None, True


def test_interrupted_turn_is_rolled_back_and_retried_once():
    s, calls = {}, []
    original = lab.process_message
    lab.process_message = _fake_process(calls, interrupt_first=1)
    try:
        lab.submit_message("¿Qué puertos requiere?", s)
        _, interrupted = _run(s)
        assert interrupted
        store = lab.get_store(s)
        assert store["messages"] == [] and store["memory"].turn_number == 0, "partial turn must be rolled back"
        assert lab.pending_message(s)["attempts"] == 1

        result, interrupted = _run(s)
        assert not interrupted and result["turn_recovery"]["recovered_after_interruptions"] == 1
        store = lab.get_store(s)
        assert [m["role"] for m in store["messages"]] == ["user", "assistant"], "no duplicated user message"
        assert lab.pending_message(s) is None
        assert store["turn_recovery"] == {"interrupted": 1, "recovered": 1, "abandoned": 0}
    finally:
        lab.process_message = original


def test_turn_is_abandoned_with_a_visible_message_after_max_attempts():
    s, calls = {}, []
    original = lab.process_message
    lab.process_message = _fake_process(calls, interrupt_first=99)
    try:
        lab.submit_message("consulta que siempre se interrumpe", s)
        for _ in range(lab.MAX_PENDING_ATTEMPTS):
            assert _run(s)[1]
        result, interrupted = _run(s)
        assert result is None and not interrupted
        store = lab.get_store(s)
        assert len(calls) == lab.MAX_PENDING_ATTEMPTS
        assert store["messages"][-1]["content"] == lab.ABANDONED_TURN_TEXT
        assert store["turn_recovery"]["abandoned"] == 1
        assert lab.pending_message(s) is None
    finally:
        lab.process_message = original


def test_completed_turn_clears_pending_without_recovery_marks():
    s, calls = {}, []
    original = lab.process_message
    lab.process_message = _fake_process(calls)
    try:
        lab.submit_message("hola", s)
        result, interrupted = _run(s)
        assert not interrupted and "turn_recovery" not in result
        assert lab.pending_message(s) is None
        recovery = lab.get_store(s).get("turn_recovery") or {}
        assert not any(recovery.values()), recovery
    finally:
        lab.process_message = original


def test_reset_store_drops_pending_prompt():
    s = {}
    lab.submit_message("pendiente", s)
    lab.reset_store(s)
    assert lab.pending_message(s) is None


def test_attempt_result_without_prior_action_does_not_crash():
    memory = ConversationMemory()
    understanding = TurnUnderstanding(
        user_act="attempt_result",
        intent="troubleshooting",
        topic_relation="same_topic",
        domain_relevance="in_scope",
        current_goal="Resolver trabajos detenidos",
        goal_complete=False,
        case_updates=[{"type": "attempt_result", "value": "Reinicié el servicio y sigue igual", "outcome": "unknown"}],
    )
    apply_understanding(memory, understanding)
    attempts = memory.support_case.attempts
    assert attempts and attempts[-1]["result"] == "Reinicié el servicio y sigue igual"
