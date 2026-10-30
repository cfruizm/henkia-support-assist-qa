"""Canonical runtime configuration for productive retrieval resources.

4C.2 ownership rule:
- Productive vectorstore and retrieval modules consume CONFIG from this module.
- Provider secrets remain supplied by Streamlit secrets and gateway configuration.
- Reference-only backend settings must not become implicit V2 Clean dependencies.

The marker does not change configuration values.
"""

# app/config.py
# Centralized configuration for Arus PrintAssist

from pathlib import Path

# -----------------------------------------------------------------------------
# Project paths
# -----------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
PDF_DIR = DATA_DIR / "knowledge_base_pdfs"
VECTORSTORE_DIR = DATA_DIR / "vectorstore"
RUNTIME_DIR = DATA_DIR / "runtime"

# Ensure expected folders exist
PDF_DIR.mkdir(parents=True, exist_ok=True)
VECTORSTORE_DIR.mkdir(parents=True, exist_ok=True)
RUNTIME_DIR.mkdir(parents=True, exist_ok=True)

# -----------------------------------------------------------------------------
# Streamlit UI configuration
# -----------------------------------------------------------------------------
APP_TITLE = "Arus PrintAssist"
APP_SUBTITLE = (
    "Asistente de soporte de impresión, documentación técnica "
    "y escalamiento de incidentes."
)
PAGE_ICON = "🖨️"
PAGE_LAYOUT = "wide"
SIDEBAR_TITLE = "Control de sesión"

# -----------------------------------------------------------------------------
# Backend configuration
# -----------------------------------------------------------------------------
CONFIG = {
    "project_name": "Arus PrintAssist Prototype",
    "language": "es",
    "embedding_model_name": "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
    "vectorstore_dir": str(VECTORSTORE_DIR),
    "chunk_size": 800,
    "chunk_overlap": 150,

    # Backward-compatible default
    "retrieval_top_k": 4,

    # Candidate retrieval by intent.
    # These are intentionally higher than final top-k because we rerank after retrieval.
    "retrieval_top_k_by_intent": {
        "default": 12,
        "requirements": 18,
        "architecture": 16,
        "conceptual": 12,
        "procedural": 16,
        "troubleshooting": 22,
        "escalation": 12,
        "warranty": 18,
    },

    # Final context size sent to the LLM.
    "retrieval_final_top_k_by_intent": {
        "default": 4,
        "requirements": 6,
        "architecture": 6,
        "conceptual": 4,
        "procedural": 5,
        "troubleshooting": 6,
        "escalation": 4,
        "warranty": 5,
    },

    # Safer retrieval behavior for Streamlit Cloud prototype.
    "enable_filter_fallback": True,
    "max_docs_per_source": 3,

    "pdf_dir": str(PDF_DIR),
    "runtime_dir": str(RUNTIME_DIR),
}

LLM_CONFIG = {
    "model_name": "Qwen/Qwen2.5-7B-Instruct",
    "provider": None,
    "temperature": 0.2,
    "max_tokens": 900,
}
