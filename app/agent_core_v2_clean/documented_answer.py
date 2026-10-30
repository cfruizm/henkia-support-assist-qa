from __future__ import annotations
import hashlib
import json
import re
import unicodedata
from collections import defaultdict
from .models import AgentResponse
from .source_footer import compact_sources, strip_generated_source_footer
from .diagnostic_language import soften_diagnostic_certainty
from .guidance_integrity import build_guidance_integrity_contract, integrity_diagnostic
from .evidence_boundary import normalize_citation_groups
from .documented_fact_coverage import augment_exhaustive_numeric_evidence,ensure_enumerated_numeric_fact_coverage,expects_exhaustive_numeric_list,numeric_enumeration_evidence_score,collect_compact_numeric_rows

PROMPT_VERSION = "documented_v18_localized_conceptual_authority"
SYSTEM = """Eres un colega de soporte empresarial de impresion. Responde unicamente con la evidencia documental suministrada y usa el idioma del usuario. Se util, directo y natural. No inventes menus, pasos, requisitos, relaciones ni funciones. Cada afirmacion factual debe terminar con una o mas citas [R#].

Ajusta la forma al objetivo:
- conceptual: empieza con una definicion o descripcion directa. Despues explica proposito, capacidades o componentes solamente cuando esten respaldados. No conviertas una definicion en una lista completa de requisitos.
- requirements: sintetiza todas las categorias de condiciones previas respaldadas por el conjunto de evidencia, no solo por el primer fragmento. Separa categorias y conserva alternativas como alternativas.
- procedural: conserva el orden documental y no rellenes pasos ausentes.

Integra fragmentos complementarios del mismo documento y de paginas posteriores. No copies un unico enunciado si otros fragmentos autorizados agregan capacidades materialmente distintas. Si una parte solicitada no aparece, responde primero todo lo que si esta documentado y declara la limitacion de forma localizada. Nunca afirmes ausencia global sin revisar todos los fragmentos. En seguimientos del mismo caso, no vuelvas a definir, presentar ni describir el producto. Empieza por el nuevo hecho confirmado, su implicación y la siguiente comprobación respaldada. Prioriza cobertura completa y concisa sobre detalle secundario. Para una consulta inicial usa como máximo 320 palabras; para un seguimiento del mismo caso usa como máximo 220 palabras. En troubleshooting prioriza la implicación del dato nuevo y hasta tres comprobaciones de mayor valor diagnóstico. No repitas definiciones, contexto, fuentes equivalentes ni recomendaciones ya realizadas. En seguimientos usa máximo 180 palabras y no más de tres comprobaciones numeradas. Continúa primero una comprobación truncada. No repitas acciones incluidas en already_delivered_guidance. Las recomendaciones mostradas anteriormente NO son acciones ejecutadas. Considera realizada una validación únicamente cuando aparezca en user_confirmed_attempts. Nunca uses expresiones de ejecución previa, como afirmar que algo ya fue verificado, basándote solo en assistant_delivered_guidance. Si una acción no está confirmada, mantenla como pendiente y redáctala en futuro o como instrucción. Antes de publicar una acción, evalúa semánticamente su impacto y reversibilidad. Si puede causar pérdida de configuración o datos, interrupción, impacto amplio, cambios de seguridad/acceso o rollback difícil, no la presentes como acción rutinaria ni temprana: indica condición de uso, impacto, prerrequisitos de respaldo/recuperación, autorización o ventana cuando apliquen, y ofrece escalamiento si no puede ejecutarse con seguridad. No declares una causa o capa descartada salvo evidencia explícita. Una validación correcta solo reduce probabilidad; formula la siguiente hipótesis como ampliación del diagnóstico, no como causa confirmada ni exclusión definitiva. No afirmes que una capa está operativa, descartada o es la causa a partir de una observación indirecta. Una acción fallida confirma únicamente que esa acción no resolvió el incidente. En troubleshooting genera primero este bloque interno exacto: `<semantic_memory>{"pending_checks":[{"check_key":"semantic_goal_key","action":"pending action in the user's language"}],"documented_hypotheses":[{"hypothesis_key":"semantic_hypothesis_key","summary":"conditional possibility in the user's language","required_conditions":["unconfirmed condition"]}]}</semantic_memory>`. Cada `check_key` debe expresar el objetivo diagnóstico estable y ser equivalente entre idiomas; reutiliza el mismo key cuando la comprobación nueva persigue el mismo objetivo, aunque cambien idioma, citas o redacción. Incluye como máximo dos comprobaciones internas y ordénalas por valor diagnóstico. Cada hipótesis debe usar lenguaje de posibilidad, nunca causalidad consumada, e incluir condiciones necesarias todavía no confirmadas. Después del bloque escribe una respuesta visible natural en el idioma del usuario. No muestres ni menciones el bloque. Comienza reconociendo únicamente los hechos confirmados y explica que esos hechos ajustan prioridades, pero no confirman ni excluyen una causa o capa. En la respuesta visible presenta una sola comprobación discriminante como siguiente paso; conserva las demás únicamente en la memoria interna. No presentes soluciones de configuración hasta confirmar que el escenario documental aplica. Usa máximo 180 palabras, una sola lista si es necesaria y una sola pregunta. El bloque no incluye hechos ni resultados confirmados. Distingue requisitos generales documentados de requisitos adicionales o exclusivos que la fuente no especifica. Una ausencia cualificada no contradice requisitos generales confirmados. No menciones procesos internos del laboratorio."""

