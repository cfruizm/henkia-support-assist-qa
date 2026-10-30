from __future__ import annotations
from copy import deepcopy
import re
import unicodedata

FIELDS = (
    "user_act", "intent", "topic_relation", "current_goal",
    "canonical_subject", "subject_origin", "reference_relation",
    "goal_updates", "should_retrieve", "domain_relevance",
)


def _norm(value):
    return unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode().casefold()


def _tokens(value):
    return {token for token in re.findall(r"[a-z0-9]+", _norm(value)) if len(token) > 2}


def snapshot(value):
    if hasattr(value, "to_dict"):
        value = value.to_dict()
    value = dict(value or {})
    return {field: deepcopy(value.get(field)) for field in FIELDS}


def _changes(previous, current):
    changes = {}
    for field in FIELDS:
        old = deepcopy((previous or {}).get(field))
        new = deepcopy((current or {}).get(field))
        if old != new:
            changes[field] = {"before": old, "after": new}
    return changes


def _event_index(events):
    grouped = {}
    for event in list(events or []):
        event = deepcopy(event or {})
        event_type = str(event.get("type") or "untyped_event")
        grouped.setdefault(event_type, []).append(event)
    return grouped


def decision_trace(stages, before, boundary, entity, events):
    """Build an observational decision ledger without changing runtime behavior."""
    stages = [(name, snapshot(value)) for name, value in stages]
    fields = {}
    transitions = []
    conflicts = []
    event_index = _event_index(events)

    for field in FIELDS:
        history = []
        marker = object()
        for name, payload in stages:
            value = deepcopy(payload.get(field))
            if value != marker:
                history.append({"stage": name, "value": value})
                marker = value
        writers = [item["stage"] for item in history[1:]]
        fields[field] = {
            "provider_value": stages[0][1].get(field) if stages else None,
            "final_value": stages[-1][1].get(field) if stages else None,
            "changed": len(history) > 1,
            "winning_stage": history[-1]["stage"] if history else None,
            "writers": writers,
            "write_count": len(writers),
            "multi_writer": len(set(writers)) > 1,
            "history": history,
        }
        if len(set(writers)) > 1:
            conflicts.append({
                "type": "multiple_components_wrote_field",
                "field": field,
                "writers": list(dict.fromkeys(writers)),
                "winning_stage": history[-1]["stage"],
                "final_value": deepcopy(history[-1]["value"]),
            })

    for index, (name, payload) in enumerate(stages):
        previous_payload = stages[index - 1][1] if index else {}
        changes = _changes(previous_payload, payload) if index else {}
        reason_events = event_index.get(name, [])
        # Some runtime event names differ from stage names. Keep all candidates visible
        # rather than guessing a semantic mapping in the instrumentation layer.
        transitions.append({
            "sequence": index + 1,
            "component": name,
            "input_snapshot": deepcopy(previous_payload) if index else None,
            "output_snapshot": deepcopy(payload),
            "accepted_changes": changes,
            "changed_fields": sorted(changes),
            "related_events": reason_events,
            "terminal_signal": any(bool(event.get("terminal")) for event in reason_events),
        })

    provider = stages[0][1] if stages else {}
    final = stages[-1][1] if stages else {}
    previous_subject = str((before or {}).get("active_subject") or "") or None
    final_subject = str(final.get("canonical_subject") or "") or None
    reference = str(final.get("reference_relation") or "none")
    boundary = dict(boundary or {})
    contradictions = []

    if provider.get("topic_relation") in {"new_topic", "independent"} and final.get("topic_relation") in {"same_topic", "same_topic_refinement"}:
        contradictions.append("provider_new_topic_overridden_to_continuity")
    if reference == "none" and previous_subject and final_subject == previous_subject:
        contradictions.append("unreferenced_previous_subject_carried")
    if reference == "none" and boundary.get("previous_evidence_role") in {"primary", "eligible"}:
        contradictions.append("primary_previous_evidence_without_structured_reference")

    return {
        "schema_version": 2,
        "observational_only": True,
        "stages": [{"stage": name, "understanding": payload} for name, payload in stages],
        "decision_ledger": {
            "schema_version": "1.0",
            "observational_only": True,
            "initial_state": deepcopy(stages[0][1]) if stages else {},
            "transitions": transitions,
            "final_state": deepcopy(final),
            "field_winners": {field: data.get("winning_stage") for field, data in fields.items()},
            "conflicts": conflicts,
            "unmatched_events": [deepcopy(event) for event in list(events or []) if str((event or {}).get("type") or "") not in {name for name, _ in stages}],
        },
        "fields": fields,
        "previous_state": {
            "active_subject": previous_subject,
            "pending_goal": deepcopy((before or {}).get("pending_goal") or {}),
            "support_case_status": ((before or {}).get("support_case") or {}).get("status"),
        },
        "entity_frame": deepcopy(entity or {}),
        "boundary": boundary,
        "event_types": [str((event or {}).get("type") or "") for event in events or []],
        "contradictions": contradictions,
    }

