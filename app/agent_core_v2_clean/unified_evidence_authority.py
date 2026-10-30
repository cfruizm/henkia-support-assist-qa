from __future__ import annotations
from copy import deepcopy
import re
import unicodedata

_GENERIC = {
    "como", "para", "una", "uno", "unos", "unas", "que", "cual", "cuales",
    "existen", "documentados", "documentacion", "informacion", "usuario",
    "proceso", "procedimiento", "metodo", "metodos", "detalle", "detallar",
    "realizar", "realiza", "actual", "explicar", "analizar", "saber", "muestra",
    "necesito", "quiero", "puedo", "dime", "hacer", "obtener", "comprender",
    "the", "how", "for", "documented", "information", "process", "method",
}
_SHORT = {"pin", "ews", "usb", "smb", "wja", "ipp", "pcl", "pdf", "mf", "dca", "sds", "tls", "ssl"}
_OPERATION = {
    "asignar", "consultar", "actualizar", "instalar", "configurar", "analizar",
    "mostrar", "generar", "exportar", "comparar", "validar", "recuperar",
    "descargar", "importar", "crear", "visualizar", "listar", "resumir",
    "distribuir", "distribucion", "procesar", "ejecutar", "escanear",
}

def _norm(value):
    return unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode().casefold()

def _tokens(value):
    out = set()
    for token in re.findall(r"[a-z0-9]+", _norm(value)):
        if token in _GENERIC:
            continue
        if len(token) >= 4 or token in _SHORT:
            out.add(token)
    return out

def _identity(item):
    return str(item.get("url") or item.get("source") or (item.get("metadata") or {}).get("canonical_url") or item.get("title") or "")

def _page_number(item):
    metadata=item.get("metadata") or {};raw=metadata.get("page_label") or metadata.get("page") or item.get("page")
    try:return int(str(raw).strip())
    except (TypeError,ValueError):return None

def _explicit_page_scope(value):
    """Extract an explicit numeric page constraint without domain vocabulary."""
    text=_norm(value)
    match=re.search(r"\b(?:pagina|page)\s*(\d+)\s*(?:en\s+adelante|onward|onwards|forward|y\s+siguientes)?",text)
    if not match:return None
    start=int(match.group(1));tail=match.group(0)
    open_ended=bool(re.search(r"(?:adelante|onward|onwards|forward|siguientes)",tail))
    return {"start":start,"end":None if open_ended else start,"open_ended":open_ended,"matched":match.group(0)}

def _document_order_key(item, fallback=0):
    metadata=item.get("metadata") or {};page=_page_number(item);raw_chunk=metadata.get("chunk_index")
    if raw_chunk in (None,""):raw_chunk=metadata.get("chunk")
    if raw_chunk in (None,""):raw_chunk=metadata.get("start_index")
    try:chunk=(0,int(str(raw_chunk).strip()))
    except (TypeError,ValueError):chunk=(1,int(fallback))
    return (0,page) if page is not None else (1,10**9),chunk,int(fallback)

def _document_object_candidates(out,candidates):
    fields=(out.get("query") or {}).get("fields") or {};details=fields.get("details") or {};requested=_norm(details.get("document_object") or "")
    if not requested:return [],None
    context=out.get("_answer_context") or {};identities={str(x).strip() for x in context.get("source_identities") or [] if str(x).strip()}
    eligible=[(position,deepcopy(item)) for position,item in enumerate(candidates) if not identities or _identity(item) in identities]
    eligible.sort(key=lambda pair:_document_order_key(pair[1],pair[0]))
    ordered=[item for _,item in eligible];matches=[]
    for index,item in enumerate(ordered):
        available=_norm(" ".join((str(item.get("title") or ""),str(item.get("text") or ""))))
        if re.search(r"(?<![a-z0-9])"+re.escape(requested)+r"(?![a-z0-9])",available):matches.append(index)
    if not matches:return [],{"requested":requested,"matched":False,"match_count":0,"ordering":"page_chunk_position"}
    # Cross-references and table-of-contents entries may precede the actual body.
    # Choose the strongest documentary anchor generically: favor an occurrence
    # nearest the beginning of its own chunk, then richer content following the
    # phrase, then the later documentary position as a deterministic tie-breaker.
    anchors=[]
    for index in matches:
        body=_norm(ordered[index].get("text") or "");match=re.search(r"(?<![a-z0-9])"+re.escape(requested)+r"(?![a-z0-9])",body)
        offset=match.start() if match else len(body);ratio=offset/max(1,len(body));after=len(body)-(match.end() if match else len(body))
        near_start=ratio<=0.35
        anchors.append((1 if near_start else 0,-ratio,after,index))
    anchors.sort(reverse=True);anchor_index=anchors[0][3]
    start=max(0,anchor_index-1);stop=min(len(ordered),start+16);selected=ordered[start:stop]
    matched_pages=sorted({_page_number(ordered[index]) for index in matches if _page_number(ordered[index]) is not None})
    selected_pages=[]
    for item in selected:
        page=_page_number(item)
        if page is not None and page not in selected_pages:selected_pages.append(page)
    anchor_page=_page_number(ordered[anchor_index])
    return selected,{"requested":requested,"matched":True,"match_count":len(matches),"context_chunks":len(selected),"ordering":"page_chunk_position","window":"best_anchor_progressive_up_to_limit","anchor_strategy":"chunk_leading_occurrence_then_forward_content_then_later_position","anchor_index":anchor_index,"anchor_page":anchor_page,"region_start_index":start,"region_end_index_exclusive":stop,"maximum_chunks":16,"matched_pages":matched_pages,"selected_pages":selected_pages}