_STOP = {
    "cuales", "cual", "especificamente", "requisitos", "requisito", "necesito",
    "identify", "specific", "requirements", "subject", "para", "sobre", "tiene",
    "tienen", "del", "los", "las", "son", "que", "what", "which", "documentado",
    "documentada", "documentacion", "informacion", "explica", "explicar", "define",
}


def _norm(value):
    return " ".join(
        "".join(c for c in unicodedata.normalize("NFKD", str(value or "").casefold()) if not unicodedata.combining(c)).split()
    )


def _terms(value):
    return {
        x for x in re.findall(r"[a-z0-9]+", _norm(value))
        if len(x) >= 4 and x not in _STOP
    }


def _identity(item):
    meta = item.get("metadata") or {}
    return str(item.get("url") or item.get("source") or meta.get("canonical_url") or item.get("title") or "")


def _page_key(item):
    return (_identity(item), str(item.get("page") or (item.get("metadata") or {}).get("page_label") or ""))


def _candidate_rows(retrieval):
    verdict = retrieval.get("evidence_verdict") or {}
    rows = verdict.get("selected_evidence") or retrieval.get("generation_evidence") or retrieval.get("evidence") or []
    out, seen = [], set()
    for row in rows:
        text = " ".join(str(row.get("text") or "").split())
        if len(text) < 40:
            continue
        signature = hashlib.sha256((str(_page_key(row)) + text.casefold()).encode()).hexdigest()
        if signature in seen:
            continue
        seen.add(signature)
        clean = dict(row)
        clean["text"] = text
        out.append(clean)
    return out


