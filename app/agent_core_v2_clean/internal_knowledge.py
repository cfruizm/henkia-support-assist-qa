from __future__ import annotations
import hashlib
import json
import re
import unicodedata
from .models import AgentResponse
from .answer_context_policy import enrich_internal_payload
from .documentation_limitation import user_message as limitation_user_message
from .guidance_integrity import build_guidance_integrity_contract, integrity_diagnostic

PROMPT_VERSION = "controlled_internal_knowledge_v19_documented_requirements_safe_diagnosis"
WARNING = "⚠️ **Orientación complementaria basada en conocimiento general del modelo**"
SYSTEM = """Actúa como colega de soporte empresarial de impresión. Usa un formato compacto y proporcional. Si existen extractos autorizados, presenta primero ### Según la documentación y limita esa sección a afirmaciones respaldadas con citas [R#]; después usa ### Validaciones adicionales para orientación complementaria sin citas. Si no existen extractos autorizados, omite por completo la sección documental y usa solo ### Orientación sugerida, seguida opcionalmente por **Siguiente paso:**. No incluyas secciones vacías ni repitas la limitación documental en varios encabezados. Si documentation_limitation.required_message contiene texto, conserva fielmente su significado una sola vez. Responde al objetivo actual. Respeta hechos confirmados. La evidencia describe posibilidades, no elecciones del usuario. No conviertas modalidades sugeridas en hechos. El alcance confirmado gobierna el orden diagnóstico. Si la afectación es amplia, transversal o incluye modalidades distintas, prioriza primero el componente, servicio, configuración, registro o dependencia compartida; no comiences por herramientas locales, controladores o dispositivos individuales salvo que exista evidencia que los señale. Si la afectación es local o de un solo dispositivo, prioriza entonces comprobaciones específicas de ese endpoint. Cada acción debe indicar qué valida y cómo su resultado cambia el siguiente paso. No repitas una comprobación que aparezca en previous_attempts ni una acción semánticamente equivalente a assistant_delivered_guidance. Compara intención, acción, objeto y resultado, no solo texto literal. Si response_policy.exclude_previous_guidance es verdadero, entrega únicamente acciones nuevas; si no quedan, dilo brevemente sin volver a desarrollar las anteriores. Solo puedes repetir una acción cuando nueva evidencia lo justifique y debes explicar por qué. que nueva evidencia justifique repetirla y expliques por qué. No menciones procesos internos. Cuando el usuario pregunte por el historial del caso, la procedencia de acciones o la diferencia entre lo realizado y lo sugerido, usa user_confirmed_attempts y assistant_delivered_guidance como listas autoritativas separadas. Enumera ambas fielmente. Nunca afirmes que no hubo recomendaciones si assistant_delivered_guidance contiene elementos, y no añadas un nuevo paso salvo que el usuario lo solicite.  Cuando authorized_evidence incluya evidence_role documented_requirements_context, úsala en la sección documental únicamente para requisitos, dependencias, comunicación, cuentas, puertos, plataforma o restricciones expresamente descritas; no la conviertas en un procedimiento documentado ni afirmes que una dependencia es la causa. La orientación complementaria inicial debe limitarse a observación, consulta de estado, lectura de registros o verificación reversible. No prescribas reparación del sistema operativo, desinstalación, reinstalación, eliminación de datos o configuración, cambios de permisos, registro, certificados, red o seguridad, reinicios de alcance amplio ni actualización de versión a menos que la evidencia autorizada describa explícitamente esa acción y los intentos confirmados justifiquen haber agotado comprobaciones de menor impacto. Si no existe esa justificación, solicita o captura evidencia y ofrece como máximo una comprobación segura y discriminante. Distingue siempre requisito documentado, hipótesis y causa confirmada; nunca presentes una hipótesis como dependencia crítica o conclusión. Los campos manufacturer, product, model, operating_system y architecture del alcance son hechos aportados por el usuario. Consérvalos literalmente. La ausencia de documentación no constituye evidencia de que sean erróneos. No inventes un paquete exacto. Organiza el diagnóstico de menor a mayor impacto: primero observación y lectura de estado; después validaciones reversibles sin cambiar configuración; luego cambios acotados y reversibles; deja para el final cualquier acción privilegiada, disruptiva o de seguridad. No presentes una hipótesis como causa confirmada: vincúlala con la observación que permitiría confirmarla o descartarla. No recomiendes como primera línea deshabilitar protecciones, retirar controles, revertir actualizaciones, eliminar componentes o realizar cambios amplios. Si una acción de alto impacto fuera realmente necesaria, no la des como instrucción directa: explica el riesgo, exige evidencia previa, autorización, ventana controlada, plan de reversión y ofrece escalamiento como alternativa. Nunca sugieras debilitar controles corporativos para probar una hipótesis cuando exista una validación de menor riesgo. Para cualquier acción potencialmente disruptiva, aplica guidance_integrity_contract: condición, impacto, respaldo o recuperación, autorización o ventana cuando apliquen y alternativa de escalamiento. Máximo 180 palabras."""

