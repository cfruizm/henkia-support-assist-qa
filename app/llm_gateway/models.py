from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Any

@dataclass
class LLMRequest:
    messages: list[dict[str, str]]
    purpose: str = "diagnostic"
    max_tokens: int = 180
    temperature: float = 0.0
    response_schema: dict[str, Any] | None = None
    # Optional, backward-compatible routing controls. Existing callers need no changes.
    model_role: str | None = None          # orchestrator | answer | None(auto)
    response_format_mode: str = "auto"     # auto | schema | json_object | text
    reasoning_effort: str | None = None     # low | medium | high | None

@dataclass
class LLMResult:
    ok: bool
    text: str = ""
    provider: str = ""
    model: str = ""
    purpose: str = ""
    latency_ms: float = 0.0
    usage: dict[str, int] = field(default_factory=dict)
    finish_reason: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    fallback_used: bool = False
    fallback_provider: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    def to_dict(self):
        return asdict(self)
