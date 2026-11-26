"""Make JSON schemas compatible with providers' strict structured-output mode.

Strict json_schema modes (OpenAI-compatible providers such as Cerebras) only
enforce a schema when every object declares additionalProperties=false and
lists all of its properties as required. Schemas that do not follow those rules
may be silently ignored, which is what QA showed: with json_schema configured
the provider still invented fields and omitted required ones.

make_strict() keeps the original semantics: properties that were optional become
nullable (null means "not provided"), so callers must treat null like absence.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any


def _nullable(prop: dict) -> dict:
    prop = deepcopy(prop)
    kind = prop.get("type")
    if isinstance(kind, str) and kind != "null":
        prop["type"] = [kind, "null"]
    elif isinstance(kind, list) and "null" not in kind:
        prop["type"] = [*kind, "null"]
    if "enum" in prop and None not in prop["enum"]:
        prop["enum"] = [*prop["enum"], None]
    return prop


def make_strict(schema: dict[str, Any]) -> dict[str, Any]:
    """Return a strict-mode copy of a JSON schema (recursively)."""
    node = deepcopy(schema)
    kinds = node.get("type")
    is_object = kinds == "object" or (isinstance(kinds, list) and "object" in kinds)
    if is_object and isinstance(node.get("properties"), dict):
        required = set(node.get("required") or [])
        properties = {}
        for name, prop in node["properties"].items():
            prop = make_strict(prop) if isinstance(prop, dict) else prop
            properties[name] = prop if name in required else _nullable(prop)
        node["properties"] = properties
        node["required"] = list(properties)
        node["additionalProperties"] = False
    if isinstance(node.get("items"), dict):
        node["items"] = make_strict(node["items"])
    return node