MAX_AUTHORIZED_ITEMS = 4
MAX_AUTHORIZED_CHARS = 4300
MAX_ITEM_TEXT_CHARS = 900


def _norm(value):
    return "".join(
        c
        for c in unicodedata.normalize("NFKD", str(value or "").casefold())
        if not unicodedata.combining(c)
    )


def _terms(value):
    return set(re.findall(r"[a-z0-9]{3,}", _norm(value)))


def _stable(evidence):
    payload = [
        evidence.get("url") or evidence.get("source"),
        evidence.get("page"),
        " ".join(str(evidence.get("text") or "").split()),
    ]
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False).encode()
    ).hexdigest()[:16]


def authorized_evidence(
    retrieval,
    question="",
    goal="",
    max_items=MAX_AUTHORIZED_ITEMS,
    max_chars=MAX_AUTHORIZED_CHARS,
):
    current = list(retrieval.get("generation_evidence") or retrieval.get("evidence") or [])
    ctx = retrieval.get("_answer_context") or {}
    previous = list(ctx.get("active_document_evidence_ledger") or ctx.get("cited_evidence") or [])
    query_terms = _terms(f"{question} {goal}")
    candidates = []

    for origin, rows in (("current_turn", current), ("previous_answer", previous)):
        for position, evidence in enumerate(rows):
            stable_id = _stable(evidence)
            text = " ".join(str(evidence.get("text") or "").split())
            evidence_terms = _terms(f"{evidence.get('title', '')} {text}")
            overlap = len(query_terms & evidence_terms)
            density = overlap / max(1, len(query_terms))
            current_turn_tie_break = 0.02 if origin == "current_turn" else 0.0
            candidates.append(
                (
                    density + current_turn_tie_break,
                    overlap,
                    -position,
                    origin,
                    evidence,
                    stable_id,
                    text,
                )
            )

    candidates.sort(reverse=True, key=lambda item: (item[0], item[1], item[2]))
    selected = []
    seen = set()
    used_chars = 0

    for _, overlap, _, origin, evidence, stable_id, text in candidates:
        if stable_id in seen:
            continue
        if selected and overlap <= 0:
            continue

        row = {
            "id": f"R{len(selected) + 1}",
            "stable_id": stable_id,
            "title": evidence.get("title"),
            "page": evidence.get("page"),
            "text": text[:MAX_ITEM_TEXT_CHARS],
            "origin": origin,
        }
        row_chars = len(json.dumps(row, ensure_ascii=False))
        if selected and used_chars + row_chars > max_chars:
            continue

        selected.append(row)
        seen.add(stable_id)
        used_chars += row_chars
        if len(selected) >= max_items:
            break

    return selected


def repair_citation_placement(text):
    value = str(text or "")
    doc = re.search(r"Según la documentación", value, re.I)
    extra = re.search(r"Validaciones adicionales", value, re.I)
    if not (doc and extra and doc.start() < extra.start()):
        return value, False
    tail = re.sub(r"\s*\[(R\d+)\]", "", value[extra.start():])
    return value[:extra.start()] + tail, tail != value[extra.start():]