def attach_retrieval(result,retrieval,message):
 u=dict(result.get("understanding") or {});boundary=dict(retrieval.get("pre_retrieval_boundary") or result.get("topic_boundary") or {});verdict=dict(retrieval.get("evidence_verdict") or {});evidence=list(retrieval.get("generation_evidence") or retrieval.get("evidence") or []);requested=_tokens(" ".join(str(x or "") for x in (message,u.get("current_goal"),u.get("canonical_subject"))));align=[]
 for item in evidence:
  title=_tokens(item.get("title"));content=_tokens(item.get("text"));align.append({"evidence_id":item.get("id"),"title":item.get("title"),"page":item.get("page"),"document_identity":str(item.get("url") or item.get("source") or ""),"title_hits":sorted(requested&title),"content_hits":sorted(requested&content),"lexical_content_coverage":round(len(requested&(title|content))/max(1,len(requested)),4),"semantic_fit":deepcopy(item.get("semantic_fit") or {}),"carried_from_previous_answer":bool(item.get("carried_from_previous_answer"))})
 before=(((result.get("state_before") or {}).get("pending_goal") or {}).get("known_details") or {});after=(((result.get("state_after") or {}).get("pending_goal") or {}).get("known_details") or {});mt=_tokens(message);carry=[]
 for field in sorted(set(before)|set(after)):
  if before.get(field) is not None and before.get(field)==after.get(field):
   vt=_tokens(before[field]);carry.append({"field":field,"value":deepcopy(after[field]),"referenced_by_current_message":bool(vt and len(vt&mt)/len(vt)>=.60),"carried":True})
 contr=[]
 if verdict.get("status")=="sufficient" and float(verdict.get("coverage") or 0)<.75:contr.append("sufficient_verdict_with_low_reported_coverage")
 if verdict.get("status")=="sufficient" and align and max(x["lexical_content_coverage"] for x in align)<.20:contr.append("sufficient_verdict_with_low_current_request_alignment")
 if boundary.get("previous_evidence_role")=="primary" and str(u.get("reference_relation") or "none")=="none":contr.append("primary_document_continuity_without_structured_reference")
 retrieval["decision_observability"]={"schema_version":1,"observational_only":True,"request":{"message":message,"goal":u.get("current_goal"),"subject":u.get("canonical_subject"),"reference_relation":u.get("reference_relation")},"boundary":boundary,"verdict":{"status":verdict.get("status"),"mode":verdict.get("mode"),"accepted":verdict.get("accepted"),"reason":verdict.get("reason"),"coverage":verdict.get("coverage"),"document_ids":deepcopy(verdict.get("document_ids") or []),"evidence_ids":deepcopy(verdict.get("evidence_ids") or [])},"evidence_alignment":align,"state_carry_audit":carry,"continuity_indicators":{"previous_evidence_role":boundary.get("previous_evidence_role"),"active_document_reused":bool((retrieval.get("selection") or {}).get("active_document_reused")),"preferred_document_locked":bool((retrieval.get("selection") or {}).get("preferred_document_locked")),"carried_previous_evidence":((retrieval.get("semantic_fit") or {}).get("carried_previous_evidence"))},"contradictions":contr}
 trace=dict(result.get("decision_trace") or {});combined=list(trace.get("contradictions") or [])
 for item in contr:
  if item not in combined:combined.append(item)
 trace["retrieval_observability_summary"]={"contradictions":contr,"selected_evidence_count":len(evidence),"verdict_status":verdict.get("status"),"verdict_coverage":verdict.get("coverage")};trace["contradictions"]=combined;result["decision_trace"]=trace;return retrieval