def evidence_pack(retrieval, message="", understanding=None, max_items=6, max_chars=6200):
    followup=(str((understanding or {}).get("user_act") or "") in {"follow_up","answer_to_question","request_elaboration","attempt_result","reported_failure"} or str((understanding or {}).get("topic_relation") or "") in {"same_topic","return_to_previous"})
    enumerative_numeric=expects_exhaustive_numeric_list(message)
    if followup and not enumerative_numeric:max_items,max_chars=min(max_items,4),min(max_chars,4500)
    """Select a diverse, relevance-ordered evidence set without losing later pages."""
    rows = _candidate_rows(retrieval)
    wanted = _terms(" ".join((str(message or ""), str((understanding or {}).get("current_goal") or ""))))
    scored = []
    for position, row in enumerate(rows):
        body_terms = _terms(" ".join((str(row.get("title") or ""), row["text"])))
        overlap = len(wanted & body_terms) / max(1, len(wanted))
        semantic = float((row.get("semantic_fit") or {}).get("score", 0.0) or 0.0)
        numeric_table = numeric_enumeration_evidence_score(message,row) if enumerative_numeric else 0.0
        scored.append((0.52 * overlap + 0.20 * semantic + 0.60 * numeric_table, -position, row))
    scored.sort(reverse=True, key=lambda value: (value[0], value[1]))

    # First pass preserves page/document diversity. Second pass fills remaining capacity.
    buckets = defaultdict(list)
    for score, position, row in scored:
        buckets[_page_key(row)].append((score, position, row))
    ordered = [values[0] for values in buckets.values()]
    ordered.sort(reverse=True, key=lambda value: (value[0], value[1]))
    selected_ids = {id(value[2]) for value in ordered}
    ordered.extend(value for value in scored if id(value[2]) not in selected_ids)

    compact_numeric_rows=collect_compact_numeric_rows(message,rows,maximum=max_items) if enumerative_numeric else []
    items, used = [], 0
    compact_signatures=set()
    for item in compact_numeric_rows:
        size=len(json.dumps(item,ensure_ascii=False))
        if items and used+size>max_chars:continue
        items.append(item);used+=size
        compact_signatures.add((str(item.get("id") or ""),str(item.get("numeric_table_value") or "")))
        if len(items)>=max_items:break
    for _, _, row in ordered:
        item = {
            "id": row.get("id"), "title": row.get("title"), "page": row.get("page"),
            "source": row.get("url") or row.get("source"), "text": row["text"][:2200],
        }
        if any(str(row.get("id") or "")==signature[0] for signature in compact_signatures) and len(items)>=max_items-1:
            continue
        size = len(json.dumps(item, ensure_ascii=False))
        if items and used + size > max_chars:
            continue
        items.append(item)
        used += size
        if len(items) >= max_items:
            break
    return items


def requested_dimensions(message, understanding):
    subject = _terms((understanding or {}).get("canonical_subject") or (understanding or {}).get("goal_updates", {}).get("subject"))
    return sorted(_terms(message) - subject)


def dimension_coverage(message, understanding, evidence):
    terms = requested_dimensions(message, understanding)
    body = _norm(" ".join(str(x.get("text") or "") for x in evidence))
    covered = [x for x in terms if x in body]
    return {"requested": terms, "covered": covered, "missing": [x for x in terms if x not in body], "sufficient": not terms or bool(covered)}


def _negative_claim_scope(text):
    """Classify documentary absence by linguistic scope, never by product terms.

    A qualified absence concerns additional/specific conditions and may coexist
    with general documented requirements. An unqualified absence denies the
    documented dimension itself and can contradict positive evidence.
    """
    value = _norm(text)
    qualifiers = (
        "adicional", "adicionales", "especifico", "especificos",
        "especificas", "exclusivo", "exclusiva", "exclusivos", "exclusivas",
        "distinto", "distinta", "distintos", "distintas", "particular",
        "particulares", "propio", "propia", "propios", "propias", "extra",
        "additional", "specific", "exclusive", "different", "particular",
    )
    words = set(re.findall(r"[a-z0-9]+", value))
    return "qualified" if words.intersection(qualifiers) else "general"


def contradicted_absence(text, message, understanding, evidence):
    body = _norm(text)
    absence = any(x in body for x in (
        "no especifica", "no contiene", "no detalla", "no proporciona", "no documenta",
        "no es posible responder", "not specify", "not contain", "not document",
    ))
    coverage = dimension_coverage(message, understanding, evidence)
    scope = _negative_claim_scope(text)
    coverage["negative_claim_scope"] = scope
    # General positive requirements and qualified absence can both be true.
    return bool(absence and scope == "general" and coverage["covered"]), coverage


