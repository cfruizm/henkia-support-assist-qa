"""Offline checks for understanding-contract recovery from provider schema drift.

The payloads are real provider outputs captured in QA (json_object mode), where
canonical_subject / subject_origin / intent came nested inside other objects and
were silently replaced by defaults, so an explicit new subject was lost.
"""

from app.agent_core_v2_clean.understanding import ConversationUnderstanding

NESTED_NEW_SUBJECT = """{
  "reasoning_summary": "New procedural request for PaperCut Find-Me configuration, distinct from previous HP Access Control topic.",
  "current_goal": {
    "summary": "Obtener el procedimiento aprobado para configurar PaperCut Find-Me",
    "intent": "procedural",
    "known_details": {"subject": "PaperCut Find-Me"},
    "missing_detail": null,
    "status": "pending"
  },
  "topic_relation": {
    "is_same_topic": false,
    "canonical_subject": "PaperCut Find-Me",
    "subject_origin": "current_message",
    "reference_relation": "none"
  },
  "case_updates": [],
  "should_retrieve": true,
  "needs_clarification": false,
  "clarification_question": null,
  "requested_workflow": "none"
}"""

NESTED_SAME_SUBJECT = """{
  "reasoning_summary": "New symptom reported for active subject.",
  "current_goal": {"summary": "Diagnose why jobs disappear before release", "intent": "troubleshooting", "status": "active"},
  "topic_relation": {
    "is_same_topic": true,
    "canonical_subject": "Platform Alpha",
    "subject_origin": "conversation_memory",
    "reference_relation": "current_subject"
  },
  "case_updates": [{"type": "observation", "value": "Jobs disappear before release"}],
  "should_retrieve": true,
  "needs_clarification": false,
  "requested_workflow": "none"
}"""

FLAT_VALID = """{
  "user_act": "new_request", "intent": "requirements", "topic_relation": "new_topic",
  "domain_relevance": "in_scope", "current_goal": "Requisitos de Platform Alpha",
  "goal_complete": false, "goal_updates": {}, "case_updates": [],
  "needs_clarification": false, "clarification_target": null, "should_retrieve": true,
  "confidence": 0.9, "reasoning_summary": "ok", "canonical_subject": "Platform Alpha",
  "subject_origin": "current_message", "reference_relation": "none", "requested_workflow": "none"
}"""


def _parse(text):
    understanding = ConversationUnderstanding(gateway=None)
    return understanding._parse(text), understanding.normalization


def test_nested_explicit_new_subject_is_recovered():
    u, norm = _parse(NESTED_NEW_SUBJECT)
    assert u.canonical_subject == "PaperCut Find-Me"
    assert u.subject_origin == "current_message"
    assert u.topic_relation == "new_topic"
    assert u.reference_relation == "none"
    assert u.intent == "procedural"
    assert u.current_goal.startswith("Obtener el procedimiento")
    assert "canonical_subject" not in norm["defaulted_core_fields"]


def test_nested_same_topic_object_maps_to_enum():
    u, _ = _parse(NESTED_SAME_SUBJECT)
    assert u.topic_relation == "same_topic"
    assert u.canonical_subject == "Platform Alpha"
    assert u.subject_origin == "conversation_memory"
    assert u.intent == "troubleshooting"


def test_flat_valid_payload_is_unchanged_and_reports_no_defaults():
    u, norm = _parse(FLAT_VALID)
    assert (u.intent, u.topic_relation, u.canonical_subject) == ("requirements", "new_topic", "Platform Alpha")
    assert norm["defaulted_core_fields"] == []
    assert not any("." in key for key in norm["schema_aliases"])


def test_defaulted_core_fields_are_reported():
    _, norm = _parse('{"current_goal": "Algo", "case_updates": [], "should_retrieve": true}')
    assert {"user_act", "intent", "canonical_subject"} <= set(norm["defaulted_core_fields"])
