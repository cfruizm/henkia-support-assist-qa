from __future__ import annotations
import re
import unicodedata
from app.domain_registry import PRODUCT_ALIAS_INDEX,PROCESS_ALIAS_INDEX,detect_entities_in_text

_DOMAIN_SIGNAL=re.compile(
    r"\b(?:print(?:er|ing)?|impres(?:ora|ion|ión)|scan(?:ner|ning)?|escane(?:ar|o)|"
    r"spool(?:er)?|cola(?:s)?\s+de\s+impres|driver|controlador(?:es)?|firmware|"
    r"toner|t[oó]ner|tinta|papel|consumible|multifuncional|mfp|mfd|copiadora|"
    r"servidor\s+de\s+impres|puerto\s+de\s+impres|liberaci[oó]n\s+(?:de\s+)?trabajos|"
    r"pin\s+de\s+impres|gesti[oó]n\s+documental|servicio\s+de\s+impres)\b",re.I
)
_DOCUMENT_SIGNAL=re.compile(r"\b(?:documento|manual|gu[ií]a|instructivo)\s+[A-Z]{1,8}\d{2,}(?:[-_]\w+)*",re.I)
_EXEMPT_INTENTS={"social","meta","capabilities","case_history","cancel","escalation"}
_EXEMPT_ACTS={"social","request_capabilities","cancel","escalation"}
_CONTINUITY_ACTS={"follow_up","request_elaboration","answer_to_question","attempt_result"}


def _fold(value):
    return unicodedata.normalize("NFKD",str(value or "")).encode("ascii","ignore").decode().casefold()


def _registered_entities(message):
    return list(dict.fromkeys(
        detect_entities_in_text(str(message or ""),PRODUCT_ALIAS_INDEX)+
        detect_entities_in_text(str(message or ""),PROCESS_ALIAS_INDEX)
    ))


def _known_subjects(before):
    values=[]
    for value in (before.get("active_subject"),):
        if value:values.append(str(value))
    for item in before.get("subject_history") or []:
        if isinstance(item,dict):
            value=item.get("subject") or item.get("canonical_subject") or item.get("value")
        else:value=item
        if value:values.append(str(value))
    pending=before.get("pending_goal") or {}
    details=pending.get("known_details") or {}
    if details.get("subject"):values.append(str(details["subject"]))
    return {_fold(value) for value in values if _fold(value)}


def reconcile_scope(message,understanding,state_before=None):
    """Authorize scope without erasing decisions owned by continuity, case or goal state."""
    u=dict(understanding or {});before=dict(state_before or {})
    original=str(u.get("domain_relevance") or "uncertain").casefold()
    intent=str(u.get("intent") or "unknown").casefold();act=str(u.get("user_act") or "").casefold()
    relation=str(u.get("topic_relation") or "").casefold();origin=str(u.get("subject_origin") or "").casefold()
    reference=str(u.get("reference_relation") or "none").casefold();subject=str(u.get("canonical_subject") or "").strip()
    entities=_registered_entities(message)
    generic_signal=bool(_DOMAIN_SIGNAL.search(str(message or "")) or _DOCUMENT_SIGNAL.search(str(message or "")))
    known_subjects=_known_subjects(before)
    subject_known=bool(subject and _fold(subject) in known_subjects)
    structured_reference=reference in {"current_subject","previous_subject"}
    memory_origin=origin in {"conversation_memory","previous_subject","inherited","current_subject"}
    continuity_valid=bool(
        relation in {"same_topic","same_topic_refinement"}
        and structured_reference
        and (memory_origin or subject_known)
        and (subject_known or bool(before.get("active_subject")) or bool(before.get("subject_history")))
    )
    referential=continuity_valid or (relation=="same_topic" and (memory_origin or structured_reference))
    independent=not continuity_valid and (relation in {"new_topic","independent"} or act in {"new_request","independent_question","topic_change"} or not referential)
    exempt=intent in _EXEMPT_INTENTS or act in _EXEMPT_ACTS
    evidence={
        "registered_entities":entities,"generic_domain_signal":generic_signal,
        "referential":referential,"independent":independent,"explicit_subject":bool(subject),
        "structured_reference":structured_reference,"memory_origin":memory_origin,
        "subject_known":subject_known,"continuity_valid":continuity_valid,
    }
    if exempt:
        return u,{"applied":False,"terminal":False,"reason":"scope_authority_exempt_conversational_act","original_scope":original,"final_scope":original,"evidence":evidence}
    if continuity_valid and original!="out_of_scope":
        return u,{"applied":False,"terminal":False,"reason":"resolved_contextual_continuity_precedes_independent_scope_test","original_scope":original,"final_scope":original,"evidence":evidence}
    if original=="out_of_scope":
        # Scope owns scope and routing only. It must not erase case facts, references,
        # goals or topic decisions owned by other authorities.
        u.update({"domain_relevance":"out_of_scope","should_retrieve":False,"needs_clarification":False,"clarification_target":None,"requested_workflow":"none"})
        return u,{"applied":True,"terminal":True,"reason":"provider_out_of_scope_confirmed","original_scope":original,"final_scope":"out_of_scope","memory_preserved":True,"evidence":evidence}
    if independent and subject and not entities and not generic_signal:
        u.update({"domain_relevance":"out_of_scope","should_retrieve":False,"needs_clarification":False,"clarification_target":None,"requested_workflow":"none"})
        return u,{"applied":True,"terminal":True,"reason":"independent_subject_without_printing_domain_evidence","original_scope":original,"final_scope":"out_of_scope","memory_preserved":True,"evidence":evidence}
    if independent and not subject and not entities and not generic_signal and original=="in_scope":
        u.update({"domain_relevance":"uncertain","should_retrieve":False,"needs_clarification":True,"clarification_target":"relación de la solicitud con el servicio de impresión","requested_workflow":"none"})
        return u,{"applied":True,"terminal":False,"reason":"independent_request_without_domain_object_requires_scope_clarification","original_scope":original,"final_scope":"uncertain","memory_preserved":True,"evidence":evidence}
    return u,{"applied":False,"terminal":False,"reason":"printing_domain_evidence_or_valid_continuity","original_scope":original,"final_scope":str(u.get("domain_relevance") or original),"evidence":evidence}
