from __future__ import annotations
import copy, hashlib, re, unicodedata

VERSION = "semantic_evidence_fit_v8_query_provenance"
STOP = {"para","como","que","del","las","los","una","uno","con","por","sin","antes","debo","debe","deben","en","el","la","y","o","how","what","the","and","for","from","with","this","that","before","after","into","using","is","are","to","configure","configurar","explicar","realizar","aplicar","revisar","necesito","quiero"}
# Canonical concepts are language bridges, not product or benchmark rules.
CONCEPTS = {
 "authentication":{"autenticacion","authenticate","authentication","credential","credentials","credencial","credenciales","login","identity","identidad","access","acceso"},
 "validation":{"validar","validacion","verify","verification","check","checking","confirm","comprobar","revisar","prerequisite","requirement","requirements","requisito","requisitos"},
 "printing":{"impresion","imprimir","print","printing","printer","impresora","job","trabajo","spooler"},
 "tracking":{"tracking","rastreo","seguimiento","monitoreo","monitoring","registro","log"},
 "security":{"segura","seguro","seguridad","secure","security","protection","proteccion"},
 "user":{"usuario","usuarios","user","users","account","accounts","cuenta","cuentas"},
 "device":{"dispositivo","dispositivos","device","devices","mfd","mfp","equipo","equipos"},
 "cost":{"cost","costes","costo","costos","gasto","gastos","expense","expenses"},
 "configuration":{"configuracion","configure","configured","configuration","setting","settings","ajuste","ajustes"},
}

def _norm(value):
 value=unicodedata.normalize("NFKD",str(value or "")).encode("ascii","ignore").decode().casefold()
 return " ".join(re.findall(r"[a-z0-9_-]{2,}",value))

def _raw_terms(value):return {x for x in _norm(value).split() if x not in STOP and len(x)>=3}
def _terms(value):
 raw=_raw_terms(value);out=set(raw)
 for concept,variants in CONCEPTS.items():
  if raw & variants:out.add("concept:"+concept)
 return out

def _identity(item):return str(item.get("url") or item.get("source") or (item.get("metadata") or {}).get("canonical_url") or item.get("title") or "")
def _chunk_identity(item):return "|".join((_identity(item),str(item.get("page") or ""),_norm(item.get("text") or "")[:240]))
def _document_terms(item):
 meta=item.get("metadata") or {}
 return _terms(" ".join(str(x or "") for x in (item.get("title"),item.get("text"),meta.get("product"),meta.get("component"),meta.get("document_family"),meta.get("source_group"))))
def _specificity(item):
 meta=item.get("metadata") or {};title=_raw_terms(item.get("title"));return {"product":str(meta.get("product") or "").casefold(),"component":str(meta.get("component") or "").casefold(),"title_terms":title}
def _group_key(item):return _identity(item) or str(item.get("title") or "")

def evaluate_item(item,query_text,fields=None,answer_context=None):
 fields=fields or {};answer_context=answer_context or {};details=fields.get("details") or {}
 stable=" ".join(str(x or "") for x in (query_text,fields.get("goal"),fields.get("contextual_operation"),fields.get("current_message")," ".join(str(v) for v in details.values())))
 q=_terms(stable);d=_document_terms(item);title_terms=_terms(item.get("title"));overlap=q&d;title_overlap=q&title_terms
 concept_q={x for x in q if x.startswith("concept:")};concept_match=concept_q&d
 coverage=len(overlap)/max(1,len(q));title_coverage=len(title_overlap)/max(1,len(q));concept_coverage=len(concept_match)/max(1,len(concept_q)) if concept_q else 0.0
 previous_ids=set(answer_context.get("source_identities") or []);follow=(fields.get("topic_relation") in {"same_topic","same_topic_refinement"} and fields.get("user_act") in {"follow_up","answer_to_question","request_elaboration","attempt_result","reported_failure","answer","confirmation"});continuity=0.20 if follow and _identity(item) in previous_ids else 0.0
 specific=_specificity(item);confirmed=" ".join(str(v).casefold() for v in details.values());product= specific["product"]
 product_bonus=0.12 if product and any(part and part in confirmed for part in re.split(r"[_\s-]+",product)) else 0.0
 # Penalize scope-heavy titles only when their distinctive terms are neither in the query nor in the previous answer context.
 prior_terms=_terms(answer_context.get("main_text_excerpt") or "");distinct={x for x in specific["title_terms"] if not x.startswith("concept:")} - {x for x in q if not x.startswith("concept:")} - {x for x in prior_terms if not x.startswith("concept:")}
 query_concepts={x for x in q if x.startswith("concept:")};document_concepts={x for x in d if x.startswith("concept:")}
 # Only meaning-changing qualifiers are restrictive. Context concepts such as user, device, printing, security or configuration must not be punished.
 restrictive={"concept:cost"};unrequested_concepts=(document_concepts-query_concepts)&restrictive
 modifier_penalty=min(0.32,0.20*len(unrequested_concepts))
 intent=str(fields.get("intent") or "").casefold();title_raw=_raw_terms(item.get("title"))
 conceptual_cues={"about","overview","definition","concept","introduccion","descripcion"};procedural_cues={"configure","configuration","install","enable","setup","configurar","instalar","habilitar"}
 intent_bonus=0.0
 if intent=="conceptual":intent_bonus=0.10 if title_raw&conceptual_cues else (-0.06 if title_raw&procedural_cues else 0.0)
 elif intent=="procedural":intent_bonus=0.08 if title_raw&procedural_cues else 0.0
 penalty=min(0.24,0.035*len(distinct))+modifier_penalty
 primary_bonus=0.0
 if item.get("carried_from_previous_answer") and fields.get("previous_evidence_role")=="primary" and overlap:
  primary_bonus=0.12
 score=max(0.0,min(1.0,0.42*coverage+0.22*title_coverage+0.24*concept_coverage+continuity+product_bonus+intent_bonus+primary_bonus-penalty))
 return {"score":round(score,4),"query_terms":sorted(q),"matched_terms":sorted(overlap),"title_matched_terms":sorted(title_overlap),"concept_matches":sorted(concept_match),"unconfirmed_title_terms":sorted(distinct)[:12],"continuity_boost":continuity,"product_context_bonus":product_bonus,"unrequested_concepts":sorted(unrequested_concepts),"modifier_penalty":round(modifier_penalty,4),"intent_affinity":round(intent_bonus,4),"primary_evidence_bonus":round(primary_bonus,4),"assumption_penalty":round(penalty,4)}

