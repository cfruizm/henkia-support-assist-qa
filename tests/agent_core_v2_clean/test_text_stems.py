"""Offline checks for stem-based term matching (no hand-written word lists)."""

from app.agent_core_v2_clean.operation_bridge import present_terms, translation_map
from app.agent_core_v2_clean.text_stems import collapse_by_stem, stem_index, term_matches
from app.agent_core_v2_clean.understanding import ConversationUnderstanding
from app.agent_core_v2_clean.unified_evidence_authority import apply_unified_evidence_verdict


def test_word_forms_of_one_root_match():
    assert term_matches("analiza", stem_index({"analizar"}))
    assert term_matches("instalarlo", stem_index({"installation"}))
    assert term_matches("configuracion", stem_index({"configure"}))
    assert not term_matches("teclado", stem_index({"tecnico", "telefono"}))


def test_forms_of_one_root_count_once():
    collapsed = collapse_by_stem({"cambiar", "cambio", "idioma", "teclado"})
    assert len(collapsed) == 3 and "teclado" in collapsed and "idioma" in collapsed


def test_llm_translations_cover_words_stemming_cannot():
    translations = translation_map({"term_translations": [
        {"term": "desaparecen", "english": "disappear"},
        {"term": "liberarlos", "english": "release"},
    ]})
    available = {"jobs", "disappearing", "released"}
    assert present_terms({"desaparecen", "liberarlos"}, available, translations) == {"desaparecen", "liberarlos"}


def test_contract_parses_and_cleans_term_translations():
    understanding = ConversationUnderstanding(gateway=None)
    u = understanding._parse(
        '{"intent":"troubleshooting","current_goal":"x","case_updates":[],'
        '"term_translations":[{"term":"desaparecen","english":"Disappear"},{"bad":1},{"term":"cola","english":"cola"}]}'
    )
    assert u.term_translations == [{"term": "desaparecen", "english": "disappear"}]
    assert ConversationUnderstanding(gateway=None)._parse(
        '{"intent":"conceptual","current_goal":"x","case_updates":[],"term_translations":null}'
    ).term_translations == []


def _item(title, text):
    return {"id": "R1", "title": title, "source": f"/docs/{title}.pdf", "page": "2", "text": text,
            "semantic_fit": {"score": 0.6}, "metadata": {"title": title}}


def test_generic_verb_alone_does_not_authorize_unrelated_article():
    doc = _item("Instalación del Administrador", "Para cambiar la configuración, cambie el puerto del servicio y reinicie.")
    retrieval = {"ok": True, "evidence": [doc], "generation_evidence": [doc], "diagnostic_evidence": [doc],
                 "query": {"fields": {"topic_relation": "new_topic", "user_act": "new_request"}}, "_answer_context": {}}
    understanding = {"user_act": "new_request", "intent": "procedural", "topic_relation": "new_topic",
                     "current_goal": "Cambiar el idioma del teclado en Platform Alpha",
                     "goal_updates": {"subject": "Platform Alpha"}, "canonical_subject": "Platform Alpha",
                     "subject_origin": "current_message", "reference_relation": "none"}
    verdict = apply_unified_evidence_verdict(retrieval, "¿Cómo cambio el idioma del teclado en Platform Alpha?", understanding)["evidence_verdict"]
    assert not verdict["accepted"], verdict


def test_semantic_fit_ignores_codes_and_extensions_and_matches_word_forms():
    from app.agent_core_v2_clean.semantic_fit import evaluate_item

    item = {"title": "IN0504-6_V1 INSTRUCTIVO USO DASHBOARD ALPHA - STREAMLIT.pdf",
            "text": "Use los filtros del dashboard para analizar la operación por cliente y exporte los datos."}
    fields = {"goal": "Explicar cómo analizar el dashboard de control de operación de Alpha", "intent": "procedural",
              "current_message": "¿Cómo se analiza el dashboard de control de operación de Alpha?"}
    fit = evaluate_item(item, "¿Cómo se analiza el dashboard de control de operación de Alpha?", fields)
    assert "analiza" in fit["matched_terms"] or "analizar" in fit["matched_terms"]
    assert not any(any(ch.isdigit() for ch in t) or t == "pdf" for t in fit["unconfirmed_title_terms"])
    assert fit["score"] >= 0.15, fit