def validate_internal(text, finish_reason=None, valid_ids=None, require_documented=False):
    value = str(text or "").strip()
    known = set(valid_ids or [])
    complete = str(finish_reason or "").casefold() not in {"length", "max_tokens"}
    doc = re.search(r"Según la documentación", value, re.I)
    extra = re.search(r"Validaciones adicionales", value, re.I)
    guidance = re.search(r"Orientación sugerida", value, re.I)
    if known:
        supplemental = extra or guidance
        ordered = bool(doc and supplemental and doc.start() < supplemental.start())
        internal_only = bool(guidance and not doc and not extra)
        first = value[doc.start():supplemental.start()] if ordered else ""
        rest = value[supplemental.start():] if ordered else value
        sections = [name for name, match in (("Según la documentación", doc), ("Validaciones adicionales", extra), ("Orientación sugerida", guidance)) if match]
        # Applicable partial evidence is binding on a canonical hybrid route.
        provisional_documented = set(re.findall(r"\[(R\d+)\]", first))
        documented_required_and_present = bool(
            require_documented and ordered and provisional_documented
            and provisional_documented.issubset(known)
        )
        ordered = documented_required_and_present if require_documented else (ordered or internal_only)
    else:
        ordered = bool(guidance) and not doc and not extra
        first = ""
        rest = value
        sections = ["Orientación sugerida"] if guidance else []
    documented = set(re.findall(r"\[(R\d+)\]", first))
    internal = set(re.findall(r"\[(R\d+)\]", rest))
    safe = bool(value) and ordered and not internal and documented.issubset(known)
    return safe and complete, {
        "safe_partial": safe,
        "sections_present": sections,
        "separation_valid": ordered,
        "finish_complete": complete,
        "documented_citations": sorted(documented),
        "internal_citations": sorted(internal),
        "unknown_citations": sorted((documented | internal) - known),
        "compact_format": True,
    }


