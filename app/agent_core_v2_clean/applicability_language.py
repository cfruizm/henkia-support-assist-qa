from __future__ import annotations
import re

_CONDITION_MARKERS=(
    "si el entorno", "si la configuración", "si el controlador", "si los trabajos",
    "si aplica", "en caso de que", "cuando el entorno", "if the environment",
    "if the configuration", "if the driver", "if the jobs", "if applicable",
)
_VERIFY_FIRST_MARKERS=(
    "verifica primero", "valida primero", "confirma primero", "comprueba primero",
    "antes de aplicar", "antes de realizar", "before applying", "verify first",
    "validate first", "confirm first", "check first",
)
_OVERCLAIM_PATTERNS=(
    r"\b(?:la|el) causa probable es\b",
    r"\bel problema se debe a\b",
    r"\bla causa es\b",
    r"\bthe probable cause is\b",
    r"\bthe issue is caused by\b",
)
_DIRECT_STEP_PATTERNS=(
    r"\bel siguiente paso(?: documentado)? es\b",
    r"\bla siguiente acción(?: documentada)? es\b",
    r"\besta acción es necesaria\b",
    r"\bthe next documented step is\b",
    r"\bthe next step is\b",
    r"\bthis action is required\b",
)
_SOURCE_MARKERS=("**fuente documental:**", "**documentary source:**")


def _contains_any(value, patterns):
    return any(re.search(pattern, value, re.I) for pattern in patterns)


def _is_source(paragraph):
    low=paragraph.casefold().strip()
    return any(low.startswith(marker) for marker in _SOURCE_MARKERS)


def normalize_conditional_applicability(text):
    """Normalize a response only when the response itself says applicability is unverified.

    The function is domain-neutral. It does not infer prerequisites, alter cited procedures,
    or manufacture troubleshooting. It uses an explicit verify-first statement already
    generated in the answer as the authority to remove incompatible causal certainty,
    move verification before actions, and condition the action group.
    """
    value=str(text or "").strip()
    paragraphs=[x.strip() for x in re.split(r"\n\s*\n",value) if x.strip()]
    if len(paragraphs)<2:
        return value,False,{"reason":"insufficient_structure"}
    verification=[p for p in paragraphs if any(marker in p.casefold() for marker in _VERIFY_FIRST_MARKERS)]
    condition_present=any(any(marker in p.casefold() for marker in _CONDITION_MARKERS) for p in paragraphs)
    if not verification:
        return value,False,{"reason":"no_explicit_verify_first_authority","condition_detected":condition_present}
    source=[p for p in paragraphs if _is_source(p)]
    body=[p for p in paragraphs if p not in verification and p not in source]
    removed_causal=[];direct_indices=[];kept=[]
    for paragraph in body:
        low=paragraph.casefold()
        if _contains_any(low,_OVERCLAIM_PATTERNS):
            removed_causal.append(paragraph);continue
        if _contains_any(low,_DIRECT_STEP_PATTERNS):
            direct_indices.append(len(kept));continue
        kept.append(paragraph)
    if not removed_causal and not direct_indices:
        return value,False,{"reason":"no_conflicting_claim_or_action","condition_detected":condition_present,"verification_detected":True}
    intro=verification[0]
    conditional_bridge="Si la verificación confirma alguna de las condiciones documentadas, aplica únicamente la alternativa correspondiente:"
    # Verification must precede any conditional change. The bridge replaces, rather than
    # supplements, an unconditional 'next step' introduction.
    repaired=[intro]
    if direct_indices or kept:
        repaired.append(conditional_bridge)
    repaired.extend(kept)
    repaired.extend(source)
    return "\n\n".join(repaired).strip(),True,{
        "reason":"verification_moved_before_conditional_actions",
        "condition_detected":condition_present,
        "verification_detected":True,
        "removed_causal_claims":len(removed_causal),
        "removed_direct_introductions":len(direct_indices),
        "procedural_paragraphs_preserved":len(kept),
    }

# Backward-compatible entry point used by the documented composer.
def guard_unconfirmed_applicability(text):
    return normalize_conditional_applicability(text)
