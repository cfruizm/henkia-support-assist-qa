"""Observational sufficiency calibration for Knowledge Engine evidence.

KE-02 never publishes, rejects, or promotes evidence. It only records features
and a provisional classification for later calibration against labelled tests.
"""
from __future__ import annotations
import re
import statistics
import unicodedata
from typing import Any, Mapping

SCHEMA_VERSION=1
# Generic Spanish/English function words only. No products, vendors, or test phrases.
_STOP={"a","al","and","antes","como","con","cual","cuales","de","del","el","en","es","esta","este","for","how","la","las","lo","los","of","o","para","por","que","se","the","to","un","una","unos","unas","y"}

def _m(v:Any)->dict:return dict(v) if isinstance(v,Mapping) else {}
def _text(v:Any)->str:return " ".join(str(v or "").split())
def _tokens(v:Any)->set[str]:
    text=unicodedata.normalize("NFKD",_text(v)).encode("ascii","ignore").decode("ascii").casefold()
    return {x for x in re.findall(r"[a-z0-9]+",text) if len(x)>1 and x not in _STOP}
def _number(v):
    try:return float(v) if v is not None else None
    except Exception:return None

def assess(ke_result:Mapping[str,Any],understanding:Mapping[str,Any],query:str,low_score:float=.45,high_score:float=.70)->dict:
    rows=list(_m(ke_result).get("results") or [])
    scores=[x for x in (_number(_m(r).get("score")) for r in rows) if x is not None]
    subject=_text(_m(understanding).get("canonical_subject"))
    subject_tokens=_tokens(subject)
    query_tokens=_tokens(query)
    title_tokens=set();content_tokens=set();document_names=[]
    for row in rows[:5]:
        r=_m(row);name=_text(r.get("source_name"))
        if name and name not in document_names:document_names.append(name)
        title_tokens|=_tokens(name);content_tokens|=_tokens(r.get("content"))
    evidence_tokens=title_tokens|content_tokens
    matched_subject=sorted(subject_tokens & evidence_tokens)
    subject_coverage=round(len(matched_subject)/len(subject_tokens),4) if subject_tokens else None
    matched_query=sorted(query_tokens & evidence_tokens)
    query_coverage=round(len(matched_query)/len(query_tokens),4) if query_tokens else None
    top=scores[0] if scores else None;second=scores[1] if len(scores)>1 else None
    margin=round(top-second,6) if top is not None and second is not None else None
    top3=scores[:3]
    median_top3=round(statistics.median(top3),6) if top3 else None
    reasons=[];status="ambiguous"
    if not rows:
        status="likely_insufficient";reasons.append("no_results")
    else:
        if top is not None and top<low_score:reasons.append("top_score_below_candidate_low_band")
        if subject_tokens and subject_coverage==0:reasons.append("subject_not_supported_by_top_evidence")
        if top is not None and top>=high_score:reasons.append("top_score_in_candidate_high_band")
        if subject_coverage is not None and subject_coverage>=.5:reasons.append("subject_supported_by_top_evidence")
        if len(document_names)==1:reasons.append("top_results_concentrated_in_one_document")
        if "top_score_below_candidate_low_band" in reasons or "subject_not_supported_by_top_evidence" in reasons:
            status="likely_insufficient"
        elif "top_score_in_candidate_high_band" in reasons and "subject_supported_by_top_evidence" in reasons:
            status="likely_sufficient"
    return {
        "schema_version":SCHEMA_VERSION,"status":status,"observational_only":True,"affects_publication":False,
        "candidate_bands":{"low_score":low_score,"high_score":high_score,"calibrated":False},
        "features":{"result_count":len(rows),"top_score":top,"second_score":second,"top1_top2_margin":margin,"median_top3_score":median_top3,"subject":subject or None,"subject_token_count":len(subject_tokens),"subject_token_coverage":subject_coverage,"matched_subject_tokens":matched_subject,"query_token_coverage":query_coverage,"matched_query_tokens":matched_query,"top_document_count":len(document_names),"top_documents":document_names},
        "reasons":reasons,
    }