def _page_scoped_candidates(out,candidates):
    fields=(out.get("query") or {}).get("fields") or {}
    scope=_explicit_page_scope(fields.get("current_message") or fields.get("contextual_operation") or "")
    if not scope:return [],None
    context=out.get("_answer_context") or {};identities={str(x).strip() for x in context.get("source_identities") or [] if str(x).strip()}
    rows=[]
    for item in candidates:
        page=_page_number(item)
        if page is None:continue
        if identities and _identity(item) not in identities:continue
        if page<scope["start"]:continue
        if scope["end"] is not None and page>scope["end"]:continue
        rows.append(deepcopy(item))
    rows.sort(key=lambda item:(_page_number(item) if _page_number(item) is not None else 10**9,str(item.get("id") or "")))
    return rows,scope

def _dedup(items):
    out, seen = [], set()
    for item in items:
        key = (_identity(item), str(item.get("page") or ""), _norm(item.get("text"))[:320])
        if key in seen:
            continue
        seen.add(key)
        out.append(deepcopy(item))
    return out

def _request_text(message, understanding, retrieval):
    understanding=understanding or {}
    if understanding.get("degraded"):return str(message or "")
    fields=((retrieval.get("query") or {}).get("fields") or {})
    relation=str(fields.get("topic_relation") or understanding.get("topic_relation") or "")
    act=str(fields.get("user_act") or understanding.get("user_act") or "")
    if relation=="new_topic":return " ".join((str(message or ""),str(understanding.get("current_goal") or "")))
    if relation in {"same_topic","same_topic_refinement","return_to_previous"} and act in {"follow_up","answer_to_question","request_elaboration","attempt_result","reported_failure"}:
        details=fields.get("details") or {}
        accumulated=" ".join(str(x or "") for x in (fields.get("goal"),fields.get("contextual_operation"),details.get("operation"),details.get("subject"),understanding.get("current_goal")))
        technical=_tokens(accumulated);current=_tokens(message)
        return accumulated if technical and len(current&technical)<1 else " ".join((str(message or ""),accumulated))
    return str(message or "")

def _fit(item, wanted):
    title = _tokens(item.get("title"))
    content = title | _tokens(item.get("text"))
    covered = wanted & content
    title_hits = wanted & title
    semantic = float((item.get("semantic_fit") or {}).get("score", 0) or 0)
    return {
        "coverage": len(covered) / max(1, len(wanted)),
        "title_coverage": len(title_hits) / max(1, len(wanted)),
        "title_precision": len(title_hits) / max(1, len(title)),
        "covered_count": len(covered),
        "title_hit_count": len(title_hits),
        "semantic_score": semantic,
        "carried": bool(item.get("carried_from_previous_answer")),
        "covered": sorted(covered),
        "title_hits": sorted(title_hits),
    }