def _prior_evidence(answer_context):
 out=[]
 for item in (answer_context.get("active_document_evidence_ledger") or answer_context.get("cited_evidence") or []):
  row=copy.deepcopy(item);row["carried_from_previous_answer"]=True;out.append(row)
 return out

def apply_semantic_fit(retrieval,answer_context=None):
 result=copy.deepcopy(retrieval or {});query=result.get("query") or {};fields=query.get("fields") or {};follow=(fields.get("topic_relation") in {"same_topic","same_topic_refinement"} and fields.get("user_act") in {"follow_up","answer_to_question","request_elaboration","attempt_result","reported_failure","answer","confirmation"})
 evidence=list(result.get("evidence") or [])
 if follow:
  known={_chunk_identity(x) for x in evidence}
  for old in _prior_evidence(answer_context or {}):
   key=_chunk_identity(old)
   if key not in known:evidence.append(old);known.add(key)
 ranked=[]
 for pos,item in enumerate(evidence):
  row=copy.deepcopy(item);base_fit=evaluate_item(row,query.get("text") or "",fields,answer_context or {});fits=[("canonical",query.get("text") or "",base_fit)]
  for candidate in list(row.get("ranking_queries") or [])[-3:]:
   text=str((candidate or {}).get("text") or "").strip()
   if text:fits.append((str((candidate or {}).get("mode") or "candidate"),text,evaluate_item(row,text,fields,answer_context or {})))
  mode,ranking_query,fit=max(fits,key=lambda x:float((x[2] or {}).get("score",0.0)))
  fit=dict(fit);fit.update({"ranking_query_mode":mode,"ranking_query_used":ranking_query,"canonical_query_score":base_fit.get("score"),"candidate_count":max(0,len(fits)-1)})
  row["semantic_fit"]=fit;ranked.append((fit["score"],-pos,row))
 ranked.sort(reverse=True,key=lambda x:(x[0],x[1]));ordered=[x[2] for x in ranked]
 groups={}
 for row in ordered:groups.setdefault(_group_key(row),[]).append(row)
 group_scores=[]
 for key,items in groups.items():
  scores=sorted((x["semantic_fit"]["score"] for x in items),reverse=True);group_scores.append((round(0.72*scores[0]+0.28*(sum(scores[:3])/max(1,min(3,len(scores)))),4),key,items))
 group_scores.sort(reverse=True,key=lambda x:x[0]);selected_group=group_scores[0] if group_scores else (0.0,"",[])
 # Isolate generation evidence from diagnostic candidates. Generators must not mix documents accidentally.
 diagnostic=ordered
 generation=selected_group[2]
 result["diagnostic_evidence"]=diagnostic
 result["generation_evidence"]=generation
 result["evidence"]=generation
 best=selected_group[0];prior_quality=float(((result.get("selection") or {}).get("quality") or 0.0));combined=round(max(0.0,min(1.0,0.76*best+0.24*prior_quality)),4)
 result.setdefault("selection",{})["quality"]=combined
 primary_candidates=[x for x in ordered if x.get("carried_from_previous_answer") and fields.get("previous_evidence_role")=="primary" and float((x.get("semantic_fit") or {}).get("score",0.0))>=0.30]
 primary_selected=[]
 if primary_candidates:
  primary_doc=_identity(primary_candidates[0]);primary_best=float(primary_candidates[0]["semantic_fit"]["score"])
  primary_selected=[x for x in primary_candidates if _identity(x)==primary_doc and float(x["semantic_fit"]["score"])>=max(0.30,primary_best-0.08)][:4]
 if primary_selected:
  generation=primary_selected;selected_identity=_identity(primary_selected[0]);best=max(float(x["semantic_fit"]["score"]) for x in primary_selected);combined=max(combined,best);accepted=True;decision_path="primary_previous_evidence"
 else:
  selected_identity=selected_group[1];accepted=bool(generation) and best>0.0 and combined>=0.38;decision_path="group_threshold"
 if not accepted:generation=[];result["generation_evidence"]=[];result["evidence"]=[]
 else:result["generation_evidence"]=generation;result["evidence"]=generation
 carried=sum(1 for x in generation if x.get("carried_from_previous_answer"))
 provenance_modes=sorted({str((x.get("semantic_fit") or {}).get("ranking_query_mode") or "canonical") for x in diagnostic})
 selected_provenance_modes=sorted({str((x.get("semantic_fit") or {}).get("ranking_query_mode") or "canonical") for x in generation})
 result["semantic_fit"]={"version":VERSION,"ranking_query_modes":provenance_modes,"selected_ranking_query_modes":selected_provenance_modes,"query_provenance_preserved":any(x!="canonical" for x in provenance_modes),"best_group_score":best,"combined_quality":combined,"selected_document":selected_identity if accepted else None,"selected_group_ids":[str(x.get("id")) for x in generation],"carried_previous_evidence":carried,"previous_answer_sources_used":bool(carried),"accepted_for_generation":accepted,"low_fit":not accepted,"ranked_ids":[str(x.get("id")) for x in diagnostic],"generation_ids":[str(x.get("id")) for x in generation],"diagnostic_count":len(diagnostic),"generation_count":len(generation),"previous_evidence_primary_eligible":bool(primary_candidates),"previous_evidence_role":"primary" if carried else "none","decision_path":decision_path}
 result["followup_grounding"]={"followup_detected":follow,"previous_evidence_considered":len(_prior_evidence(answer_context or {})) if follow else 0,"previous_evidence_selected":carried,"global_retrieval_skipped_reason":"previous_evidence_sufficient" if carried else None}
 return result