def _remove_contradicted_absence_claims(text, message, understanding, evidence):
    """Remove only unqualified negative blocks that contradict positive evidence.

    Qualified limitations such as additional or environment-specific requirements
    are preserved. The repair is structural, domain-independent and uses no extra
    model call.
    """
    contradiction, coverage = contradicted_absence(text, message, understanding, evidence)
    if not contradiction:
        return str(text or ""), False, coverage
    markers = (
        "no especifica", "no contiene", "no detalla", "no proporciona", "no documenta",
        "no es posible responder", "not specify", "not contain", "not document",
    )
    value = str(text or "").strip()
    lines = value.splitlines()
    # Mixed positive and negative claims may share one paragraph. Remove only the
    # unqualified negative sentence while preserving cited positive sentences.
    sentences = [x.strip() for x in re.split(r"(?<=[.!?])\s+", value) if x.strip()]
    if len(sentences) > 1 and not any(re.match(r"^\s*(?:[-*+]\s+|\d+[.)]\s+)", line) for line in lines):
        kept_sentences = [
            sentence for sentence in sentences
            if not (any(marker in _norm(sentence) for marker in markers)
                    and _negative_claim_scope(sentence) == "general")
        ]
        sentence_text = " ".join(kept_sentences).strip()
        if len(kept_sentences) < len(sentences) and re.search(r"\[(R\d+)\]", sentence_text):
            return sentence_text, True, coverage
    heading = lambda line: bool(re.match(r"^\s*(?:#{1,6}\s+|\*\*[^*]+\*\*\s*$)", line))
    sections, current = [], []
    for line in lines:
        if heading(line) and current:
            sections.append(current); current = [line]
        else:
            current.append(line)
    if current:
        sections.append(current)
    bad = []
    for index, section in enumerate(sections):
        body = _norm("\n".join(section))
        if any(marker in body for marker in markers) and _negative_claim_scope(body) == "general":
            bad.append(index)
    survivors = [section for index, section in enumerate(sections) if index not in bad]
    survivor_text = "\n".join("\n".join(x) for x in survivors).strip()
    if bad and survivor_text and re.search(r"\[(R\d+)\]", survivor_text):
        repaired = survivor_text
    else:
        kept, suppress_list = [], False
        for line in lines:
            is_list = bool(re.match(r"^\s*(?:[-*+]\s+|\d+[.)]\s+)", line))
            if suppress_list and is_list:
                continue
            if suppress_list and not is_list and line.strip():
                suppress_list = False
            low = _norm(line)
            if any(marker in low for marker in markers) and _negative_claim_scope(low) == "general":
                suppress_list = True
                continue
            kept.append(line)
        repaired = "\n".join(kept).strip()
    return repaired or value, repaired != value, coverage



def localize_documentary_absence_claims(text):
    """Keep limitations local to the evidence supplied to this answer."""
    value = str(text or "")
    repairs = (
        (r"(?i)\bno se documentan en los fragmentos proporcionados\b",
         "En los fragmentos utilizados para esta respuesta no se incluyeron"),
        (r"(?i)\bno se documenta en los fragmentos proporcionados\b",
         "En los fragmentos utilizados para esta respuesta no se incluyó"),
        (r"(?i)\bno se documentan en la evidencia proporcionada\b",
         "En la evidencia utilizada para esta respuesta no se incluyeron"),
        (r"(?i)\bno se documenta en la evidencia proporcionada\b",
         "En la evidencia utilizada para esta respuesta no se incluyó"),
        (r"(?i)\bthe provided fragments do not document\b",
         "The evidence used for this answer did not include"),
        (r"(?i)\bthe supplied evidence does not document\b",
         "The evidence used for this answer did not include"),
    )
    applied = []
    for pattern, replacement in repairs:
        value, count = re.subn(pattern, replacement, value)
        if count:
            applied.append({"pattern": pattern, "count": count})
    return value, {"applied": bool(applied), "repairs": applied,
                   "authority": "current_response_evidence_only"}

def validate_citations(text, ids):
    cited = set(re.findall(r"\[(R\d+)\]", text or ""))
    return bool(str(text or "").strip()) and bool(cited) and cited.issubset(set(ids)), sorted(cited)

