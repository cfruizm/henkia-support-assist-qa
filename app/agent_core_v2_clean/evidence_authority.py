from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class EvidenceDecision:
    status: str
    generation_mode: str
    reason: str
    selected_ids: list[str]
    product_match: float
    object_match: float
    operation_match: float
    intent_match: float
    coverage: float
    accepted: bool

    def to_dict(self):
        return asdict(self)


_VALID_STATUS = {"sufficient", "partial", "insufficient"}
_VALID_MODE = {
    "documented",
    "documented_only",
    "documented_plus_internal",
    "hybrid",
    "internal_only",
}


def _float(value) -> float:
    try:
        return max(0.0, min(1.0, float(value or 0.0)))
    except (TypeError, ValueError):
        return 0.0


def _ids(verdict: dict) -> list[str]:
    values = verdict.get("evidence_ids") or verdict.get("selected_ids") or []
    out: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in out:
            out.append(text)
    return out


def _mode(status: str, raw_mode: str) -> str:
    value = str(raw_mode or "").strip().casefold()
    if value in _VALID_MODE:
        if value in {"documented_only"}:
            return "documented"
        if value == "hybrid":
            return "documented_plus_internal"
        return value
    if status == "sufficient":
        return "documented"
    if status == "partial":
        return "documented_plus_internal"
    return "internal_only"


def canonical_evidence_decision(retrieval: dict, intent: str) -> EvidenceDecision:
    """Translate the unified verdict without re-judging evidence.

    Authority ownership:
    - ``unified_evidence_authority.apply_unified_evidence_verdict`` selects and
      authorizes documentary evidence.
    - This module only validates and translates that verdict for downstream
      consumers.

    It deliberately contains no lexical thresholds, semantic-fit fallback,
    product-match fallback, or second acceptance algorithm. If the unified
    verdict is absent or malformed, generation remains closed.
    """
    retrieval = retrieval or {}
    verdict = retrieval.get("evidence_verdict") or {}
    if not verdict:
        return EvidenceDecision(
            "insufficient",
            "internal_only",
            "unified_evidence_verdict_missing",
            [],
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
            False,
        )

    status = str(verdict.get("status") or "insufficient").strip().casefold()
    if status not in _VALID_STATUS:
        status = "insufficient"

    selected_ids = _ids(verdict)
    accepted = bool(verdict.get("accepted"))
    coverage = _float(verdict.get("coverage"))
    operation = verdict.get("operation_alignment") or {}

    # Sufficient documentary authority must be internally coherent. A verdict
    # cannot open generation if it selected no evidence or did not accept it.
    if status == "sufficient" and (not accepted or not selected_ids):
        status = "insufficient"
        accepted = False
        reason = "invalid_sufficient_unified_verdict"
    else:
        reason = str(verdict.get("reason") or "unified_evidence_verdict")

    # Partial authority is intentionally not promoted here. The response plan
    # decides whether the authorized partial evidence may be published in a
    # hybrid answer.
    if status != "sufficient":
        accepted = False

    aligned = 1.0 if bool(operation.get("aligned")) else coverage
    return EvidenceDecision(
        status=status,
        generation_mode=_mode(status, verdict.get("mode")),
        reason=reason,
        selected_ids=selected_ids,
        product_match=coverage,
        object_match=coverage,
        operation_match=aligned,
        intent_match=coverage,
        coverage=coverage,
        accepted=accepted,
    )