def _ledger_signature(item):
    identity = _identity(item)
    page = str(item.get("page") or "")
    normalized = _norm(item.get("text") or "")
    digest = hashlib.sha256(normalized.encode()).hexdigest()[:16]
    return identity, page, digest


def _compact_evidence_row(item):
    title = str(item.get("title") or "").strip()
    return {
        "id": item.get("id"), "title": title, "source": item.get("source"),
        "url": item.get("url"), "page": item.get("page"),
        "text": " ".join(str(item.get("text") or "").split())[:1000],
        # Preserve provenance fields required by the source-access policy. These
        # values are metadata only; retaining them does not broaden retrieval or
        # authorize a download by itself. The access policy still validates the
        # vendor, approved PDF root, resolved path, file type and size.
        "metadata": {k:v for k,v in (item.get("metadata") or {}).items()
                     if k in {
                         "product", "component", "document_family",
                         "canonical_url", "source_url", "source_group",
                         "vendor", "source_type", "title",
                         "source_access", "access", "organization",
                     }},
    }


def _guidance_candidates(text):
    rows=[]
    blocks=re.split(r"(?m)(?=^\s*(?:[-*+] |(?:\*\*)?\d+[.)]\s+|#{2,4}\s+))",str(text or ""))
    for block in blocks:
        value=" ".join(block.split()).strip()
        value=re.sub(r"^(?:[-*+] |(?:\*\*)?\d+[.)]\s+|#{2,4}\s+)","",value).strip(" *_:#")
        if not value or len(value)<12 or value.startswith("[") or value.casefold().startswith("fuentes"):
            continue
        first=re.split(r"(?<=[.!?])\s+",value,1)[0][:240].strip()
        if first and len(first.split())>=3: rows.append((first,value[:420]))
    return rows[:12]