def _conceptual_selection(candidates, understanding):
    """Conceptual routing must not override an exact symptom article."""
    u=understanding or {}
    if str(u.get("intent") or "").casefold()!="conceptual":return None
    request_terms=_tokens(" ".join((str(_request_text("",u,{})),str(u.get("current_goal") or ""),str(u.get("canonical_subject") or ""))))
    exact=[]
    for position,item in enumerate(candidates):
        sf=item.get("semantic_fit") or {}; title_terms=set(sf.get("title_matched_terms") or [])
        title_terms={_norm(x) for x in title_terms if not str(x).startswith("concept:")}
        semantic=float(sf.get("score",0.0) or 0.0)
        symptom_hits=len(title_terms & request_terms)
        if symptom_hits>=3 and semantic>=0.30:
            exact.append((symptom_hits,semantic,-position,deepcopy(item)))
    if exact:
        exact.sort(reverse=True,key=lambda x:(x[0],x[1],x[2]));identity=_identity(exact[0][3])
        selected=[x[3] for x in exact if _identity(x[3])==identity][:8]
        for i,item in enumerate(selected,1):item["id"]=f"R{i}"
        return {"schema_version":8,"status":"sufficient","mode":"documented","accepted":True,
          "reason":"exact_symptom_title_precedence","request_terms":sorted(request_terms),
          "document_ids":[identity],"evidence_ids":[x["id"] for x in selected],"coverage":1.0,
          "selected_evidence":selected,"rejected_count":max(0,len(candidates)-len(selected)),
          "selection_authority":"symptom_title_over_broad_conceptual"}
    details=u.get("goal_updates") or {};subject=u.get("canonical_subject") or details.get("subject") or ""
    subject_terms=_tokens(subject)
    subject_phrase=" ".join(re.findall(r"[a-z0-9]+",_norm(subject))).strip()
    if not subject_terms:return None
    ranked=[]
    for position,item in enumerate(candidates):
        title=_norm(item.get("title"));text=_norm(item.get("text"));available=_tokens(" ".join((title,text)))
        if not subject_terms.issubset(available):continue
        possessive_feature=bool(re.search(r"\b(?:'s|s)\s+[a-z0-9]+",title)) or " configure " in f" {title} "
        definitional=bool(re.search(r"\b(?:is|are|es|son|consta de|consists of)\b",text)) and not possessive_feature
        descriptive=any(m in text for m in ("proporciona","permite","administra","supervision","gestion","compatible","provides","allows","manages","monitoring","capabilities","supports"))
        family=str((item.get("metadata") or {}).get("document_family") or "").casefold();overview=family in {"brochure","overview","requirements","general_document"}
        semantic=float((item.get("semantic_fit") or {}).get("score",0.0) or 0.0)
        if not (definitional or descriptive or overview):continue
        score=(.45 if definitional else 0)+(.30 if descriptive else 0)+(.15 if overview else 0)+min(.10,semantic)-(.35 if possessive_feature else 0)
        ranked.append((score,-position,deepcopy(item)))
    ranked.sort(reverse=True,key=lambda x:(x[0],x[1]));selected=[x[2] for x in ranked if x[0]>=.20][:8]
    for i,item in enumerate(selected,1):item["id"]=f"R{i}"
    if not selected:return None
    # A subject mention inside a feature article is not enough to authorize a
    # complete product definition. General authority requires an overview-like
    # document or an explicit subject-level definition. Otherwise, generation
    # remains allowed but the verdict is honestly partial.
    overview_families={"brochure","overview","general_document"}
    overview_support=False;explicit_subject_definition=False
    # Preserve the canonical subject order. Sorting the token set changed names
    # such as "Example Suite" into "suite example" and hid valid definitions.
    subject_pattern=r"\b"+r"\s+".join(re.escape(x) for x in subject_phrase.split())+r"\b" if subject_phrase else ""
    for item in selected:
        metadata=item.get("metadata") or {};family=str(metadata.get("document_family") or "").casefold()
        if family in overview_families:overview_support=True
        body=_norm(item.get("text"))[:900]
        if subject_pattern and re.search(subject_pattern+r".{0,100}\b(?:is|are|es|son|permite|provides|allows|manages)\b",body):
            explicit_subject_definition=True
    complete=bool(overview_support or explicit_subject_definition)
    return {"schema_version":9,"status":"sufficient" if complete else "partial","mode":"documented","accepted":True,
      "reason":"conceptual_general_authority" if complete else "conceptual_feature_evidence_only",
      "request_terms":sorted(request_terms),"document_ids":list(dict.fromkeys(_identity(x) for x in selected)),
      "evidence_ids":[x["id"] for x in selected],"coverage":1.0 if complete else 0.5,
      "selected_evidence":selected,"rejected_count":max(0,len(candidates)-len(selected)),
      "conceptual_authority":{"complete":complete,"overview_support":overview_support,
        "explicit_subject_definition":explicit_subject_definition,
        "localized_limitation_required":not complete}}