def _localized_conceptual_authority(text, retrieval, intent):
    """Localize a conceptual answer when evidence only documents a feature.

    The evidence verdict, not product vocabulary, activates this guard. It removes
    global identity or primary-purpose claims from the generated draft while
    preserving complete cited capability statements. No internal knowledge is
    added and no second model call is made.
    """
    verdict = (retrieval or {}).get("evidence_verdict") or {}
    authority = verdict.get("conceptual_authority") or {}
    required = bool(
        str(intent or "").casefold() == "conceptual"
        and str(verdict.get("status") or "").casefold() == "partial"
        and authority.get("localized_limitation_required")
    )
    diagnostic = {
        "required": required,
        "applied": False,
        "removed_global_claims": 0,
        "reason": verdict.get("reason"),
    }
    value = strip_generated_source_footer(str(text or "").strip())
    if not required or not value:
        return value, diagnostic
    global_claims = (
        r"\b(?:su|el|la)\s+prop[oó]sito\s+principal\b",
        r"\b(?:su|el|la)\s+funci[oó]n\s+principal\b",
        r"\b(?:principalmente|fundamentalmente)\s+(?:se\s+)?(?:utiliza|usa|sirve)\b",
        r"\b(?:is|are|es|son)\s+(?:una?|an?|el|la)\s+(?:soluci[oó]n|plataforma|sistema|producto|servicio)\b",
    )
    blocks = re.split(r"(?<=\.)\s+|\n{2,}", value)
    kept, removed = [], 0
    for block in blocks:
        candidate = block.strip()
        if not candidate:
            continue
        if any(re.search(pattern, _norm(candidate), re.I) for pattern in global_claims):
            removed += 1
            continue
        kept.append(candidate)
    body = "\n\n".join(kept).strip()
    valid_ids = {str(item.get("id")) for item in (verdict.get("selected_evidence") or []) if item.get("id")}
    body_citations = set(re.findall(r"\[(R\d+)\]", body))
    if not body or not body_citations or not body_citations.issubset(valid_ids):
        diagnostic.update({"applied": False, "removed_global_claims": removed, "safe_body_available": False})
        return value, diagnostic
    prefix = (
        "La documentación recuperada no proporciona una definición general completa del producto. "
        "Sí documenta la siguiente capacidad específica:"
    )
    diagnostic.update({"applied": True, "removed_global_claims": removed, "safe_body_available": True})
    return prefix + "\n\n" + body, diagnostic


def safe_cited_partial(text, valid_ids, finish_reason):
    """Return only content ending at the last complete authorized citation.

    The decision is structural and domain-independent. It does not inspect
    products, symptoms, actions, customers, URLs, or test-campaign phrases.
    """
    if str(finish_reason or "").casefold() not in {"length", "max_tokens"}:
        return None, []
    value = str(text or "").strip()
    allowed = set(map(str, valid_ids or []))
    matches = [m for m in re.finditer(r"\[(R\d+)\]", value) if m.group(1) in allowed]
    if not matches:
        return None, []
    partial = value[:matches[-1].end()].rstrip()
    cited = sorted(set(re.findall(r"\[(R\d+)\]", partial)))
    if not partial or not cited or not set(cited).issubset(allowed):
        return None, []
    return partial, cited


def visible_truncation_fallback(evidence):
    """Build a visible, source-only terminal fallback without another LLM call."""
    ids = [str(item.get("id")) for item in evidence or [] if item.get("id")]
    text = ("La generación documentada alcanzó el límite antes de producir un bloque completo "
            "y citado. Para evitar publicar una instrucción incompleta, no se mostrará el texto "
            "truncado ni se ejecutará un segundo compositor en este turno.")
    footer = compact_sources(evidence, ids)
    return text + ("\n\n" + footer if footer else "")


def answer_fingerprint(message, understanding, retrieval, model=""):
    payload = {
        "q": " ".join(str(message).split()).casefold(), "goal": understanding.get("current_goal"),
        "intent": understanding.get("intent"), "retrieval": (retrieval.get("query") or {}).get("fingerprint"),
        "evidence": [(e.get("id"), e.get("url") or e.get("source"), e.get("page")) for e in _candidate_rows(retrieval)],
        "model": model, "prompt": PROMPT_VERSION,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:24]


