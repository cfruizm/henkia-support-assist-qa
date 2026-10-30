from __future__ import annotations

RISK_POLICY_VERSION="guidance_integrity_v4_compact_authority"

def _text(value,limit=280):
    return " ".join(str(value or "").split()).strip()[:limit]

def _case(retrieval):
    context=(retrieval or {}).get("_case_context") or {}
    return {"subject":_text(context.get("subject"),120) or None,"symptoms":[_text(x,160) for x in context.get("symptoms") or [] if _text(x)][-6:],"observations":[_text(x,160) for x in context.get("observations") or [] if _text(x)][-6:],"affected_scope":_text(context.get("affected_scope"),80) or None}

def _attempts(retrieval):
    rows=[];context=(retrieval or {}).get("_case_context") or {}
    for item in list(context.get("attempts") or [])[-4:]:
        action=_text((item or {}).get("action"))
        if action:rows.append({"action":action,"result":_text((item or {}).get("result")) or None,"outcome":_text((item or {}).get("outcome"),40) or "unknown"})
    return rows

def _guidance(retrieval):
    previous=(retrieval or {}).get("_answer_context") or {};rows=[];seen=set()
    for item in list(previous.get("delivered_guidance") or [])[-6:]:
        action=_text((item or {}).get("action"));key=_text((item or {}).get("check_key"),120).casefold();identity=key or action.casefold()
        if not action or identity in seen:continue
        seen.add(identity);row={"action":action}
        if key:row["check_key"]=key
        rows.append(row)
    return rows[-4:]

def _norm_subject(value):
    import unicodedata
    return " ".join(unicodedata.normalize("NFKD",str(value or "")).encode("ascii","ignore").decode().casefold().split())

def _subject_scope(retrieval):
    retrieval=retrieval or {};query=((retrieval.get("query") or {}).get("fields") or {})
    current=query.get("canonical_subject") or query.get("subject") or query.get("product")
    if not current:
        current=((retrieval.get("_answer_context") or {}).get("active_subject"))
    case=((retrieval.get("_case_context") or {}).get("subject"))
    current_norm=_norm_subject(current);case_norm=_norm_subject(case)
    compatible=not current_norm or not case_norm or current_norm==case_norm
    return {"current_subject":str(current or "").strip() or None,"case_subject":str(case or "").strip() or None,"compatible":compatible}

def build_guidance_integrity_contract(retrieval):
    scope=_subject_scope(retrieval)
    facts=_case(retrieval) if scope["compatible"] else []
    attempts=_attempts(retrieval) if scope["compatible"] else []
    guidance=_guidance(retrieval) if scope["compatible"] else []
    return {
      "schema_version":3,"policy_version":RISK_POLICY_VERSION,
      "subject_scope":scope,
      "cross_subject_context_filtered":not scope["compatible"],
      "confirmed_case_facts":facts,
      "user_confirmed_attempts":attempts,
      "assistant_delivered_guidance":guidance,
      "authority_rules":[
        "Only user-confirmed facts and attempts are confirmed.",
        "Prior assistant guidance is pending unless the user confirms execution.",
        "A failed attempt confirms only non-resolution; it does not confirm another cause.",
        "Document conditions and hypotheses remain unconfirmed until the user confirms them."
      ],
      "high_impact_action_rule":"For actions with broad impact, data/configuration risk, security changes or difficult rollback, state applicability, impact and safeguards; otherwise offer escalation."
    }

def integrity_diagnostic(contract):
    return {"policy_version":contract.get("policy_version"),"confirmed_attempt_count":len(contract.get("user_confirmed_attempts") or []),"delivered_guidance_count":len(contract.get("assistant_delivered_guidance") or []),"confirmed_and_delivered_separated":True,"disruptive_guidance_guard_enabled":True,"compact_contract":True,"subject_scope":contract.get("subject_scope") or {},"cross_subject_context_filtered":bool(contract.get("cross_subject_context_filtered"))}
