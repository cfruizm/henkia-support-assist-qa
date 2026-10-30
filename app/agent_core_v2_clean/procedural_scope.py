from __future__ import annotations
from copy import deepcopy
import re
import unicodedata

_GENERIC_PRODUCTS = {"sanitized_support_assets", "internal_support_asset", "unknown", "general"}


def _norm(value):
    return unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode("ascii").casefold()


def _words(value):
    return set(re.findall(r"[a-z0-9][a-z0-9_.-]+", _norm(value)))


def _requested_scope(message, understanding):
    understanding = understanding or {}
    details = understanding.get("goal_updates") or {}
    text = " ".join((str(message or ""), str(understanding.get("current_goal") or ""), " ".join(map(str, details.values()))))
    words = _words(text)
    explicit = set()
    for key in ("product", "platform", "vendor", "manufacturer", "model", "operating_system"):
        value = details.get(key)
        if value:
            explicit.add(_norm(value))
    return {"words": words, "explicit": explicit, "details": details}


def _evidence_scope(item):
    metadata = item.get("metadata") or {}
    values = []
    # vendor and collection_name describe provenance, not a required product.
    for key in ("product", "platform"):
        value = metadata.get(key)
        if value and _norm(value) not in _GENERIC_PRODUCTS:
            values.append(_norm(value))
    title = _norm(item.get("title"))
    return {"values": sorted(set(values)), "title": title}


def _scope_is_requested(scope, request):
    for value in scope["values"]:
        tokens = _words(value.replace("_", " "))
        if value in request["explicit"] or (tokens and tokens.issubset(request["words"])):
            return True
    return False


def constrain_generic_procedure(message, understanding, retrieval):
    """Prevent an unrequested product workflow from answering a generic procedure.

    Product-specific evidence remains available for diagnostics and may be cited as
    an explicitly labelled example, but it cannot authorize a complete generic
    procedure unless the user selected that product or platform.
    """
    clean = deepcopy(retrieval or {})
    evidence = clean.get("generation_evidence") or clean.get("evidence") or []
    request = _requested_scope(message, understanding)
    scoped = []
    neutral = []
    for item in evidence:
        scope = _evidence_scope(item)
        annotated = deepcopy(item)
        annotated["procedural_scope"] = {"evidence_scope": scope["values"], "requested": _scope_is_requested(scope, request), "product_specific": bool(scope["values"])}
        fit = float((annotated.get("semantic_fit") or {}).get("score", 0.0) or 0.0)
        title_terms = _words(scope["title"])
        request_terms = request["words"]
        direct_procedure_match = bool(request_terms and len(request_terms & title_terms) >= 2 and fit >= 0.30)
        annotated["procedural_scope"]["direct_procedure_match"] = direct_procedure_match
        if scope["values"] and not annotated["procedural_scope"]["requested"] and not direct_procedure_match:
            scoped.append(annotated)
        else:
            neutral.append(annotated)
    generic_request = not request["explicit"]
    restricted = bool(generic_request and scoped and not neutral)
    if restricted:
        # Keep only the most operation-relevant extract as a labelled example.
        candidates = sorted(scoped, key=lambda x: float((x.get("semantic_fit") or {}).get("score", 0.0) or 0.0), reverse=True)
        clean["generation_evidence"] = candidates[:1]
        clean["evidence"] = candidates[:1]
    elif generic_request and scoped:
        clean["generation_evidence"] = neutral[:6]
        clean["evidence"] = neutral[:6]
    clean["procedural_scope_guard"] = {
        "generic_request": generic_request,
        "explicit_scope": sorted(request["explicit"]),
        "unrequested_product_evidence_count": len(scoped),
        "neutral_evidence_count": len(neutral),
        "direct_procedure_match_count": sum(1 for x in neutral if (x.get("procedural_scope") or {}).get("direct_procedure_match")),
        "restricted_to_example": restricted,
        "requires_general_guidance": restricted,
        "requires_missing_details": ["manufacturer_or_model", "operating_system"] if restricted else [],
    }
    sf = clean.setdefault("semantic_fit", {})
    if restricted:
        sf["accepted_for_generation"] = False
        sf["low_fit"] = True
        sf["generation_ids"] = [x.get("id") for x in clean["generation_evidence"]]
        sf["generation_count"] = len(clean["generation_evidence"])
        sf["scope_alignment"] = "unrequested_product_only"
    return clean


def scoped_assessment_override(retrieval, assessment):
    guard = (retrieval or {}).get("procedural_scope_guard") or {}
    if not guard.get("restricted_to_example"):
        return assessment
    updated = deepcopy(assessment or {})
    updated.update({
        "status": "partial",
        "generation_allowed": False,
        "internal_knowledge_candidate": True,
        "reasons": list(dict.fromkeys([*(updated.get("reasons") or []), "unrequested_product_scope"])),
    })
    canonical = deepcopy(updated.get("canonical_decision") or {})
    canonical.update({"status": "partial", "generation_mode": "documented_plus_internal", "reason": "unrequested_product_scope", "accepted": False})
    updated["canonical_decision"] = canonical
    return updated