def readable_sources(evidence, cited_ids):
    by_id = {str(e.get("id")): e for e in evidence}
    return [f"[{rid}] {by_id[rid].get('title') or 'Fuente sin titulo'}, pagina {by_id[rid].get('page') or 'N/D'}" for rid in cited_ids if rid in by_id]



def _compact_followup_checks(text, understanding, maximum=3):
    # Numbered-answer truncation used to run before citation validation. If the
    # model placed the citation on a later list item, truncation removed the only
    # citation and caused a false citation guard. Token limits and the prompt's
    # coverage contract already control length, so preserve the complete cited
    # structure here.
    return str(text or "")


_SEMANTIC_OPEN="<semantic_memory>"
_SEMANTIC_CLOSE="</semantic_memory>"

def extract_semantic_memory(text):
    value=str(text or "");start=value.find(_SEMANTIC_OPEN);end=value.find(_SEMANTIC_CLOSE)
    empty={"pending_checks":[],"documented_hypotheses":[],"parsed":False}
    if start<0 or end<start:return value.strip(),empty
    raw=value[start+len(_SEMANTIC_OPEN):end].strip();visible=(value[:start]+value[end+len(_SEMANTIC_CLOSE):]).strip()
    try:data=json.loads(raw)
    except Exception:return visible,empty
    checks=[];seen=set()
    for row in data.get("pending_checks") or []:
        if not isinstance(row,dict):continue
        key=" ".join(str(row.get("check_key") or "").split()).strip().casefold()
        action=" ".join(str(row.get("action") or "").split()).strip()
        if not key or not action or key in seen:continue
        seen.add(key);checks.append({"check_key":key[:120],"action":action[:320]})
        if len(checks)>=3:break
    hypotheses=[];seen=set()
    for row in data.get("documented_hypotheses") or []:
        if not isinstance(row,dict):continue
        key=" ".join(str(row.get("hypothesis_key") or "").split()).strip().casefold()
        summary=" ".join(str(row.get("summary") or "").split()).strip()
        conditions=[" ".join(str(x or "").split()).strip()[:240] for x in row.get("required_conditions") or [] if str(x or "").strip()][:4]
        if not key or not summary or not conditions or key in seen:continue
        seen.add(key);hypotheses.append({"hypothesis_key":key[:120],"summary":summary[:320],"required_conditions":conditions,"status":"unconfirmed"})
        if len(hypotheses)>=2:break
    return visible,{"pending_checks":checks,"documented_hypotheses":hypotheses,"parsed":True}

