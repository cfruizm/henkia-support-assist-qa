from __future__ import annotations

def evidence_has_current_support(retrieval: dict) -> bool:
    current = [x for x in (retrieval.get('diagnostic_evidence') or retrieval.get('evidence') or []) if not x.get('carried_from_previous_answer')]
    return bool(current)

def unsafe_global_absence_claim(answer_text: str, retrieval: dict) -> bool:
    text = (answer_text or '').lower()
    negatives = ('no contiene información', 'no contiene instrucciones', 'no existe documentación', 'documentación no cubre')
    return any(x in text for x in negatives) and evidence_has_current_support(retrieval)

def grounding_guard_instruction() -> str:
    return (
        'No afirmes que la documentación no contiene información cuando la recuperación actual '
        'incluya fuentes candidatas no transportadas. Si falta una dimensión necesaria, explica '
        'que existen alternativas documentadas y solicita únicamente el dato que permite elegirla.'
    )
