from __future__ import annotations

from dataclasses import asdict, dataclass

from .evidence_authority import canonical_evidence_decision


@dataclass(frozen=True)
class EvidenceAssessment:
    status: str
    score: float
    reasons: list[str]
    usable_chunks: int
    unique_pages: int
    same_document_only: bool
    ordered: bool
    generation_allowed: bool
    internal_knowledge_candidate: bool
    coverage_basis: str = "selected_evidence"
    retrieval_quality: float = 0.0
    relevance_supported: bool = False
    canonical_decision: dict | None = None

    def to_dict(self):
        return asdict(self)


def _identity(item: dict) -> str:
    metadata = item.get("metadata") or {}
    return str(
        item.get("url")
        or item.get("source")
        or metadata.get("canonical_url")
        or metadata.get("source")
        or item.get("title")
        or ""
    ).strip()


def assess_procedural_evidence(retrieval, intent="procedural"):
    """Build diagnostics from the canonical verdict, never a second verdict.

    Structural properties remain diagnostics and guards. They cannot promote an
    insufficient/partial verdict to sufficient, and they cannot replace the
    unified evidence authority.
    """
    retrieval = retrieval or {}
    decision = canonical_evidence_decision(retrieval, intent)
    evidence = list(
        retrieval.get("generation_evidence")
        or retrieval.get("evidence")
        or []
    )
    expansion = retrieval.get("procedural_expansion") or {}
    pages = {
        str(item.get("page"))
        for item in evidence
        if item.get("page") not in (None, "")
    }
    identities = {_identity(item) for item in evidence if _identity(item)}
    same_document_only = bool(
        expansion.get("same_document_only", len(identities) <= 1)
    )
    ordered = bool(expansion.get("ordered", True))

    structural_ok = bool(evidence) and same_document_only and ordered
    generation_allowed = bool(decision.accepted and structural_ok)
    status = decision.status
    reasons: list[str] = []

    if decision.status != "sufficient":
        reasons.append(decision.reason)
    if decision.accepted and not evidence:
        reasons.append("accepted_verdict_without_generation_evidence")
    if decision.accepted and not same_document_only:
        reasons.append("authorized_evidence_spans_multiple_documents")
    if decision.accepted and not ordered:
        reasons.append("authorized_evidence_not_ordered")

    # A structural failure closes generation but does not create a competing
    # documentary classification. The original unified status is preserved for
    # audit, while generation_allowed records the effective gate.
    score = round(decision.coverage, 3)
    quality = float((retrieval.get("selection") or {}).get("quality", 0) or 0)
    return EvidenceAssessment(
        status=status,
        score=score,
        reasons=list(dict.fromkeys(reasons)),
        usable_chunks=len(evidence),
        unique_pages=len(pages),
        same_document_only=same_document_only,
        ordered=ordered,
        generation_allowed=generation_allowed,
        internal_knowledge_candidate=not generation_allowed,
        coverage_basis="unified_evidence_verdict",
        retrieval_quality=quality,
        relevance_supported=decision.status in {"sufficient", "partial"},
        canonical_decision=decision.to_dict(),
    )


def safe_partial_response(assessment, retrieval):
    if assessment.status == "partial":
        return "Encontré documentación relacionada, pero no cubre suficientemente la operación solicitada."
    return "No encontré evidencia documental aplicable a la operación solicitada."
