from __future__ import annotations
from copy import deepcopy
import re
import unicodedata

CONCEPTUAL_INTENT = "conceptual"
_GENERIC = {
    "concept", "concepto", "explicar", "explica", "definir", "definicion",
    "relacion", "relaciona", "entre", "cuales", "existen", "existentes",
    "enumerar", "principales", "general", "procedimiento", "actualizar",
    "impresion", "printing", "operation", "subject", "de", "del", "la",
    "el", "los", "las", "que", "como", "con", "ese", "esa", "esta",
    "este", "para", "por", "una", "uno", "unos", "unas", "print",
    "printer", "impresora", "software", "sistema", "dispositivo",
    "define", "definition", "explain", "function", "relationship", "between",
    "what", "which", "that", "this", "these", "those", "with", "from",
    "into", "about", "does", "and", "the", "for", "are", "exists",
    "existing", "list", "main", "general", "procedure", "update", "device",
}


def _canonical_token(token):
    """Collapse common inflectional plurals without domain vocabulary."""
    if len(token) > 4 and token.endswith("ies"):
        return token[:-3] + "y"
    if len(token) > 4 and token.endswith("es") and not token.endswith(("ses", "xes")):
        return token[:-1]
    if len(token) > 3 and token.endswith("s") and not token.endswith(("ss", "us", "is")):
        return token[:-1]
    return token


def _tokens(value):
    text = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode("ascii").casefold()
    return {
        _canonical_token(x)
        for x in re.findall(r"[a-z0-9]+", text)
        if len(x) > 2 and x not in _GENERIC
    }


def _normalized_text(value):
    return unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode("ascii").casefold()


def _has_conceptual_claim(text, anchors):
    """Detect an explicit definitional/descriptive claim for a single subject.

    Neutral affinity plus noun mention is insufficient. The evidence must state
    what the subject is, means, refers to, consists of, or can be described as.
    Multi-subject relationship questions are governed by joint anchor coverage.
    """
    if len(anchors) != 1:
        return True
    anchor = re.escape(next(iter(anchors)))
    normalized = _normalized_text(text)
    subject = rf"(?:[a-z0-9]+\s+){{0,2}}{anchor}(?:s)?"
    predicates = (
        r"(?:is|are|es|son)\s+(?:an?|un|una|el|la|los|las)\s+[a-z]",
        r"(?:can\s+be|puede(?:n)?\s+ser)\s+(?:[a-z]+\s+){{0,3}}(?:piece|pieza|type|tipo|form|forma|component|componente|system|sistema|process|proceso)",
        r"(?:means?|significa|refers?\s+to|se\s+refiere\s+a|consists?\s+of|consiste\s+en|describes?|describe|translates?|traduce(?:n)?)",
    )
    return any(re.search(rf"\b{subject}\s+{predicate}", normalized) for predicate in predicates)


def _evidence_identity(item):
    metadata = item.get("metadata") or {}
    return (
        metadata.get("content_hash")
        or metadata.get("canonical_url")
        or item.get("source")
        or item.get("url")
        or item.get("id")
    )


def _concept_anchors(understanding):
    understanding = understanding or {}
    updates = understanding.get("goal_updates") or {}
    return _tokens(updates.get("subject")) or _tokens(understanding.get("current_goal"))


def _direct_current_evidence(items, understanding):
    """Authorize evidence only when it covers the requested conceptual scope.

    A single-concept question requires that concept. A multi-concept question
    requires every distinct concept in the same chunk. This avoids presenting
    a driver-only document as proof of the relationship between driver and a
    different concept.
    """
    anchors = _concept_anchors(understanding)
    selected = []
    rejected = []
    seen_identities = set()
    for item in items or []:
        if item.get("carried_from_previous_answer"):
            rejected.append((item, "carried_previous_answer"))
            continue
        fit = item.get("semantic_fit") or {}
        body = " ".join((
            str(item.get("title") or ""),
            str(item.get("text") or ""),
            " ".join(map(str, fit.get("matched_terms") or [])),
        ))
        covered = anchors.intersection(_tokens(body))
        anchor_complete = bool(anchors) and covered == anchors
        intent_affinity = fit.get("intent_affinity")
        intent_aligned = intent_affinity is None or float(intent_affinity) >= 0.0
        explicit_claim = _has_conceptual_claim(body, anchors)
        descriptive_content = any(term in _normalized_text(body) for term in ("proporciona","permite","administra","supervision","gestion","supports","provides","enables","manages"))
        claim_supported = len(anchors) != 1 or explicit_claim or (anchor_complete and descriptive_content) or (
            intent_affinity is not None and float(intent_affinity) > 0.0
        )
        identity = _evidence_identity(item)
        duplicate = identity in seen_identities
        eligible = anchor_complete and intent_aligned and claim_supported and not duplicate
        annotated = deepcopy(item)
        annotated["conceptual_coverage"] = {
            "required_anchors": sorted(anchors),
            "covered_anchors": sorted(covered),
            "anchor_complete": anchor_complete,
            "intent_affinity": intent_affinity,
            "intent_aligned": intent_aligned,
            "explicit_conceptual_claim": explicit_claim,
            "claim_supported": claim_supported,
            "duplicate_evidence": duplicate,
            "complete": eligible,
        }
        if eligible:
            selected.append(annotated)
            seen_identities.add(identity)
        elif duplicate:
            rejected.append((annotated, "duplicate_conceptual_evidence"))
        elif not anchor_complete:
            rejected.append((annotated, "incomplete_concept_coverage"))
        elif not intent_aligned:
            rejected.append((annotated, "conceptual_intent_mismatch"))
        else:
            rejected.append((annotated, "missing_conceptual_claim"))
    return selected[:8], rejected