def _requirements_structure_score(item):
    """Domain-neutral prerequisite/constraint structure across languages."""
    text=_norm(" ".join((str(item.get("title") or ""),str(item.get("text") or ""))))
    stems=("requir","prereq","instal","compatib","dependenc","sistema","system","servidor","server","database","datos","network","redes","certificat","certificad","memori","proces","disco","storage","operating")
    hits={stem for stem in stems if stem in text}
    list_like=bool(re.search(r"(?:^|\s)(?:[0-9]+[.)]|[-•])\s",str(item.get("text") or "")))
    return len(hits)+(1 if list_like else 0),sorted(hits),list_like

def _requirements_selection(candidates, understanding, wanted):
    """Select broad requirements evidence using document-level coverage.

    Requirement constraints are often distributed across several chunks or
    pages. This selector aggregates by document identity and relies on the
    semantic intent and subject already produced by understanding. It contains
    no product names, domain phrases, URLs, ports, or campaign examples.
    """
    u = understanding or {}
    if str(u.get("intent") or "").casefold() != "requirements":
        return None
    details = u.get("goal_updates") or {}
    subject_terms = _tokens(" ".join(str(x or "") for x in (
        u.get("canonical_subject"), details.get("subject"),
        details.get("product"), details.get("platform"),
    )))
    operation_terms = wanted - subject_terms
    groups = {}
    for position, item in enumerate(candidates):
        identity = _identity(item)
        if identity:
            groups.setdefault(identity, []).append((position, deepcopy(item)))
    ranked = []
    for identity, positioned in groups.items():
        rows = [item for _, item in positioned]
        title_terms, content_terms, pages, semantic_scores = set(), set(), set(), []
        for item in rows:
            title_terms |= _tokens(item.get("title"))
            content_terms |= _tokens(item.get("text"))
            semantic_scores.append(float((item.get("semantic_fit") or {}).get("score", 0) or 0))
            if item.get("page") not in (None, ""):
                pages.add(str(item.get("page")))
        available = title_terms | content_terms
        subject_hits = subject_terms & available
        operation_hits = operation_terms & available
        request_hits = wanted & available
        coverage = len(request_hits) / max(1, len(wanted))
        subject_ok = not subject_terms or bool(subject_hits)
        operation_ok = not operation_terms or bool(operation_hits)
        breadth = len(pages) if pages else len(rows)
        semantic = max(semantic_scores or [0.0])
        structure_rows=[];structure_hits=set()
        for row in rows:
            score,hits,list_like=_requirements_structure_score(row)
            if score:structure_rows.append((score,float((row.get("semantic_fit") or {}).get("score",0) or 0),deepcopy(row)))
            structure_hits.update(hits)
        title_subject_ratio=len(subject_hits)/max(1,len(subject_terms)) if subject_terms else 1.0
        cross_language_ok=bool(subject_ok and title_subject_ratio>=0.5 and breadth>=2 and len(structure_rows)>=2 and semantic>=0.20)
        eligible=(subject_ok and operation_ok and semantic>=0.12 and coverage>=0.30) or cross_language_ok
        if eligible:
            ranked.append((1 if cross_language_ok else 0,coverage,len(operation_hits),len(structure_rows),breadth,semantic,-positioned[0][0],identity,rows,pages,sorted(subject_hits),sorted(operation_hits),sorted(structure_hits),structure_rows))
    if not ranked:
        return None
    ranked.sort(reverse=True, key=lambda x: x[:7])
    cross_language,coverage,_,structure_count,breadth,semantic,_,identity,rows,pages,subject_hits,operation_hits,structure_hits,structure_rows = ranked[0]
    def order_key(item):
        page = str(item.get("page") or "")
        return (0, int(page)) if page.isdigit() else (1, page)
    if cross_language:
        focused=sorted((row for _,_,row in structure_rows),key=order_key)
        selected=_dedup(focused+sorted(rows,key=order_key))[:10]
    else:selected=sorted(_dedup(rows), key=order_key)[:10]
    for idx, item in enumerate(selected, 1):
        item["id"] = f"R{idx}"
    complete = breadth >= 2 and len(selected) >= 3
    return {
        "schema_version": 10,
        "status": "sufficient" if complete else "partial",
        "mode": "documented" if complete else "documented_plus_internal",
        "accepted": bool(complete),
        "reason": "requirements_document_level_coverage" if complete else "requirements_document_level_coverage_partial",
        "request_terms": sorted(wanted),
        "document_ids": [identity],
        "evidence_ids": [item["id"] for item in selected],
        "coverage": round(float(coverage), 4),
        "selected_evidence": selected,
        "rejected_count": max(0, len(candidates) - len(selected)),
        "requirements_authority": {
            "aggregation": "single_document_multichunk",
            "subject_hits": subject_hits,
            "operation_hits": operation_hits,
            "unique_pages": len(pages),
            "selected_chunks": len(selected),
            "semantic_score": round(float(semantic), 4),
            "cross_language_structure_authority": bool(cross_language),
            "structure_chunk_count": structure_count,
            "structure_hits": structure_hits,
            "complete": bool(complete),
        },
    }