def capture_answer_context(result, previous_context=None):
    answer=result.get("answer") or {}; retrieval=result.get("retrieval") or {}; text=str(answer.get("text") or "").strip()
    if not text:return {}
    cited=set(re.findall(r"\[(R\d+)\]",text)); evidence=retrieval.get("evidence") or []
    current=[copy.deepcopy(e) for e in evidence if not cited or str(e.get("id")) in cited]
    previous_context=previous_context or {}; continuity=result.get("document_continuity") or {}
    same_topic=bool(continuity.get("same_topic") or continuity.get("primary") or str((result.get("understanding") or {}).get("topic_relation") or "") in {"same_topic","same_topic_refinement","return_to_previous"})
    prior_ledger=previous_context.get("active_document_evidence_ledger") or previous_context.get("cited_evidence") or []
    current_ids=[]
    for item in current:
        identity=_identity(item)
        if identity and identity not in current_ids:current_ids.append(identity)
    if current:
        ledger=list(current)
        if continuity.get("primary") and current_ids: ledger += [copy.deepcopy(x) for x in prior_ledger if _identity(x) in current_ids]
    elif same_topic: ledger=[copy.deepcopy(x) for x in prior_ledger]
    else: ledger=[]
    def compact(rows,maximum):
        out=[];seen=set()
        for item in rows:
            sig=_ledger_signature(item)
            if sig in seen:continue
            seen.add(sig);out.append(_compact_evidence_row(item))
            if len(out)>=maximum:break
        return out
    current_compact=compact(current,8);ledger_compact=compact(ledger,12)
    identities=[];titles=[]
    for item in ledger_compact or current_compact:
        identity=_identity(item)
        if identity and identity not in identities:identities.append(identity)
        title=str(item.get("title") or "").strip()
        if title and title not in titles:titles.append(title)
    normalized=" ".join(text.split()); inverted=list(re.finditer(r"¿[^?]{1,420}\?",normalized)); closing=inverted[-1].group(0).strip() if inverted else None
    semantic_memory=(((result.get("documented_answer") or {}).get("validation") or {}).get("semantic_memory") or {})
    current_checks=[]
    for item in semantic_memory.get("pending_checks") or []:
        key=" ".join(str((item or {}).get("check_key") or "").split()).strip().casefold();action=" ".join(str((item or {}).get("action") or "").split()).strip()
        if key and action:current_checks.append({"check_key":key,"action":action,"excerpt":action,"status":"delivered","origin":"assistant_structured_memory","guidance_kind":"pending_check","semantic_signature":sorted(_terms(action))})
    prior=[copy.deepcopy(x) for x in previous_context.get("delivered_guidance") or []] if same_topic else []
    by_key={}
    unkeyed=[]
    for item in prior:
        key=" ".join(str((item or {}).get("check_key") or "").split()).strip().casefold()
        if key:by_key[key]=item
        else:unkeyed.append(item)
    for item in current_checks:by_key[item["check_key"]]=item
    guidance=unkeyed+list(by_key.values())
    hypotheses=[]
    for item in semantic_memory.get("documented_hypotheses") or []:
        key=" ".join(str((item or {}).get("hypothesis_key") or "").split()).strip().casefold();summary=" ".join(str((item or {}).get("summary") or "").split()).strip();conditions=[" ".join(str(x or "").split()).strip() for x in (item or {}).get("required_conditions") or [] if str(x or "").strip()]
        if key and summary and conditions:hypotheses.append({"hypothesis_key":key,"summary":summary,"required_conditions":conditions,"status":"unconfirmed","origin":"assistant_structured_memory"})
    verdict=retrieval.get("evidence_verdict") or {}
    authority={"status":verdict.get("status"),"reason":verdict.get("reason"),"mode":verdict.get("mode"),"accepted":verdict.get("accepted")}
    if not any(authority.values()) and same_topic:authority=copy.deepcopy(previous_context.get("evidence_authority") or {})
    return {"answer_mode":answer.get("mode"),"goal":(result.get("understanding") or {}).get("current_goal"),
      "main_text_excerpt":normalized[:1000],"evidence_ledger_version":"active_primary_document_v4_semantic_guidance",
      "cumulative_evidence_count":len(ledger_compact),"closing_question":closing,"source_identities":identities,"source_titles":titles,
      "cited_ids":sorted(cited),"cited_evidence":ledger_compact,"current_answer_cited_evidence":current_compact,
      "active_document_evidence_ledger":ledger_compact,"delivered_guidance":guidance,"documented_hypotheses":hypotheses,"evidence_authority":authority,
      "finish_reason":answer.get("finish_reason"),"partial":str(answer.get("mode") or "").endswith("_partial") or str(answer.get("finish_reason") or "").casefold() in {"length","max_tokens"},
      "historical_document_context_preserved":bool(not current and same_topic and ledger_compact)}
