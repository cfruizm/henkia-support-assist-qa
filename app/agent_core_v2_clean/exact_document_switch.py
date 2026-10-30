from __future__ import annotations
from copy import deepcopy
import re
import unicodedata


def _norm(value):
    return " ".join(re.findall(r"[a-z0-9]+", unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode().casefold()))


def _active_sources(answer_context):
    context=answer_context or {}
    return {str(x).strip() for x in context.get("source_identities") or [] if str(x).strip()}


def _resolved_title(retrieval):
    resolution=(retrieval or {}).get("document_resolution") or {}
    matches=resolution.get("matches") or []
    if not matches:return None
    first=matches[0] or {}
    return str(first.get("title") or ((first.get("metadata") or {}).get("title")) or "").strip() or None


def reconcile_exact_document_switch(result, retrieval, message, store):
    """Give an exact current-message document switch precedence over inherited continuity.

    The resolver remains the sole authority for document identity. This function
    only repairs a contradictory conversational classification when the resolved
    source differs from the active document and the resolver's exact identifier
    is visibly present in the current message.
    """
    out=result
    raw=retrieval or {}
    selection=raw.get("selection") or {}
    exact=raw.get("exact_document_match") or {}
    resolution=raw.get("document_resolution") or {}
    identifiers=[_norm(x) for x in (exact.get("identifiers") or resolution.get("identifiers") or []) if _norm(x)]
    message_norm=_norm(message)
    identifier_in_message=bool(identifiers and any(value in message_norm for value in identifiers))
    source=str(exact.get("source") or "").strip()
    context=(store or {}).get("answer_context") or {}
    active_sources=_active_sources(context)
    source_changed=bool(source and active_sources and source not in active_sources)
    u=out.get("understanding") or {}
    inherited=str(u.get("subject_origin") or "").casefold() in {"conversation_memory","previous_subject","inherited"} or str(u.get("reference_relation") or "none").casefold() not in {"","none"}
    eligible=(
        selection.get("chosen_mode")=="deterministic_document_resolver"
        and bool(selection.get("exact_identifier_match"))
        and bool(exact.get("matched"))
        and identifier_in_message
        and source_changed
        and inherited
    )
    diagnostic={
        "applied":False,
        "reason":"exact_document_switch_not_required",
        "exact_identifier_match":bool(selection.get("exact_identifier_match")),
        "identifier_in_current_message":identifier_in_message,
        "resolved_source":source or None,
        "active_sources":sorted(active_sources),
        "active_document_changed":source_changed,
    }
    if not eligible:return out,diagnostic
    title=_resolved_title(raw) or str((resolution.get("matches") or [{}])[0].get("source") or source).rsplit("/",1)[-1]
    prior_subject=u.get("canonical_subject")
    repaired=deepcopy(u)
    repaired.update({
        "user_act":"new_request",
        "topic_relation":"new_topic",
        "canonical_subject":title,
        "subject_origin":"current_message",
        "reference_relation":"none",
    })
    goal_updates=dict(repaired.get("goal_updates") or {})
    goal_updates["subject"]=title
    goal_updates.pop("document_object",None)
    repaired["goal_updates"]=goal_updates
    out["understanding"]=repaired
    out["topic_boundary"]={
        "relation":"new_topic",
        "reason":"exact_current_message_document_switch",
        "shared_ratio":0.0,
        "changed_dimensions":["subject","document"],
        "introduced_dimensions":[],
        "previous_evidence_role":"none",
    }
    memory=(store or {}).get("memory")
    if memory is not None:
        memory.active_subject=title
        if getattr(memory,"pending_goal",None) is not None:
            memory.pending_goal.summary=repaired.get("current_goal") or memory.pending_goal.summary
            memory.pending_goal.intent=repaired.get("intent") or memory.pending_goal.intent
            memory.pending_goal.known_details={**dict(memory.pending_goal.known_details or {}),"subject":title}
        out["state_after"]=deepcopy(memory.to_dict())
    diagnostic.update({
        "applied":True,
        "reason":"exact_current_message_document_overrode_inherited_continuity",
        "prior_subject":prior_subject,
        "resolved_document":title,
        "previous_continuity_suppressed":True,
    })
    out.setdefault("functional_events",[]).append({"type":"exact_document_switch_reconciled",**diagnostic})
    normalization=out.setdefault("goal_update_normalization",{})
    corrections=normalization.setdefault("structural_corrections",[])
    if "exact_document_switch_reconciled" not in corrections:corrections.append("exact_document_switch_reconciled")
    return out,diagnostic