def _primary_continuity_selection(out,candidates,wanted):
    query=(out.get("query") or {}).get("fields") or {};context=out.get("_answer_context") or {}
    if str(query.get("previous_evidence_role") or "")!="primary":return None
    identities={str(x).strip() for x in context.get("source_identities") or [] if str(x).strip()}
    if not identities:return None
    object_rows,object_scope=_document_object_candidates(out,candidates)
    if object_rows:
        identity=_identity(object_rows[0]);selected=[item for item in object_rows if _identity(item)==identity]
        for index,item in enumerate(selected,1):item["id"]=f"R{index}"
        return {"schema_version":11,"status":"sufficient","mode":"documented","accepted":True,"reason":"explicit_object_within_primary_document","request_terms":sorted(wanted),"operation_terms":[],"document_ids":[identity],"evidence_ids":[item["id"] for item in selected],"coverage":1.0,"selected_evidence":selected,"rejected_count":max(0,len(candidates)-len(selected)),"continuity_authority":"primary_identity_plus_document_object","previous_authority_status":str((context.get("evidence_authority") or {}).get("status") or "") or None,"progression_candidate_count":len(selected),"document_object_scope":object_scope}
    scoped,page_scope=_page_scoped_candidates(out,candidates)
    if scoped:
        identity=_identity(scoped[0]);available=[item for item in scoped if _identity(item)==identity];selected=available[:16]
        for index,item in enumerate(selected,1):item["id"]=f"R{index}"
        return {"schema_version":10,"status":"sufficient","mode":"documented","accepted":True,"reason":"explicit_page_scope_within_primary_document","request_terms":sorted(wanted),"operation_terms":[],"document_ids":[identity],"evidence_ids":[item["id"] for item in selected],"coverage":1.0,"selected_evidence":selected,"rejected_count":max(0,len(candidates)-len(selected)),"continuity_authority":"primary_identity_plus_explicit_page_scope","previous_authority_status":str((context.get("evidence_authority") or {}).get("status") or "") or None,"progression_candidate_count":len(selected),"page_scope":{**page_scope,"available_chunks":len(available),"selected_chunks":len(selected)}}
    details=query.get("details") or {};operation_text=" ".join(str(x or "") for x in (query.get("contextual_operation"),details.get("operation"),query.get("goal"),context.get("goal")))
    operation_terms=_tokens(operation_text);subject_terms=_tokens(" ".join(str(x or "") for x in (details.get("subject"),query.get("subject"))));operation_terms-=subject_terms
    previous_status=str((context.get("evidence_authority") or {}).get("status") or "");rows=[]
    for position,item in enumerate(candidates):
        if _identity(item) not in identities:continue
        available=_tokens(" ".join((str(item.get("title") or ""),str(item.get("text") or ""))));fit=_fit(item,wanted or operation_terms);semantic=float((item.get("semantic_fit") or {}).get("score",0) or 0)
        op_hits=len(operation_terms&available);non_subject_hits=len((wanted-subject_terms)&available)
        aligned=op_hits>=2 or non_subject_hits>=2 or (op_hits>=1 and semantic>=.30) or semantic>=.42
        if previous_status=="partial" and not (op_hits>=2 or semantic>=.42):aligned=False
        if aligned:rows.append((op_hits,non_subject_hits,fit["coverage"],semantic,-position,deepcopy(item)))
    if not rows:return None
    rows.sort(reverse=True,key=lambda x:(x[0],x[1],x[2],x[3],x[4]));identity=_identity(rows[0][5]);selected=[x[5] for x in rows if _identity(x[5])==identity][:8]
    for i,item in enumerate(selected,1):item["id"]=f"R{i}"
    coverage=round(float(max(x[2] for x in rows)),4)
    strong_progression=len(selected)>=2 or coverage>=0.35
    status="sufficient" if strong_progression else "partial"
    mode="documented" if strong_progression else "documented_plus_internal"
    return {"schema_version":9,"status":status,"mode":mode,"accepted":strong_progression,"reason":"primary_document_progressive_rerank","request_terms":sorted(wanted or operation_terms),"operation_terms":sorted(operation_terms),"document_ids":[identity],"evidence_ids":[x["id"] for x in selected],"coverage":coverage,"selected_evidence":selected,"rejected_count":max(0,len(candidates)-len(selected)),"continuity_authority":"primary_identity_plus_all_document_chunks","previous_authority_status":previous_status or None,"progression_candidate_count":len(selected)}

