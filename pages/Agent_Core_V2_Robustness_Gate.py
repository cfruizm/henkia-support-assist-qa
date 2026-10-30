from __future__ import annotations
import json
import streamlit as st
from app.agent_core_v2_clean.evidence_sufficiency import assess_procedural_evidence
from app.agent_core_v2_clean.robustness_gate import run_gate, GATE_VERSION

st.set_page_config(page_title="Agent Core V2 Robustness Gate", page_icon="🧪", layout="wide")
st.title("Agent Core V2 Robustness Gate")
st.caption("Validación estructural determinista. No llama al LLM, no consume tokens y no modifica la conversación ni producción.")

if "agent_core_v2_robustness_report" not in st.session_state:
    st.session_state.agent_core_v2_robustness_report = None

if st.button("Ejecutar gate de robustez", type="primary", use_container_width=True):
    st.session_state.agent_core_v2_robustness_report = run_gate(assess_procedural_evidence)

report = st.session_state.agent_core_v2_robustness_report
if report is None:
    st.info("Pulsa el botón para ejecutar los seis escenarios controlados.")
else:
    if report["approved"]:
        st.success("Gate APROBADO")
    else:
        st.error("Gate NO APROBADO. Revisa los escenarios fallidos antes de continuar.")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Aprobados", report["passed"])
    c2.metric("Fallidos", report["failed"])
    c3.metric("Llamadas LLM", report["llm_calls"])
    c4.metric("Tokens", report["tokens"])
    st.caption(f"Versión: {GATE_VERSION} | Fixtures sintéticos controlados: Sí | Producción modificada: No")
    for item in report["results"]:
        icon = "✅" if item["passed"] else "❌"
        with st.expander(f"{icon} {item['case_id']} · {item['description']}", expanded=not item["passed"]):
            st.write(f"Categoría: `{item['category']}`")
            a, b = st.columns(2)
            with a:
                st.markdown("**Esperado**")
                st.json(item["expected"])
            with b:
                st.markdown("**Observado**")
                st.json(item["observed"])
            if item["mismatches"]:
                st.markdown("**Diferencias**")
                for mismatch in item["mismatches"]:
                    st.code(mismatch)
    payload = json.dumps(report, ensure_ascii=False, indent=2).encode("utf-8")
    st.download_button("Descargar reporte JSON", data=payload, file_name="agent_core_v2_clean_robustness_report.json", mime="application/json", use_container_width=True)