class DocumentedAnswerComposer:
    def __init__(self, gateway, max_tokens=360):
        self.gateway = gateway
        self.max_tokens = max(320, min(900, int(max_tokens)))
        self.last_provider_result = {}
        self.validation = {}

    def compose(self, message, understanding, retrieval):
        retrieval, exhaustive_evidence_expansion = augment_exhaustive_numeric_evidence(retrieval, message)
        intent = str(understanding.get("intent") or "").casefold()
        requirements = intent == "requirements"
        conceptual = intent == "conceptual"
        evidence = evidence_pack(
            retrieval, message, understanding,
            max_items=10 if requirements else 10 if conceptual else 8,
            max_chars=11000 if requirements else 10000 if conceptual else 8000,
        )
        if not evidence:
            return AgentResponse("La recuperacion no contiene evidencia suficiente para responder de forma documentada.", "documented_insufficient", False)
        from app.llm_gateway.models import LLMRequest
        previous=dict(retrieval.get("_answer_context") or {})
        followup=(str(understanding.get("user_act") or "") in {"follow_up","answer_to_question","request_elaboration","attempt_result","reported_failure"} or str(understanding.get("topic_relation") or "") in {"same_topic","return_to_previous"})
        integrity_contract=build_guidance_integrity_contract(retrieval)
        payload = {
            "question": message, "intent": intent, "goal": understanding.get("current_goal"),"followup":followup,
            "already_delivered_guidance":list(previous.get("delivered_guidance") or [])[:8],"previous_answer_partial":bool(previous.get("partial")),
            "guidance_integrity_contract":integrity_contract,
            "user_confirmed_attempts":integrity_contract["user_confirmed_attempts"],
            "assistant_delivered_guidance":integrity_contract["assistant_delivered_guidance"],
            "causal_authority_contract":{"confirmed_case_facts":retrieval.get("_case_context") or {},"confirmed_attempts":integrity_contract["user_confirmed_attempts"],"document_conditions_are_unconfirmed":True,"failed_attempt_confirms_only_non_resolution":True,"negative_exclusion_requires_explicit_evidence":True},
            "conceptual_authority_contract": {
                "status": (retrieval.get("evidence_verdict") or {}).get("status"),
                "reason": (retrieval.get("evidence_verdict") or {}).get("reason"),
                "authority": (retrieval.get("evidence_verdict") or {}).get("conceptual_authority") or {},
                "rule": "When localized_limitation_required is true, do not define the product globally or state its main purpose. Describe only the documented capability and state the limitation locally.",
            },
            "coverage_contract": {
                "use_all_relevant_fragments": not followup,
                "preserve_later_page_information": True,
                "definition_does_not_imply_full_requirements": conceptual,
                "max_numbered_checks":3 if followup else None,
                "required_shape": "definition_purpose_capabilities_if_supported" if conceptual else "requirement_categories" if requirements else "proportional",
                "enumerative_numeric_request": expects_exhaustive_numeric_list(message),
                "enumerative_numeric_rule": "When true, answer first with the complete numeric list supported by compact table rows, preserving protocol/scope/purpose. Put URLs and notes after the list.",
            },
            "evidence": evidence,
        }
        limit = 760 if requirements else 620 if conceptual else self.max_tokens
        result = self.gateway.complete(LLMRequest(
            [{"role": "system", "content": SYSTEM}, {"role": "user", "content": json.dumps(payload, ensure_ascii=False, separators=(",", ":"))}],
            "agent_core_v2_clean_documented_answer", limit, 0.0, None,
        ))
        self.last_provider_result = result.to_dict()
        if not result.ok:
            return AgentResponse("Encontre documentacion, pero no pude redactar la respuesta en este turno. Las fuentes recuperadas se conservaron.", "documented_provider_degraded", False)
        localized_text,absence_localization=localize_documentary_absence_claims(str(result.text or ""))
        visible_text,semantic_memory=extract_semantic_memory(localized_text)
        # Providers may group valid documentary references as [R1, R3, R5].
        # Normalize that equivalent notation before every downstream citation,
        # truncation and coverage check so valid evidence is not falsely rejected.
        visible_text = normalize_citation_groups(visible_text)
        text = _compact_followup_checks(visible_text,understanding)
        text, conceptual_authority_publication = _localized_conceptual_authority(text, retrieval, intent)
        text,certainty_softened = soften_diagnostic_certainty(text,intent)
        text, negative_claim_removed, dimension_check = _remove_contradicted_absence_claims(
            text, message, understanding, evidence
        )
        text, enumerated_fact_coverage = ensure_enumerated_numeric_fact_coverage(text, message, evidence)
        contradiction, _ = contradicted_absence(text, message, understanding, evidence)
        valid_ids = [str(x["id"]) for x in evidence]
        valid, cited = validate_citations(text, valid_ids)
        truncated = str(result.finish_reason or "").casefold() in {"length", "max_tokens"}
        partial_text, partial_cited = safe_cited_partial(text, valid_ids, result.finish_reason)
        safe_partial = bool(truncated and partial_text)
        if safe_partial:
            text, cited = partial_text, partial_cited
        cited_pages = {str(x.get("page") or "") for x in evidence if str(x.get("id")) in cited and x.get("page") not in (None, "")}
        available_pages = {str(x.get("page") or "") for x in evidence if x.get("page") not in (None, "")}
        required_page_coverage = min(3, len(available_pages)) if requirements else min(2, len(available_pages)) if conceptual else 1
        complete_page_coverage = bool(cited) if not available_pages else len(cited_pages) >= required_page_coverage
        partial_page_coverage = bool(cited) and (safe_partial or (available_pages and not complete_page_coverage))
        page_coverage_valid = complete_page_coverage or partial_page_coverage
        coverage_partial = bool(valid and cited and not complete_page_coverage and available_pages and not contradiction)
        valid = bool((valid or safe_partial) and page_coverage_valid and not contradiction)
        self.validation = {
            "citations_valid": valid, "cited_ids": cited, "finish_reason": result.finish_reason,
            "truncated": truncated, "published_partial": bool(valid and (safe_partial or coverage_partial)),
            "safe_partial_terminal": bool(valid and safe_partial),
            "coverage_partial_terminal": bool(valid and coverage_partial),
            "visible_truncation_fallback": bool(truncated and not safe_partial),
            "evidence_pages": sorted(available_pages), "cited_pages": sorted(cited_pages),
            "required_page_coverage": required_page_coverage, "page_coverage_valid": page_coverage_valid,
            "requested_dimension_coverage": dimension_check, "contradicted_absence_blocked": contradiction,
            "contradicted_negative_claim_removed": negative_claim_removed,
            "evidence_items_supplied": len(evidence), "prompt_version": PROMPT_VERSION,
            "diagnostic_certainty_softened": certainty_softened,
            "conceptual_authority_publication": conceptual_authority_publication,
            "guidance_integrity": integrity_diagnostic(integrity_contract),
            "semantic_memory":semantic_memory,
            "documentary_absence_localization":absence_localization,
            "exhaustive_evidence_expansion":exhaustive_evidence_expansion,
            "enumerated_fact_coverage":enumerated_fact_coverage,
            "compact_numeric_rows_supplied":sum(1 for item in evidence if item.get("numeric_table_value")),
            "visible_answer_decoupled":bool(semantic_memory.get("parsed")),
        }
        if contradiction:
            return AgentResponse("La respuesta generada contradecia la evidencia documental recuperada y fue bloqueada antes de publicarse. Intenta nuevamente para regenerar la sintesis documentada.", "documented_evidence_contradiction_guard", False, result.provider, result.model, result.usage, result.finish_reason)
        if truncated and not safe_partial:
            text = visible_truncation_fallback(evidence)
            return AgentResponse(text, "documented_truncation_safe_defer", False, result.provider, result.model, result.usage, "safe_defer")
        if not valid:
            return AgentResponse("Encontre documentacion, pero la respuesta generada no cubrio suficientemente la evidencia o no supero la validacion de citas.", "documented_citation_guard", False, result.provider, result.model, result.usage, result.finish_reason)
        text=strip_generated_source_footer(text)
        if safe_partial:
            text += "\n\n> Respuesta parcial segura: el proveedor alcanzó el límite de salida. Se publicó únicamente el contenido completo y citado disponible."
        elif coverage_partial:
            text += "\n\n> Cobertura documental parcial: se publicó únicamente la orientación respaldada por las fuentes citadas."
        footer = compact_sources(evidence, cited)
        if footer:text += "\n\n" + footer
        authority_partial = bool(conceptual_authority_publication.get("applied"))
        if authority_partial and "> Cobertura documental parcial:" not in text:
            text += "\n\n> Cobertura documental parcial: la fuente recuperada documenta una capacidad específica, no una definición general completa."
        self.validation["published_partial"] = bool(valid and (safe_partial or coverage_partial or authority_partial))
        self.validation["conceptual_authority_partial_terminal"] = authority_partial
        partial = safe_partial or coverage_partial or negative_claim_removed or authority_partial
        finish = ("safe_partial" if safe_partial else "coverage_partial" if coverage_partial
                  else "conceptual_authority_partial" if authority_partial
                  else "negative_claim_repaired" if negative_claim_removed else result.finish_reason)
        return AgentResponse(text, "documented_answer_partial" if partial else "documented_answer", True, result.provider, result.model, result.usage, finish)
