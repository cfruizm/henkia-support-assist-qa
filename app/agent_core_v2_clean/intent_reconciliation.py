from __future__ import annotations
from copy import deepcopy
import re
import unicodedata

# Generic semantic roles only. These terms describe request form, never a
# product, document, customer, page, URL, port, or validation-campaign phrase.
_PROCEDURE_OBJECTS = {
    "procedure", "procedures", "procedimiento", "procedimientos",
    "process", "processes", "proceso", "procesos",
    "workflow", "workflows", "flujo", "flujos",
    "steps", "step", "pasos", "paso",
    "instructions", "instruction", "instrucciones", "instruccion",
    "method", "methods", "metodo", "metodos",
}
_PROCEDURE_REQUESTS = {
    "describe", "describes", "describir", "describe",
    "explain", "explains", "explicar", "explica",
    "detail", "details", "detallar", "detalla",
    "show", "shows", "mostrar", "muestra",
    "list", "lists", "listar", "lista",
    "execute", "perform", "run", "ejecutar", "realizar",
}
_DEFINITION_ONLY = {
    "definition", "definicion", "meaning", "significado",
    "concept", "concepto",
}


def _norm(value):
    return unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode().casefold()


def _tokens(value):
    return set(re.findall(r"[a-z0-9]+", _norm(value)))


def _document_context(retrieval):
    retrieval = retrieval or {}
    resolution = retrieval.get("document_resolution") or {}
    exact = retrieval.get("exact_document_match") or {}
    expansion = retrieval.get("procedural_expansion") or {}
    exact_document = resolution.get("status") == "exact_match" or bool(exact.get("matched"))
    ordered_expansion = bool(
        expansion.get("ok")
        and expansion.get("same_document_only")
        and expansion.get("ordered")
        and (expansion.get("count") or len(expansion.get("pages") or []))
    )
    return exact_document, ordered_expansion, expansion


def reconcile_procedural_intent(result, store=None):
    """Repair a conceptual/procedural contradiction after document retrieval.

    The provider remains authoritative unless all of these independent signals
    agree: an initial conceptual request, an explicit procedural semantic role
    in the current goal, an exact resolved document, and an ordered same-document
    expansion. The function never promotes requirements, troubleshooting,
    follow-ups, literal-value requests, or generic product explanations.
    """
    out = result
    understanding = deepcopy(out.get("understanding") or {})
    original = str(understanding.get("intent") or "").casefold()
    relation = str(understanding.get("topic_relation") or "").casefold()
    act = str(understanding.get("user_act") or "").casefold()
    goal = str(understanding.get("current_goal") or "")
    subject = str(understanding.get("canonical_subject") or "").strip()
    terms = _tokens(goal)
    object_hits = sorted(terms & _PROCEDURE_OBJECTS)
    request_hits = sorted(terms & _PROCEDURE_REQUESTS)
    definition_hits = sorted(terms & _DEFINITION_ONLY)
    exact_document, ordered_expansion, expansion = _document_context(out.get("retrieval") or {})
    initial_request = relation == "new_topic" and act == "new_request"
    explicit_procedure_goal = bool(object_hits and request_hits and not definition_hits)
    applied = bool(
        original == "conceptual"
        and initial_request
        and subject
        and not understanding.get("case_updates")
        and not understanding.get("needs_clarification")
        and explicit_procedure_goal
        and exact_document
        and ordered_expansion
    )
    diagnostic = {
        "schema_version": 1,
        "applied": applied,
        "original_intent": original or None,
        "effective_intent": "procedural" if applied else original or None,
        "reason": "explicit_document_procedure_goal" if applied else "reconciliation_conditions_not_met",
        "signals": {
            "initial_request": initial_request,
            "canonical_subject_present": bool(subject),
            "procedure_object_hits": object_hits,
            "procedure_request_hits": request_hits,
            "definition_only_hits": definition_hits,
            "exact_document_context": exact_document,
            "procedural_expansion_valid": ordered_expansion,
            "same_document_only": bool(expansion.get("same_document_only")),
            "ordered": bool(expansion.get("ordered")),
        },
    }
    out["intent_reconciliation"] = diagnostic
    if not applied:
        return out
    understanding["intent"] = "procedural"
    understanding["reasoning_summary"] = "Document procedure goal reconciled after exact retrieval."
    out["understanding"] = understanding
    retrieval = out.get("retrieval") or {}
    query = retrieval.get("query") or {}
    fields = query.get("fields") or {}
    fields["intent"] = "procedural"
    query["fields"] = fields
    retrieval["query"] = query
    # The evidence verdict was originally calculated with the provider's
    # conceptual label. Recompute the existing unified authority with the
    # effective procedural intent so the dedicated route does not consume a
    # stale conceptual verdict. This reuses the current authority module and
    # does not create a second evidence policy.
    from .unified_evidence_authority import apply_unified_evidence_verdict
    from .documentation_limitation import classify as classify_documentation_limitation
    retrieval = apply_unified_evidence_verdict(
        retrieval,
        str(out.get("input") or ""),
        understanding,
    )
    retrieval["documentation_limitation"] = classify_documentation_limitation(retrieval)
    out["retrieval"] = retrieval
    diagnostic["authority_recomputed"] = True
    diagnostic["effective_verdict_status"] = str((retrieval.get("evidence_verdict") or {}).get("status") or "")
    diagnostic["effective_verdict_reason"] = str((retrieval.get("evidence_verdict") or {}).get("reason") or "")
    normalization = out.setdefault("goal_update_normalization", {})
    corrections = normalization.setdefault("structural_corrections", [])
    if "conceptual_to_procedural_exact_document_reconciliation" not in corrections:
        corrections.append("conceptual_to_procedural_exact_document_reconciliation")
    out.setdefault("functional_events", []).append({
        "type": "intent_reconciliation",
        "from_intent": original,
        "to_intent": "procedural",
        "reason": "explicit_document_procedure_goal",
    })
    memory = (store or {}).get("memory") if isinstance(store, dict) else None
    if memory is not None and getattr(memory, "pending_goal", None) is not None:
        memory.pending_goal.intent = "procedural"
        out["state_after"] = deepcopy(memory.to_dict())
    return out