def fingerprint(message, understanding, retrieval, assessment, model=""):
    evidence = authorized_evidence(
        retrieval,
        message,
        understanding.get("current_goal") or "",
    )
    payload = {
        "q": " ".join(str(message).split()).casefold(),
        "goal": understanding.get("current_goal"), "confirmed_scope": ((retrieval.get("response_plan") or {}).get("request") or {}).get("scope") or ((retrieval.get("query") or {}).get("fields") or {}).get("details") or {},
        "assessment": assessment.get("status"),
        "evidence": [item.get("stable_id") for item in evidence],
        "model": model,
        "prompt": PROMPT_VERSION,
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()[:24]


class ControlledInternalKnowledgeComposer:
    def __init__(self, gateway, max_tokens=420):
        self.gateway = gateway
        self.max_tokens = max(320, min(520, int(max_tokens)))
        self.last_provider_result = {}
        self.validation = {}
        self.attempts = []
    def _call(self, payload, compact=False):
        from app.llm_gateway.models import LLMRequest
        system = SYSTEM + (" Responde de nuevo de forma completa en máximo 130 palabras. Conserva las tres secciones; evita repetir requisitos y no dejes una pregunta incompleta." if compact else "")
        return self.gateway.complete(LLMRequest(
            [{"role":"system","content":system},{"role":"user","content":json.dumps(payload,ensure_ascii=False,separators=(",",":"))}],
            "agent_core_v2_clean_internal_knowledge", self.max_tokens, 0.0, None))
    def compose(self, message, understanding, retrieval, assessment):
        evidence = authorized_evidence(retrieval, message, understanding.get("current_goal") or "")
        response_plan = ((retrieval.get("response_plan") or {}).get("response_plan") or {})
        require_documented = bool(response_plan.get("allow_documented_claims") and evidence)
        limitation=dict(retrieval.get("documentation_limitation") or {});limitation["required_message"]=limitation_user_message(limitation)
        payload = {"question":message,"goal":understanding.get("current_goal"),"case_context":retrieval.get("_case_context") or {},"evidence_authority":{"requirements_context":bool(retrieval.get("requirements_context_authorized")),"requirements_are_facts_not_procedure":True},"documentation_assessment":assessment,"documentation_limitation":limitation,"authorized_evidence":evidence}
        payload = enrich_internal_payload(payload, retrieval.get("_answer_context") or {}, understanding)
        payload["partial_documentary_authority"] = {
            "required": require_documented,
            "rule": "Publish the supported documentary part first with citations; complement only the uncovered remainder.",
        }
        integrity_contract=build_guidance_integrity_contract(retrieval)
        payload["previous_attempts"] = list((retrieval.get("_case_context") or {}).get("attempts") or [])[-6:]
        payload["guidance_integrity_contract"]=integrity_contract
        continuity_guard=(assessment or {}).get("documentation_continuity_guard") or {}
        if continuity_guard.get("active"):
            payload["documentation_continuity_guard"]=continuity_guard
            payload["scope_contract"]["documentation_absence_policy"]="Do not claim global absence. State what the authorized document confirms and localize only the unsupported remainder."
        payload["user_confirmed_attempts"]=integrity_contract["user_confirmed_attempts"]
        payload["assistant_delivered_guidance"]=integrity_contract["assistant_delivered_guidance"]
        result = self._call(payload)
        self.attempts = [result.to_dict()]
        length_retry = bool(result.ok and str(result.finish_reason or "").casefold() in {"length","max_tokens"})
        if length_retry:
            compact_payload = dict(payload)
            compact_payload["authorized_evidence"] = evidence[:2]
            compact_payload["completion_recovery"] = {"reason":"previous_output_truncated","must_finish":True}
            result = self._call(compact_payload, True)
            self.attempts.append(result.to_dict())
        valid_ids = [item["id"] for item in evidence]
        valid, diagnostic = validate_internal(result.text if result.ok else "", result.finish_reason, valid_ids, require_documented=require_documented)
        if result.ok and not valid and diagnostic.get("separation_valid") and diagnostic.get("finish_complete"):
            repaired, changed = repair_citation_placement(result.text)
            if changed:
                result.text = repaired
                valid, diagnostic = validate_internal(repaired, result.finish_reason, valid_ids, require_documented=require_documented)
                diagnostic["deterministic_citation_repair"] = True
        usage={k:sum(int((a.get("usage") or {}).get(k,0) or 0) for a in self.attempts) for k in ("prompt_tokens","completion_tokens","total_tokens")}
        self.validation = {**diagnostic,"partial_documentary_authority_required":require_documented,"retry_used":length_retry,"length_recovery_attempted":length_retry,"length_recovery_succeeded":bool(length_retry and valid),"attempt_count":len(self.attempts),"selected_attempt":len(self.attempts),"published_partial":False,"selected_evidence_ids":valid_ids,"authorized_stable_ids":[item["stable_id"] for item in evidence],"authorized_evidence_count":len(evidence),"authorized_evidence_chars":sum(len(item.get("text") or "") for item in evidence),"answer_context_used":bool(payload.get("previous_answer_context")),"compact_followup_context":bool(payload.get("previous_answer_context")),"guidance_integrity":integrity_diagnostic(integrity_contract)}
        self.last_provider_result = {**result.to_dict(),"selected_attempt":len(self.attempts),"attempts":self.attempts,"aggregate_usage":usage,"aggregate_latency_ms":sum(float(a.get("latency_ms") or 0) for a in self.attempts)}
        if not result.ok:
            return AgentResponse("La documentación no es suficiente y no fue posible generar orientación complementaria.","internal_knowledge_provider_degraded",False)
        if not valid:
            reason="La orientación generada quedó incompleta y no fue posible recuperarla de forma segura." if not diagnostic.get("finish_complete") else "La orientación generada no superó la validación documental y no será publicada."
            return AgentResponse(reason,"internal_knowledge_completion_guard" if not diagnostic.get("finish_complete") else "internal_knowledge_separation_guard",False,result.provider,result.model,usage,result.finish_reason)
        return AgentResponse(f"{WARNING}\n\n{str(result.text).strip()}","controlled_internal_knowledge",True,result.provider,result.model,usage,result.finish_reason)
