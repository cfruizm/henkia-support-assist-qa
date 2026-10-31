"""Session-level KE comparison and provisional assessment metrics."""
from __future__ import annotations
from collections import Counter
from typing import Mapping
def summarize(turns):
    blocks=[t.get("knowledge_comparison") for t in turns if isinstance(t,Mapping) and t.get("knowledge_comparison")]
    successes=[];timeouts=[];errors=[];top=top5=0;statuses=[]
    for b in blocks:
        ke=b.get("henkia_ke") or {};err=ke.get("error") or {};comp=b.get("comparison") or {};assessment=b.get("ke_evidence_assessment") or {}
        if ke.get("http_status")==200:successes.append(float(ke.get("latency_ms") or 0))
        if err.get("timeout_phase"):timeouts.append(err.get("timeout_phase"))
        elif err.get("code"):errors.append(err.get("code"))
        top+=int(bool(comp.get("top_document_match")));top5+=int(bool(comp.get("top5_document_match")))
        if assessment.get("status"):statuses.append(assessment.get("status"))
    attempts=len(blocks)
    return {"schema_version":2,"attempts":attempts,"successes":len(successes),"failures":attempts-len(successes),"success_rate":round(len(successes)/attempts,4) if attempts else None,"average_success_latency_ms":round(sum(successes)/len(successes),3) if successes else None,"min_success_latency_ms":round(min(successes),3) if successes else None,"max_success_latency_ms":round(max(successes),3) if successes else None,"timeout_phases":timeouts,"error_codes":errors,"top_document_matches":top,"top5_document_matches":top5,"assessment_counts":dict(Counter(statuses)),"assessment_affects_publication":False,"candidate_bands_calibrated":False,"published_provider":"local_chroma","compared_provider":"henkia_ke","production_changed":False}
