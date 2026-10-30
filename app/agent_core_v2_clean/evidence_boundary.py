from __future__ import annotations
from copy import deepcopy
import re

_CITATION_GROUP = re.compile(r"\[((?:R\d+\s*,\s*)+R\d+)\]")

def current_turn_evidence(retrieval: dict) -> list[dict]:
    items = retrieval.get("diagnostic_evidence") or retrieval.get("evidence") or []
    return [deepcopy(x) for x in items if not x.get("carried_from_previous_answer")]

def enforce_evidence_boundary(retrieval: dict, relation: str) -> dict:
    if relation not in {"new_topic", "same_topic_changed_scope"}:
        return retrieval
    current = current_turn_evidence(retrieval)
    retrieval["generation_evidence"] = current[:8]
    retrieval["evidence"] = current[:8]
    sf = retrieval.setdefault("semantic_fit", {})
    sf.update({
        "carried_previous_evidence": 0,
        "previous_answer_sources_used": False,
        "previous_evidence_primary_eligible": False,
        "previous_evidence_role": "none" if relation == "new_topic" else "comparison_only",
        "generation_ids": [x.get("id") for x in current[:8]],
        "generation_count": len(current[:8]),
        "selected_group_ids": [x.get("id") for x in current[:8]],
        "selected_document": (current[0].get("source") or current[0].get("url")) if current else None,
        "accepted_for_generation": bool(current),
        "low_fit": not bool(current),
    })
    retrieval["boundary_filter"] = {"relation": relation, "current_evidence_count": len(current), "carried_removed": True, "generation_allowed_from_current": bool(current)}
    return retrieval

def normalize_citation_groups(text: str) -> str:
    return _CITATION_GROUP.sub(lambda m: "".join(f"[{x.strip()}]" for x in m.group(1).split(",")), text or "")

def scoped_generation_instruction(boundary: dict) -> str:
    if (boundary or {}).get("relation") != "same_topic_changed_scope":
        return ""
    return ("Trata las fuentes recuperadas como alternativas documentadas del alcance actual. "
            "No afirmes que una fuente representa todas las plataformas o productos existentes. "
            "No interpretes un alcance generico como seleccion explicita de una alternativa. "
            "Si falta el nombre exacto, presenta la alternativa encontrada como posibilidad y pide ese unico dato.")
