from __future__ import annotations
from dataclasses import dataclass, asdict
from typing import Any, Callable
import copy

GATE_VERSION = "phase2d2_web_robustness_v1"

@dataclass(frozen=True)
class GateCase:
    case_id: str
    category: str
    description: str
    expected: dict[str, Any]
    retrieval: dict[str, Any]

@dataclass(frozen=True)
class GateResult:
    case_id: str
    category: str
    description: str
    passed: bool
    expected: dict[str, Any]
    observed: dict[str, Any]
    mismatches: list[str]
    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

def _e(page: int, text: str, source: str = "controlled-doc-a") -> dict[str, Any]:
    return {
        "id": f"R{page}", "page": str(page), "source": source, "url": source,
        "title": "Controlled synthetic fixture", "text": text,
        "metadata": {"page_label": str(page), "source": source},
    }

def default_cases() -> list[GateCase]:
    action_a = ("Open the configuration file, verify the required field, save the change, run the process and confirm the result. ") * 7
    action_b = ("Select the next option, copy the validated values, execute the operation, update the view and verify completion. ") * 7
    noise = ("General notice, retention information, document control and administrative metadata without operational instructions. ") * 7
    return [
        GateCase("S01", "sufficiency", "Multi-page actionable evidence in one ordered document",
                 {"status": "sufficient", "generation_allowed": True, "internal_knowledge_candidate": False},
                 {"ok": True, "evidence": [_e(1, action_a), _e(2, action_b)], "document_groups": [{"identity": "controlled-doc-a"}], "procedural_expansion": {"ok": True, "same_document_only": True, "ordered": True, "pages": ["1", "2"]}}),
        GateCase("P01", "sufficiency", "One actionable page is useful but incomplete",
                 {"status": "partial", "generation_allowed": False, "internal_knowledge_candidate": True},
                 {"ok": True, "evidence": [_e(1, action_a)], "document_groups": [{"identity": "controlled-doc-a"}], "procedural_expansion": {"ok": True, "same_document_only": True, "ordered": True, "pages": ["1"]}}),
        GateCase("I01", "sufficiency", "No retrieved evidence",
                 {"status": "insufficient", "generation_allowed": False, "internal_knowledge_candidate": True},
                 {"ok": True, "evidence": [], "document_groups": [], "procedural_expansion": {"ok": False, "same_document_only": False, "ordered": False, "pages": []}}),
        GateCase("I02", "sufficiency", "Administrative content without actionable instructions",
                 {"status": "insufficient", "generation_allowed": False, "internal_knowledge_candidate": True},
                 {"ok": True, "evidence": [_e(1, noise)], "document_groups": [{"identity": "controlled-doc-a"}], "procedural_expansion": {"ok": True, "same_document_only": True, "ordered": True, "pages": ["1"]}}),
        GateCase("M01", "isolation", "Actionable chunks from multiple documents",
                 {"generation_allowed": False, "same_document_only": False},
                 {"ok": True, "evidence": [_e(1, action_a, "controlled-doc-a"), _e(2, action_b, "controlled-doc-b")], "document_groups": [{"identity": "controlled-doc-a"}, {"identity": "controlled-doc-b"}], "procedural_expansion": {"ok": True, "same_document_only": False, "ordered": True, "pages": ["1", "2"]}}),
        GateCase("O01", "ordering", "Evidence explicitly marked unordered",
                 {"generation_allowed": False, "ordered": False},
                 {"ok": True, "evidence": [_e(2, action_b), _e(1, action_a)], "document_groups": [{"identity": "controlled-doc-a"}], "procedural_expansion": {"ok": True, "same_document_only": True, "ordered": False, "pages": ["2", "1"]}}),
    ]

def run_gate(assess_fn: Callable[[dict[str, Any]], Any]) -> dict[str, Any]:
    results: list[GateResult] = []
    for case in default_cases():
        raw = assess_fn(copy.deepcopy(case.retrieval))
        observed = raw.to_dict() if hasattr(raw, "to_dict") else dict(raw)
        mismatches = [f"{key}: expected={value!r}, observed={observed.get(key)!r}" for key, value in case.expected.items() if observed.get(key) != value]
        results.append(GateResult(case.case_id, case.category, case.description, not mismatches, case.expected, observed, mismatches))
    passed = sum(item.passed for item in results)
    return {
        "gate_version": GATE_VERSION, "synthetic_fixtures": True, "llm_calls": 0,
        "tokens": 0, "conversation_changed": False, "production_changed": False,
        "passed": passed, "failed": len(results) - passed, "total": len(results),
        "approved": passed == len(results), "results": [item.to_dict() for item in results],
    }
