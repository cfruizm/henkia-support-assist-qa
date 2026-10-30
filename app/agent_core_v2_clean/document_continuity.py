from __future__ import annotations
from copy import deepcopy

_CONTINUITY_RELATIONS={"same_topic","same_topic_refinement","return_to_previous"}
_PRIMARY_ROLES={"primary","eligible"}
_REFERENCE_RELATIONS={"current_subject","previous_subject"}

def continuity_authority(understanding,boundary,answer_context):
    """Resolve prior-document authority from structured conversation state only.

    This module deliberately does not inspect user wording, product names, document
    titles, operations, or campaign examples. It uses the semantic contract already
    produced by understanding and topic-boundary reconciliation.
    """
    u=dict(understanding or {})
    b=dict(boundary or {})
    ctx=deepcopy(answer_context or {})
    relation=str(b.get("relation") or u.get("topic_relation") or "")
    role=str(b.get("previous_evidence_role") or "")
    reference=str(u.get("reference_relation") or "none")
    same_topic=relation in _CONTINUITY_RELATIONS
    current_subject=str(u.get("canonical_subject") or "").strip().casefold()
    context_subject=str(ctx.get("canonical_subject") or ctx.get("subject") or "").strip().casefold()
    explicit_subject_switch=(str(u.get("subject_origin") or "").casefold()=="current_message" and bool(current_subject and context_subject) and current_subject!=context_subject)
    if explicit_subject_switch:
        same_topic=False;role="none";reference="none"
    primary=bool(ctx and same_topic and role in _PRIMARY_ROLES and (
        reference in _REFERENCE_RELATIONS or str(u.get("topic_relation") or "") in _CONTINUITY_RELATIONS
    ))
    sources=[]
    if primary:
        for value in ctx.get("source_identities") or []:
            value=str(value or "").strip()
            if value and value not in sources:sources.append(value)
    return {
        "same_topic":same_topic,
        "primary":primary,
        "relation":relation,
        "previous_evidence_role":"primary" if primary else (role or "none"),
        "preferred_sources":sources,
        "answer_context":ctx if same_topic else {},
        "reason":"structured_same_topic_document_continuity" if primary else "no_primary_document_continuity",
    }
