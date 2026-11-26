"""Offline checks for the strict structured-output understanding schema."""

from app.agent_core_v2_clean.understanding import (
    GOAL_UPDATE_KEYS,
    STRICT_UNDERSTANDING_SCHEMA,
    ConversationUnderstanding,
)
from app.llm_gateway.schema_utils import make_strict


def _objects(schema, path="$"):
    """Yield (path, node) for every object node with properties."""
    if isinstance(schema, dict):
        if isinstance(schema.get("properties"), dict):
            yield path, schema
            for name, prop in schema["properties"].items():
                yield from _objects(prop, f"{path}.{name}")
        if isinstance(schema.get("items"), dict):
            yield from _objects(schema["items"], f"{path}[]")


def test_every_object_is_strict():
    nodes = list(_objects(STRICT_UNDERSTANDING_SCHEMA))
    assert len(nodes) >= 3  # root, goal_updates, case_updates items
    for path, node in nodes:
        assert node.get("additionalProperties") is False, path
        assert set(node["required"]) == set(node["properties"]), path


def test_previously_optional_fields_become_nullable():
    props = STRICT_UNDERSTANDING_SCHEMA["properties"]
    assert "null" in props["reference_relation"]["type"] and None in props["reference_relation"]["enum"]
    assert "null" in props["canonical_subject"]["type"]
    assert props["intent"]["type"] == "string"  # originally required: not nullable
    assert set(props["goal_updates"]["properties"]) == set(GOAL_UPDATE_KEYS)


def test_make_strict_does_not_mutate_input():
    original = {"type": "object", "properties": {"a": {"type": "string"}}, "required": []}
    make_strict(original)
    assert "additionalProperties" not in original and original["required"] == []


def test_strict_payload_with_nulls_parses_like_absent_fields():
    payload = """{
      "user_act": "new_request", "intent": "procedural", "topic_relation": "new_topic",
      "domain_relevance": "in_scope", "current_goal": "Instalar Platform Alpha", "goal_complete": false,
      "goal_updates": {"subject": "Platform Alpha", "product": null, "operation": null},
      "case_updates": [{"type": "symptom", "value": "falla", "result": null, "outcome": null, "result_unknown": null}],
      "needs_clarification": false, "clarification_target": null, "should_retrieve": true,
      "confidence": 0.9, "reasoning_summary": "ok", "canonical_subject": "Platform Alpha",
      "subject_origin": "current_message", "reference_relation": null, "requested_workflow": "none"
    }"""
    understanding = ConversationUnderstanding(gateway=None)
    u = understanding._parse(payload)
    assert u.reference_relation == "none"
    assert u.goal_updates == {"subject": "Platform Alpha"}
    assert u.case_updates == [{"type": "symptom", "value": "falla"}]


def test_goal_type_alias_maps_to_intent():
    understanding = ConversationUnderstanding(gateway=None)
    u = understanding._parse('{"goal_type": "requirements", "current_goal": "Requisitos", "case_updates": []}')
    assert u.intent == "requirements"
    assert "intent" not in understanding.normalization["defaulted_core_fields"]