def _context_without_citation_authority(context):
    context = deepcopy(context or {})
    if not context:
        return {}
    for key in ("source_identities", "source_titles", "cited_ids", "cited_evidence"):
        context[key] = []
    context["citation_eligible"] = False
    context["role"] = "semantic_continuity_only"
    return context


def prepare_conceptual_retrieval(retrieval: dict, boundary, understanding: dict | None = None) -> dict:
    clean = deepcopy(retrieval or {})
    if isinstance(boundary, str):
        boundary = {"relation": boundary, "changed_dimensions": []}
    boundary = boundary or {}
    changed = set(boundary.get("changed_dimensions") or [])
    new_topic = boundary.get("relation") == "new_topic"
    subject_shift = "subject" in changed
    verdict = clean.get("evidence_verdict") or {}
    candidates = clean.get("diagnostic_evidence") or clean.get("evidence") or []
    if verdict.get("accepted") and verdict.get("selected_evidence"):
        current = [deepcopy(x) for x in verdict.get("selected_evidence") or []]
        rejected = []
    elif understanding is None:
        current = [deepcopy(x) for x in candidates if not x.get("carried_from_previous_answer")][:8]
        rejected = []
    else:
        current, rejected = _direct_current_evidence(candidates, understanding)
    previous_context = clean.get("_answer_context") or {}
    current_anchors = _concept_anchors(understanding)
    previous_anchors = _tokens(previous_context.get("goal"))
    # Goal wording changes (definition -> capabilities -> purpose) are refinements,
    # not subject changes. Only the canonical topic boundary may declare a subject shift.
    inferred_subject_shift = False
    if new_topic:
        clean["_answer_context"] = {}
        context_role = "none"
    elif subject_shift:
        clean["_answer_context"] = _context_without_citation_authority(previous_context)
        context_role = "semantic_continuity_only"
    else:
        context_role = "eligible"
    clean["generation_evidence"] = current
    clean["evidence"] = current
    sf = clean.setdefault("semantic_fit", {})
    sf.update({
        "carried_previous_evidence": 0,
        "previous_answer_sources_used": False,
        "previous_evidence_primary_eligible": False if (new_topic or subject_shift) else sf.get("previous_evidence_primary_eligible", False),
        "previous_evidence_role": context_role,
        "generation_ids": [x.get("id") for x in current],
        "generation_count": len(current),
        "accepted_for_generation": bool(current),
        "low_fit": not bool(current),
        "conceptual_coverage_policy": "canonical_anchors_claim_entailment_intent_and_deduplication",
    })
    clean["conceptual_boundary"] = {
        "isolated": new_topic,
        "answer_context_removed": new_topic,
        "subject_scope_changed": subject_shift,
        "subject_shift_inferred": inferred_subject_shift,
        "current_concept_anchors": sorted(current_anchors),
        "previous_concept_anchors": sorted(previous_anchors),
        "conversation_context_preserved": bool(subject_shift and previous_context),
        "previous_context_citation_eligible": not (new_topic or subject_shift),
        "direct_evidence_count": len(current),
        "dropped_tangential_count": max(0, len(candidates) - len(current)),
        "rejected_incomplete_coverage_ids": [x.get("id") for x, reason in rejected if reason == "incomplete_concept_coverage"],
        "rejected_intent_mismatch_ids": [x.get("id") for x, reason in rejected if reason == "conceptual_intent_mismatch"],
        "rejected_missing_claim_ids": [x.get("id") for x, reason in rejected if reason == "missing_conceptual_claim"],
        "rejected_duplicate_ids": [x.get("id") for x, reason in rejected if reason == "duplicate_conceptual_evidence"],
    }
    return clean


def conceptual_assessment(retrieval: dict) -> dict:
    evidence = retrieval.get("generation_evidence") or []
    documented = bool(evidence)
    return {
        "status": "partial" if documented else "insufficient",
        "score": 0.0,
        "reasons": ["conceptual_answer_requires_controlled_synthesis", *([] if documented else ["no_direct_conceptual_evidence"])],
        "usable_chunks": len(evidence),
        "generation_allowed": False,
        "internal_knowledge_candidate": True,
        "canonical_decision": {
            "status": "partial" if documented else "insufficient",
            "generation_mode": "documented_plus_internal" if documented else "internal_only",
            "reason": "conceptual_controlled_synthesis",
            "selected_ids": [x.get("id") for x in evidence],
            "accepted": False,
        },
    }


def must_preempt_documented_answer(understanding: dict) -> bool:
    return (understanding or {}).get("intent") == CONCEPTUAL_INTENT