def _candidate_pool(out, understanding=None):
    primary = list(out.get("generation_evidence") or out.get("evidence") or [])
    diagnostic = list(out.get("diagnostic_evidence") or [])
    # A conceptual definition may be present in a different candidate document than
    # the top lexical hit. Subject-claim authorization below remains binding, so
    # widening only the candidate pool does not authorize unrelated products.
    if str((understanding or {}).get("intent") or "").casefold()=="conceptual":
        return _dedup(primary + diagnostic)
    if not primary:
        return _dedup(diagnostic)
    identities = {_identity(item) for item in primary if _identity(item)}
    # Diagnostic chunks from the already-authorized document are eligible for
    # follow-up progression. This does not authorize unrelated documents.
    same_document = [item for item in diagnostic if _identity(item) in identities]
    return _dedup(primary + same_document)

def _explicit_document_selection(retrieval, candidates, understanding, wanted):
    """Authorize an exact current-turn document only when its content covers the requested operation."""
    selection=(retrieval or {}).get("selection") or {};exact=(retrieval or {}).get("exact_document_match") or {};u=understanding or {}
    eligible=(bool(selection.get("exact_identifier_match")) and bool(exact.get("matched"))
        and str(u.get("topic_relation") or "").casefold() in {"new_topic","independent"}
        and str(u.get("subject_origin") or "").casefold()=="current_message"
        and str(u.get("reference_relation") or "none").casefold() in {"","none"})
    source=str(exact.get("source") or "").strip()
    if not eligible or not source:return None
    rows=[deepcopy(item) for item in candidates if _identity(item)==source]
    if not rows:return None
    details=u.get("goal_updates") or {};subject_terms=_tokens(" ".join(str(x or "") for x in (u.get("canonical_subject"),details.get("subject"),details.get("product"),details.get("platform"),*(exact.get("identifiers") or []))))
    operation_terms=set(wanted)-subject_terms
    if not operation_terms:return None
    title_terms=set();content_terms=set()
    for item in rows:title_terms|=_tokens(item.get("title"));content_terms|=_tokens(item.get("text"))
    title_hits=operation_terms&title_terms;content_hits=operation_terms&content_terms;required=min(2,len(operation_terms))
    if len(content_hits)<required:return None
    selected=rows[:8]
    for index,item in enumerate(selected,1):item["id"]=f"R{index}"
    coverage=len(set(wanted)&(title_terms|content_terms))/max(1,len(wanted))
    return {"schema_version":10,"status":"sufficient","mode":"documented","accepted":True,"reason":"exact_document_current_turn_operation_coverage","request_terms":sorted(wanted),"document_ids":[source],"evidence_ids":[x["id"] for x in selected],"coverage":round(float(coverage),4),"operation_alignment":{"required_terms":sorted(operation_terms),"title_hits":sorted(title_hits),"content_hits":sorted(content_hits),"aligned":True},"explicit_document_authority":{"evaluated":True,"exact_identifier_match":True,"current_turn_subject":True,"required_operation_dimensions":required,"content_operation_dimension_count":len(content_hits),"operation_supported":True,"semantic_score_required":False,"policy":"exact_document_current_turn_operation_coverage_v1"},"selected_evidence":selected,"rejected_count":max(0,len(candidates)-len(selected))}

