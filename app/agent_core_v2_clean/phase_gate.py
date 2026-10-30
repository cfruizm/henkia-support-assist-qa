from __future__ import annotations

def assess_internal_phase(session: dict) -> dict:
    turns=session.get('turns') or []; findings=[]
    for i,t in enumerate(turns,1):
        a=t.get('answer') or {}; ik=t.get('internal_knowledge') or {}; v=ik.get('validation') or {}
        if a.get('mode')=='controlled_internal_knowledge':
            if a.get('finish_reason')!='stop':findings.append({'turn':i,'code':'internal_not_complete'})
            if not v.get('separation_valid'):findings.append({'turn':i,'code':'separation_invalid'})
            if v.get('internal_citations'):findings.append({'turn':i,'code':'internal_section_has_citations'})
        if t.get('turn_metrics',{}).get('calls',0)==0 and a.get('mode')=='controlled_internal_knowledge' and not ik.get('cache_hit'):
            findings.append({'turn':i,'code':'zero_call_without_internal_cache'})
    telemetry=session.get('telemetry') or {}
    unknown=(telemetry.get('by_purpose') or {}).get('unknown')
    if unknown:findings.append({'turn':None,'code':'telemetry_unknown_purpose','detail':unknown})
    return {'gate':'phase2e_internal_knowledge_v1','approved':not findings,'findings':findings,'checked_turns':len(turns)}
