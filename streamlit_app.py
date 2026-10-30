# streamlit_app.py
# Official Streamlit entrypoint for Henkia Support Assist.

from __future__ import annotations

import json
from typing import Any

import streamlit as st

from app.access_control import render_access_sidebar, require_access
from app.ui.brand import assistant_avatar, inject_brand_styles, render_app_header, render_sidebar_brand

APP_NAME = "Henkia Support Assist"
APP_SUBTITLE = "Asistente de soporte de impresión, documentación técnica y escalamiento de incidentes."
WELCOME_TEXT = "Hola, soy Henkia Support Assist. ¿En qué puedo ayudarte hoy?"


def _as_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().casefold() in {"1", "true", "yes", "on"}


def _secret(name: str, default: Any = None) -> Any:
    try:
        return st.secrets.get(name, default)
    except Exception:
        return default


DEBUG_UI_ENABLED = _as_bool(_secret("DEBUG_UI", False))

st.set_page_config(
    page_title=APP_NAME,
    page_icon="assets/brand/Isotipo_principal@2x.png",
    layout="wide",
    initial_sidebar_state="expanded",
)

# The corporate visual layer is loaded before access so the login is branded too.
inject_brand_styles()

# Access is resolved before importing Agent Core, retrieval, embeddings, or providers.
ACCESS_IDENTITY = require_access()

from app.agent_core_v2_clean.budget import BudgetPolicy
from app.agent_core_v2_clean.lab_session import (
    export_session,
    get_store,
    process_message,
    reset_store,
)
from app.agent_core_v2_clean.resource_monitor_ui import render_resource_monitor
from app.agent_core_v2_clean.source_access_policy import configure_source_access, render_latest_source_actions

store = get_store(st.session_state)
configure_source_access(st.secrets, pdf_root="data/knowledge_base_pdfs")
render_access_sidebar(ACCESS_IDENTITY)

with st.sidebar:
    render_sidebar_brand()
ADMIN_DEBUG_UI = DEBUG_UI_ENABLED and ACCESS_IDENTITY.is_admin
telemetry = store["telemetry"]
# Official UI uses the validated normal policy. No laboratory mode selector is exposed.
store["budget"] = BudgetPolicy.for_mode("normal").to_dict()

with st.sidebar:
    st.subheader("Control de sesión")
    if st.button("Nueva conversación", type="primary", use_container_width=True):
        reset_store(st.session_state)
        st.rerun()

    if ADMIN_DEBUG_UI:
        st.divider()
        with st.expander("Diagnóstico técnico", expanded=False):
            provider = str(_secret("LLM_PROVIDER", "no configurado"))
            st.caption(f"Proveedor activo: {provider}")
            st.metric("Llamadas", int(telemetry.get("calls", 0)))
            st.metric("Tokens", f"{int(telemetry.get('total_tokens', 0)):,}")
            st.metric(
                "Fallos",
                int(telemetry.get("functional_failed_calls", telemetry.get("failed_calls", 0))),
            )
            st.divider()
            st.markdown("**Monitor de recursos**")
            render_resource_monitor(st, store, telemetry)
            st.divider()
            st.markdown("**Estado técnico completo**")
            st.json(
                {
                    "memory": store["memory"].to_dict(),
                    "budget": store["budget"],
                    "telemetry": telemetry,
                    "errors": store["errors"],
                }
            )

        st.download_button(
            "Descargar diagnóstico JSON",
            data=json.dumps(export_session(st.session_state), ensure_ascii=False, indent=2),
            file_name="henkia_support_assist_session.json",
            mime="application/json",
            use_container_width=True,
        )
        st.markdown(
            '<div class="henkia-version">Núcleo estable: Agent Core V2 Clean 4A.3.9.10.3</div>',
            unsafe_allow_html=True,
        )

render_app_header(APP_NAME, APP_SUBTITLE)
st.markdown(
    '<div class="henkia-status"><span class="henkia-status-dot"></span>Asistente disponible</div>',
    unsafe_allow_html=True,
)
st.markdown(
    """
    <div class="henkia-responsible-use">
      <strong>Uso responsable</strong><br>
      No ingreses contraseñas, claves API ni datos personales sensibles. Verifica las fuentes antes de aplicar cambios
      y reporta respuestas incorrectas. El asistente apoya al soporte humano, no lo reemplaza.
    </div>
    """,
    unsafe_allow_html=True,
)
st.markdown(
    """
    <div class="henkia-intro">
      <strong>Henkia Support Assist</strong> ofrece soporte documental y orientación de primer nivel
      para servicios de impresión, procedimientos técnicos y preparación de escalamientos.
    </div>
    <div class="henkia-note">
      <strong>Alcance:</strong> las respuestas se fundamentan prioritariamente en la documentación disponible.
      Cuando una orientación sea complementaria, el asistente debe identificarla. Para cambios críticos,
      seguridad o incidentes de alto impacto, valida la información antes de ejecutarla.
    </div>
    """,
    unsafe_allow_html=True,
)

with st.expander("Guía de uso del asistente", expanded=False):
    st.markdown(
        """
        - Describe el producto, el síntoma y el alcance con el mayor contexto disponible.
        - Indica las validaciones ya realizadas y su resultado para evitar repeticiones.
        - Puedes pedir requisitos, procedimientos, diagnóstico, documentación o preparación de un escalamiento.
        - Si cambias de tema, indícalo de forma natural. El asistente conservará el caso anterior cuando corresponda.
        - Revisa las fuentes y las advertencias antes de aplicar cambios de alto impacto.
        """
    )

messages = store["messages"]
if not messages:
    with st.chat_message("assistant", avatar=assistant_avatar()):
        st.markdown(f'<div class="henkia-welcome">{WELCOME_TEXT}</div>', unsafe_allow_html=True)
else:
    for message in messages:
        avatar = assistant_avatar() if message.get("role") == "assistant" else None
        with st.chat_message(message.get("role", "assistant"), avatar=avatar):
            st.markdown(message.get("content") or "")

    render_latest_source_actions(st, store)

if prompt := st.chat_input("Escribe tu consulta"):
    with st.spinner("Procesando..."):
        process_message(prompt, st.secrets, st.session_state)
    st.rerun()
