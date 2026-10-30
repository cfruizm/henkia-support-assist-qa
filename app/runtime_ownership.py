"""Machine-readable ownership manifest for the productive Henkia runtime.

This module contains declarations only. It does not import runtime components and
does not change application behavior.
"""

RUNTIME_OWNERSHIP_VERSION = "4C.2.3"

PRODUCTIVE_ENTRYPOINTS = (
    "streamlit_app.py",
    "pages/Agent_Core_V2_Clean_Lab.py",
    "pages/Agent_Core_V2_Robustness_Gate.py",
)

PRODUCTIVE_BOUNDARIES = {
    "conversation": "app.agent_core_v2_clean",
    "retrieval": "app.retrieval_runtime",
    "vectorstore": "app.vectorstore_runtime",
    "domain_registry": "app.domain_registry",
    "runtime_config": "app.config",
    "llm_gateway": "app.llm_gateway",
}

REFERENCE_ONLY_MODULES = ("app.backend",)

FORBIDDEN_PRODUCTIVE_IMPORTS = (
    "app.backend",
    "app.agent_core",
    "app.agent_core_v2",
    "app.retrieval",
    "app.domain_registry_v1",
)