def apply_unified_evidence_verdict(retrieval, message, understanding):
    out = deepcopy(retrieval or {})
    candidates = _candidate_pool(out, understanding)
    wanted = _tokens(_request_text(message, understanding, out))
    continuity = _primary_continuity_selection(out, candidates, wanted)
    explicit_document = _explicit_document_selection(out, candidates, understanding, wanted)
    requirements = _requirements_selection(candidates, understanding, wanted)
    conceptual = _conceptual_selection(candidates, understanding)
    if continuity:
        selected = continuity["selected_evidence"]
        out["evidence_verdict"] = continuity
        out["generation_evidence"] = deepcopy(selected)
        out["evidence"] = deepcopy(selected)
        semantic_fit = out.setdefault("semantic_fit", {})
        semantic_fit.update({
            "accepted_for_generation": True,
            "low_fit": False,
            "generation_ids": continuity["evidence_ids"],
            "generation_count": len(selected),
            "selected_document": continuity["document_ids"][0],
            "previous_evidence_role": "primary",
            "previous_evidence_primary_eligible": True,
            "decision_path": "unified_evidence_authority_v11_document_object" if continuity.get("document_object_scope") else "unified_evidence_authority_v10_page_scope" if continuity.get("page_scope") else "unified_evidence_authority_v5_primary_continuity",
        })
        follow = out.setdefault("followup_grounding", {})
        follow["previous_evidence_considered"] = len((out.get("_answer_context") or {}).get("cited_evidence") or [])
        follow["previous_evidence_selected"] = len(selected)
        follow["primary_document_reused"] = True
        return out
    if explicit_document:
        selected = explicit_document["selected_evidence"]
        out["evidence_verdict"] = explicit_document
        out["generation_evidence"] = deepcopy(selected);out["evidence"] = deepcopy(selected)
        out.setdefault("semantic_fit", {}).update({"accepted_for_generation":True,"low_fit":False,"generation_ids":explicit_document["evidence_ids"],"generation_count":len(selected),"selected_document":explicit_document["document_ids"][0],"decision_path":"unified_evidence_authority_v12_explicit_document_current_turn"})
        return out
    if requirements:
        selected = requirements["selected_evidence"]
        out["evidence_verdict"] = requirements
        out["generation_evidence"] = deepcopy(selected)
        out["evidence"] = deepcopy(selected)
        semantic_fit = out.setdefault("semantic_fit", {})
        semantic_fit.update({
            "accepted_for_generation": bool(selected),
            "low_fit": not bool(selected),
            "generation_ids": requirements["evidence_ids"],
            "generation_count": len(selected),
            "selected_document": requirements["document_ids"][0],
            "decision_path": "unified_evidence_authority_v10_requirements_document_coverage",
        })
        return out
    if conceptual:
        selected = conceptual["selected_evidence"]
        out["evidence_verdict"] = conceptual
        out["generation_evidence"] = deepcopy(selected)
        out["evidence"] = deepcopy(selected)
        semantic_fit = out.setdefault("semantic_fit", {})
        semantic_fit.update({
            "accepted_for_generation": True,
            "low_fit": False,
            "generation_ids": conceptual["evidence_ids"],
            "generation_count": len(selected),
            "selected_document": conceptual["document_ids"][0] if conceptual["document_ids"] else None,
            "decision_path": "unified_evidence_authority_v4_conceptual_claim_coverage",
        })
        return out
    scored = []
    for item in candidates:
        fit = _fit(item, wanted)
        item["unified_evidence_fit"] = {k: round(v, 4) if isinstance(v, float) else v for k, v in fit.items()}
        scored.append((fit, item))
    # Prefer exact titles over broad titles when both cover the request. This is
    # computed from token ratios only; it does not depend on products, languages,
    # URLs, synonyms, or operation dictionaries added for a scenario.
    scored.sort(key=lambda pair: (
        pair[0]["title_hit_count"], pair[0]["title_precision"], pair[0]["covered_count"],
        pair[0]["title_coverage"], pair[0]["coverage"], pair[0]["semantic_score"],
        not pair[0]["carried"],
    ), reverse=True)

    selected = []
    accepted = False
    status, mode, reason = "insufficient", "internal_only", "no_operationally_aligned_evidence"
    best_fit, best = scored[0] if scored else ({}, None)
    if best and wanted:
        target_terms = wanted - _OPERATION
        available_title = _tokens(best.get("title"))
        available = available_title | _tokens(best.get("text"))
        target_ok = not target_terms or bool(target_terms & available)

        # Separate the confirmed subject from the requested operation/object.
        # A title that only repeats the product name must not authorize an article
        # about another task. This is intentionally product-neutral: it derives
        # the subject from the semantic contract and requires at least one
        # remaining request anchor in the evidence.
        details = (understanding or {}).get("goal_updates") or {}
        subject_terms = _tokens(" ".join(str(x or "") for x in (
            (understanding or {}).get("canonical_subject"),
            details.get("subject"), details.get("product"), details.get("platform"),
        )))
        operation_terms = wanted - subject_terms
        title_operation_hits = operation_terms & available_title
        content_operation_hits = operation_terms & available
        operation_aligned = not operation_terms or bool(content_operation_hits)

        direct_title = best_fit["title_hit_count"] >= 2 and bool(title_operation_hits)
        direct_content = (
            best_fit["covered_count"] >= 2
            and best_fit["coverage"] >= 0.4
            and operation_aligned
        )
        semantic_support = best_fit["semantic_score"] >= 0.15
        intent_name = str((understanding or {}).get("intent") or "").casefold()
        procedural_new_request = (
            intent_name == "procedural"
            and str((understanding or {}).get("user_act") or "").casefold() in {"new_request", "independent_question", "topic_change"}
            and str((understanding or {}).get("reference_relation") or "none").casefold() in {"", "none"}
        )
        required_operation_dimensions = min(2, len(operation_terms)) if operation_terms else 0
        operation_dimension_count = len(content_operation_hits)
        title_operation_dimension_count = len(title_operation_hits)
        procedural_operation_supported = (
            not procedural_new_request or required_operation_dimensions == 0
            or operation_dimension_count >= required_operation_dimensions
        )
        if procedural_new_request:
            direct_title = direct_title and title_operation_dimension_count >= required_operation_dimensions
            direct_content = direct_content and procedural_operation_supported
        accepted = target_ok and operation_aligned and procedural_operation_supported and (direct_title or (direct_content and semantic_support))
        intent_is_troubleshooting = (
            str((understanding or {}).get("intent") or "").casefold() == "troubleshooting"
        )
        # Troubleshooting evidence can be useful even when vector similarity is
        # modest: titles and content may describe the affected operation without
        # repeating the user's symptom wording. Partial authority therefore uses
        # structural operation alignment plus either a semantic signal or a
        # precise operation-bearing title. It never promotes subject-only overlap.
        title_operation_support = bool(
            title_operation_hits
            and best_fit["title_precision"] >= 0.20
            and best_fit["coverage"] >= 0.10
        )
        partial_semantic = (
            intent_is_troubleshooting
            and target_ok
            and operation_aligned
            and best_fit["covered_count"] >= 1
            and (semantic_support or title_operation_support)
        )
        if accepted or partial_semantic:
            identity = _identity(best)
            selected = [item for fit, item in scored if _identity(item) == identity][:8]
            full = accepted and (best_fit["coverage"] >= 0.5 or best_fit["title_hit_count"] >= 2)
            status = "sufficient" if full else "partial"
            mode = "documented" if full else "documented_plus_internal"
            reason = "direct_title_operation_match" if full and direct_title else "direct_content_and_operation_match" if accepted else "structured_troubleshooting_support_partial"
            accepted = bool(full)

    for idx, item in enumerate(selected, 1):
        item["id"] = f"R{idx}"
    verdict = {
        "schema_version": 4,
        "status": status,
        "mode": mode,
        "accepted": accepted,
        "reason": reason,
        "request_terms": sorted(wanted),
        "document_ids": list(dict.fromkeys(_identity(x) for x in selected)),
        "evidence_ids": [x["id"] for x in selected],
        "coverage": round(float(best_fit.get("coverage", 0) if best else 0), 4),
        "operation_alignment": {
            "required_terms": sorted(operation_terms) if best and wanted else [],
            "title_hits": sorted(title_operation_hits) if best and wanted else [],
            "content_hits": sorted(content_operation_hits) if best and wanted else [],
            "aligned": bool(operation_aligned) if best and wanted else False,
        },
        "procedural_applicability": {
            "evaluated": bool(best and wanted and str((understanding or {}).get("intent") or "").casefold() == "procedural"),
            "clean_new_request": bool(procedural_new_request) if best and wanted else False,
            "required_operation_dimensions": int(required_operation_dimensions) if best and wanted else 0,
            "content_operation_dimension_count": int(operation_dimension_count) if best and wanted else 0,
            "title_operation_dimension_count": int(title_operation_dimension_count) if best and wanted else 0,
            "operation_supported": bool(procedural_operation_supported) if best and wanted else False,
            "policy": "structured_request_dimension_coverage_v1",
        },
        "selected_evidence": deepcopy(selected),
        "rejected_count": max(0, len(candidates) - len(selected)),
    }
    out["evidence_verdict"] = verdict
    out["generation_evidence"] = deepcopy(selected)
    out["evidence"] = deepcopy(selected)
    semantic_fit = out.setdefault("semantic_fit", {})
    semantic_fit.update({
        "accepted_for_generation": accepted,
        "low_fit": not accepted,
        "generation_ids": verdict["evidence_ids"],
        "generation_count": len(selected),
        "selected_document": verdict["document_ids"][0] if verdict["document_ids"] else None,
        "decision_path": "unified_evidence_authority_v10_structured_partial_troubleshooting",
    })
    return out
