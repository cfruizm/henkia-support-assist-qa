from __future__ import annotations
from copy import deepcopy
import re


def _clean(value, limit=700):
    return " ".join(str(value or "").split()).strip()[:limit]


def _safe_evidence_sentence(retrieval):
    rows = (retrieval or {}).get("generation_evidence") or (retrieval or {}).get("evidence") or []
    for row in rows:
        text = _clean(row.get("text"), 900)
        source_id = _clean(row.get("id"), 30)
        sentences = [x.strip() for x in re.split(r"(?<=[.!?])\s+", text) if len(x.strip()) >= 35]
        for sentence in sentences:
            if source_id and len(sentence) <= 420:
                return sentence, source_id
    return None, None


def build_budget_fallback(message, memory, result=None, answer_context=None, budget_status=None):
    result = result or {}
    retrieval = result.get("retrieval") or {}
    context = answer_context or result.get("answer_context") or {}
    status = deepcopy(budget_status or {})
    sentence, source_id = _safe_evidence_sentence(retrieval)
    pending = getattr(getattr(memory, "pending_goal", None), "summary", None)
    subject = getattr(memory, "active_subject", None)
    case = getattr(memory, "support_case", None)
    observations = list(getattr(case, "observations", None) or [])[-3:]
    attempts = list(getattr(case, "attempts", None) or [])[-3:]
    lines = ["Alcancé el límite operativo de esta sesión y no haré otra llamada al modelo en este turno."]
    if subject or pending:
        lines.append("El contexto técnico queda conservado para continuar sin reiniciar el caso.")
    if observations:
        lines.append("**Hechos conservados:** " + "; ".join(_clean(x, 220) for x in observations if _clean(x, 220)))
    done = []
    for item in attempts:
        action = _clean((item or {}).get("action"), 180)
        observed = _clean((item or {}).get("result"), 180)
        if action:
            done.append(action + (f" → {observed}" if observed else ""))
    if done:
        lines.append("**Acciones ya registradas:** " + "; ".join(done))
    if sentence and source_id:
        lines.append("**Punto documental recuperado antes del bloqueo:**\n\n- " + sentence + f" [{source_id}]")
    elif context.get("main_text_excerpt"):
        lines.append("La respuesta anterior y sus fuentes permanecen en la memoria compacta de la sesión.")
    lines.append("Puedes iniciar una nueva sesión para recuperar presupuesto; el caso puede retomarse con el resumen y los hechos ya registrados.")
    return {
        "text": "\n\n".join(lines),
        "mode": "controlled_budget_fallback",
        "knowledge_used": bool(sentence),
        "documented_evidence_used": bool(sentence),
        "internal_knowledge_used": False,
        "knowledge_mode": "documented_only" if sentence else "none",
        "finish_reason": "deterministic_budget_guard",
        "degraded": True,
        "degraded_reason": status.get("reason") or "session_budget_unavailable",
        "budget_status": status,
        "fallback_evidence_ids": [source_id] if source_id else [],
        "case_preserved": True,
    }
