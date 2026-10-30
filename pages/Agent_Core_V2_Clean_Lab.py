import json
import streamlit as st
from app.agent_core_v2_clean.lab_session import get_store,reset_store,process_message,export_session
from app.agent_core_v2_clean.budget import BudgetPolicy
from app.agent_core_v2_clean.deterministic_lab import process_deterministic
from app.agent_core_v2_clean.resource_monitor_ui import render_resource_monitor
st.set_page_config(page_title="Agent Core V2 Clean Lab",page_icon="🧠",layout="wide")
st.title("Agent Core V2 Clean Lab")
try:enabled=bool(st.secrets.get("AGENT_CORE_V2_CLEAN_LAB_ENABLED",False))
except Exception:enabled=False
if not enabled:st.info("Agrega AGENT_CORE_V2_CLEAN_LAB_ENABLED = true en Secrets.");st.stop()
store=get_store(st.session_state);t=store["telemetry"]
with st.sidebar:
 st.subheader("Modo de laboratorio")
 modes=["normal","economy","deterministic"];current=store.get("budget",{}).get("mode","normal");mode=st.radio("Modo",modes,index=modes.index(current) if current in modes else 0)
 preset=BudgetPolicy.for_mode(mode);store["budget"]=preset.to_dict()
 if mode=="deterministic":st.success("Flujo interactivo: 0 llamadas LLM y 0 tokens")
 else:
  used=int(t.get("total_tokens",0));errors=int(t.get("functional_failed_calls",t.get("failed_calls",0)));st.metric("Tokens usados",f"{used:,}");st.metric("Disponibles",f"{max(0,preset.max_session_tokens-used):,}");st.progress(min(1.0,used/max(1,preset.max_session_tokens)));st.caption(f"Llamadas {int(t.get('calls',0))}/{preset.max_session_calls} | Fallos {errors}")
 if st.button("Nueva conversación",use_container_width=True,type="primary"):reset_store(st.session_state);st.rerun()
 st.download_button("Descargar JSON",json.dumps(export_session(st.session_state),ensure_ascii=False,indent=2),"agent_core_v2_clean_lab_session.json","application/json",use_container_width=True)
if mode=="deterministic":
 st.subheader("Prueba interactiva sin LLM")
 st.caption("Escribe la pregunta y define el contrato semántico esperado. El sistema ejecuta memoria, política, retrieval, caché y telemetría reales sin invocar el modelo.")
 with st.expander("Contrato semántico de la prueba",expanded=True):
  c1,c2,c3,c4=st.columns(4)
  user_act=c1.selectbox("Acto",["new_request","follow_up","answer_to_question","reported_failure","attempt_result","topic_change","independent_question","cancel","escalation"])
  intent=c2.selectbox("Intención",["conceptual","procedural","troubleshooting","requirements","architecture","warranty","unknown"])
  topic_relation=c3.selectbox("Relación",["new_topic","same_topic","independent","return_to_previous"])
  domain=c4.selectbox("Dominio",["in_scope","out_of_scope","uncertain"])
  goal=st.text_input("Objetivo reconstruido esperado")
  should_retrieve=st.checkbox("Debe consultar documentación",value=True)
  needs_clarification=st.checkbox("Requiere aclaración",value=False)
  clarification=st.text_input("Dato faltante",disabled=not needs_clarification)
  details_text=st.text_area("Hechos atómicos JSON",value="{}",height=80)
  case_text=st.text_area("Actualizaciones del caso JSON",value="[]",height=80)
 for m in store["messages"]:
  with st.chat_message(m["role"]):st.markdown(m["content"])
 if prompt:=st.chat_input("Pregunta a evaluar sin LLM"):
  try:details=json.loads(details_text or "{}");case=json.loads(case_text or "[]")
  except Exception as exc:st.error(f"JSON del contrato inválido: {exc}");st.stop()
  semantic={"user_act":user_act,"intent":intent,"topic_relation":topic_relation,"domain_relevance":domain,"current_goal":goal,"goal_updates":details,"case_updates":case,"should_retrieve":should_retrieve,"needs_clarification":needs_clarification,"clarification_target":clarification or None}
  try:r=process_deterministic(prompt,semantic,store)
  except Exception as exc:st.error(f"Contrato inválido: {exc}");st.stop()
  st.session_state["v2_last_deterministic_result"]=r;st.rerun()
else:
 st.caption("Normal prioriza calidad. Economy reduce tokens. Retrieval de solo lectura está habilitado.")
 for m in store["messages"]:
  with st.chat_message(m["role"]):st.markdown(m["content"])
 if prompt:=st.chat_input("Escribe un mensaje"):
  with st.chat_message("user"):st.markdown(prompt)
  with st.chat_message("assistant"):
   with st.spinner("Procesando..."):r=process_message(prompt,st.secrets,st.session_state)
   st.markdown(r.get("answer",{}).get("text") or "Sin respuesta")
  st.rerun()
last=st.session_state.get("v2_last_deterministic_result")
if last:
 with st.expander("Último resultado sin LLM",expanded=True):st.json(last)
with st.expander("Diagnóstico técnico",expanded=False):
 render_resource_monitor(st,store,t)
 st.divider()
 st.markdown("**Estado técnico completo**")
 st.json({"memory":store["memory"].to_dict(),"budget":store["budget"],"telemetry":t,"errors":store["errors"]})
