"""Legacy reference-only module retained for selective capability extraction.

4C.2 ownership rule:
- Henkia Support Assist and Agent Core V2 Clean must not import this module.
- Productive retrieval belongs to app.retrieval_runtime and app.vectorstore_runtime.
- Reusable capabilities must be extracted into focused modules and validated independently.

This marker does not change runtime behavior.
"""

from __future__ import annotations

import json
import time
import re
import unicodedata
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

import streamlit as st
from huggingface_hub import InferenceClient
try:
    from huggingface_hub.errors import BadRequestError, HfHubHTTPError
except Exception:
    BadRequestError = Exception
    HfHubHTTPError = Exception
from langchain_chroma import Chroma
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_core.documents import Document

from app.config import CONFIG, LLM_CONFIG, RUNTIME_DIR
from app.session_state import ChatSessionState, RollingConversationMemory

from app.domain_registry import (
    PRODUCT_ENTITY_REGISTRY,
    PROCESS_ENTITY_REGISTRY,
    PRODUCT_ALIAS_INDEX,
    PROCESS_ALIAS_INDEX,
    detect_entities_in_text,
)


# -----------------------------------------------------------------------------
# Incident state
# -----------------------------------------------------------------------------
class IncidentState:
    def __init__(self):
        self.software_involved = None
        self.software_version = None
        self.actions_attempted = []
        self.error_description = None
        self.printer_data = None
        self.contract_client_location = None
        self.evidence = None
        self.impact_type = None
        self.escalation_requested = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "software_involved": self.software_involved,
            "software_version": self.software_version,
            "actions_attempted": self.actions_attempted,
            "error_description": self.error_description,
            "printer_data": self.printer_data,
            "contract_client_location": self.contract_client_location,
            "evidence": self.evidence,
            "impact_type": self.impact_type,
            "escalation_requested": self.escalation_requested,
        }


# -----------------------------------------------------------------------------
# Streamlit resources
# -----------------------------------------------------------------------------
from app.vectorstore_runtime import get_embedding_model, get_vectorstore_signature, get_vectorstore_cached, get_vectorstore


@st.cache_resource
def get_hf_client():
    hf_token = st.secrets.get("HF_TOKEN", None)
    if not hf_token:
        return None

    model_name = get_effective_llm_model()
    provider = get_effective_hf_provider()

    if provider:
        return InferenceClient(
            model=model_name,
            provider=provider,
            token=hf_token,
        )

    return InferenceClient(
        model=model_name,
        token=hf_token,
    )

def backend_is_ready() -> bool:
    try:
        _ = get_embedding_model()
        _ = get_vectorstore()
        return True
    except Exception:
        return False

def get_effective_llm_model() -> str:
    return st.secrets.get("HF_MODEL", LLM_CONFIG.get("model_name"))


def get_effective_hf_provider():
    return st.secrets.get("HF_PROVIDER", LLM_CONFIG.get("provider", None))

# -----------------------------------------------------------------------------
# Session helpers
# -----------------------------------------------------------------------------
def create_chat_session_state() -> ChatSessionState:
    state = ChatSessionState()
    state.incident_state = IncidentState()
    return state


def reset_chat_session_state() -> ChatSessionState:
    return create_chat_session_state()


def ensure_session_state_integrity(session_state: ChatSessionState):
    if getattr(session_state, "mode", None) is None:
        session_state.mode = "normal"
    if getattr(session_state, "memory", None) is None:
        session_state.memory = RollingConversationMemory(max_turns=4)
    if getattr(session_state, "logs", None) is None:
        session_state.logs = []
    if getattr(session_state, "incident_state", None) is None:
        session_state.incident_state = IncidentState()
    if getattr(session_state, "pending_incident_field", None) is None:
        session_state.pending_incident_field = None
    if getattr(session_state, "escalation_workflow_state", None) is None:
        session_state.escalation_workflow_state = "normal"
    if getattr(session_state, "escalation_summary_ready", None) is None:
        session_state.escalation_summary_ready = False
    if getattr(session_state, "escalation_persisted", None) is None:
        session_state.escalation_persisted = False
    if not hasattr(session_state, "last_escalation_summary"):
        session_state.last_escalation_summary = None
    if not hasattr(session_state, "last_escalation_exported_file"):
        session_state.last_escalation_exported_file = None
    return session_state


# -----------------------------------------------------------------------------
# Scope control
# -----------------------------------------------------------------------------
PRINT_SCOPE_KEYWORDS = [
    "impresora", "impresoras", "printer", "printers", "multifuncional", "copiadora", "mfp",
    "papercut", "sds", "hp", "epson", "web jetadmin", "wja", "jetadmin", "oxp", "gav",
    "print evolve", "mfpsecure", "impresión", "impresion", "imprimir", "imprime", "imprimen",
    "imprimiendo", "la impre", "trabajo de impresión", "trabajo de impresion", "trabajos de impresión",
    "trabajos de impresion", "los trabajos", "el trabajo", "cola de impresión", "cola de impresion",
    "cola", "colas", "queue", "spooler", "driver", "firmware", "servidor de impresión",
    "servidor de impresion", "escaner", "escáner", "scanner", "escanear", "toner", "tóner",
    "consumible", "consumibles", "suministro", "facturación", "facturacion", "prefactura",
    "pre-factura", "distribución", "distribucion", "costos", "template", "tracking", "garantía",
    "garantia", "pin", "cuotas", "reportes",
]

SUPPORT_FLOW_KEYWORDS = [
    "quiero escalar", "necesito escalar", "deseo escalar", "escalar el caso",
    "abrir un caso", "abrir caso", "crear incidente", "generar incidente",
    "pasar a nivel 2", "enviar a nivel 2", "escalar a nivel 2", "escalar a nivel 3",
]


OUT_OF_SCOPE_RESPONSE = (
    "Solo puedo ayudar con temas relacionados con el servicio de impresión, "
    "como diagnóstico, documentación, uso de herramientas y escalamiento de incidentes."
)


def is_in_scope_message(user_message: str) -> bool:
    text = user_message.lower()

    detected_products = detect_entities_in_text(text, PRODUCT_ALIAS_INDEX)
    detected_processes = detect_entities_in_text(text, PROCESS_ALIAS_INDEX)

    if detected_products or detected_processes:
        return True

    # Fallback to generic scope keywords
    domain_match = any(k in text for k in PRINT_SCOPE_KEYWORDS)
    support_match = any(k in text for k in SUPPORT_FLOW_KEYWORDS)

    return domain_match or support_match

# -----------------------------------------------------------------------------
# Deterministic help and intake routes
# -----------------------------------------------------------------------------
CAPABILITIES_HELP_RESPONSE = """Puedo ayudarte con soporte de primer nivel para servicios y herramientas de impresión:

- Diagnosticar problemas como trabajos retenidos o desaparecidos, colas bloqueadas, errores de impresión, escaneo y conectividad.
- Consultar documentación sobre PaperCut MF, HP SDS, HP Web Jetadmin, HP Access Control, GAV Tracking, Print Evolve, MFPsecure y otras herramientas disponibles.
- Explicar conceptos, requisitos, configuraciones y procedimientos documentados.
- Orientar sobre consumibles, activos, garantías y procesos del servicio cuando exista documentación disponible.
- Preparar un resumen técnico para escalar un incidente cuando el caso no pueda resolverse en primer nivel.

Para comenzar, indícame el producto o herramienta, el síntoma que observas y las validaciones que ya realizaste."""

SUPPORT_INTAKE_RESPONSE = """Claro. Cuéntame qué problema de impresión estás observando. Si puedes, incluye:

- Producto o herramienta involucrada.
- Síntoma o mensaje de error.
- Impresora, dispositivo o cola afectada.
- Acciones o validaciones que ya realizaste.

Con esa información podré orientarte mejor o ayudarte a preparar un escalamiento si es necesario."""

CAPABILITIES_PATTERNS = [
    # Capacidades generales
    "qué puedes hacer",
    "que puedes hacer",
    "qué más puedes hacer",
    "que mas puedes hacer",
    "qué otras cosas puedes hacer",
    "que otras cosas puedes hacer",
    "qué funciones tienes",
    "que funciones tienes",

    # Formas de pedir ayuda
    "cómo me puedes ayudar",
    "como me puedes ayudar",
    "de qué forma me puedes ayudar",
    "de que forma me puedes ayudar",
    "en qué me puedes ayudar",
    "en que me puedes ayudar",

    # Alcance del asistente
    "qué sabes hacer",
    "que sabes hacer",
    "qué temas manejas",
    "que temas manejas",
    "qué temas puedes atender",
    "que temas puedes atender",
    "qué soportas",
    "que soportas",
    "cuál es tu alcance",
    "cual es tu alcance",

    # Orientación y opciones
    "necesito orientación",
    "necesito orientacion",
    "muéstrame las opciones",
    "muestrame las opciones",
    "qué opciones tienes",
    "que opciones tienes",
]

CAPABILITIES_EXACT = {"ayuda", "menu", "menú", "opciones", "help"}
SUPPORT_INTAKE_PATTERNS = [
    "tengo problemas", "tengo un problema", "necesito ayuda con una impresora", "necesito soporte",
    "necesito ayuda con impresión", "necesito ayuda con impresion", "algo no funciona",
    "la impresora tiene problemas",
]
ESCALATION_CANCEL_COMMANDS = {
    "cancelar", "cancela", "salir", "abortar", "detener escalamiento",
    "cancelar escalamiento", "olvidar el caso",
}
ESCALATION_FINISH_COMMANDS = {"finalizar", "terminar", "cerrar caso", "finalizar caso", "terminar caso"}
ACKNOWLEDGEMENT_MESSAGES = {"ok", "okay", "gracias", "listo", "entendido", "perfecto", "de acuerdo"}


def normalize_route_text(user_message: str) -> str:
    text = str(user_message or "").lower().strip()
    text = re.sub(r"[^a-záéíóúüñ0-9\s¿?]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    for greeting in ("hola ", "buenas ", "buenos días ", "buenos dias ", "buenas tardes ", "buenas noches "):
        if text.startswith(greeting):
            text = text[len(greeting):].strip()
            break
    return text.strip("¿? ")


def is_capabilities_help_message(user_message: str) -> bool:
    text = normalize_route_text(user_message)
    if has_explicit_product_entity(text) or has_explicit_process_reference(text):
        return False
    return text in CAPABILITIES_EXACT or any(pattern in text for pattern in CAPABILITIES_PATTERNS)


def is_support_intake_message(user_message: str) -> bool:
    text = normalize_route_text(user_message)
    return any(pattern in text for pattern in SUPPORT_INTAKE_PATTERNS)


def is_escalation_cancel_command(user_message: str) -> bool:
    return normalize_route_text(user_message) in ESCALATION_CANCEL_COMMANDS


def is_escalation_finish_command(user_message: str) -> bool:
    return normalize_route_text(user_message) in ESCALATION_FINISH_COMMANDS


def is_acknowledgement_message(user_message: str) -> bool:
    return normalize_route_text(user_message) in ACKNOWLEDGEMENT_MESSAGES


GENERIC_PRINT_ENTITY_TERMS = {
    "impresora", "impresoras", "printer", "printers", "impresión", "impresion", "imprimir",
    "multifuncional", "copiadora", "mfp", "monitor", "cola", "queue", "spooler", "driver",
    "firmware", "escaner", "escáner", "scanner", "toner", "tóner",
}

AMBIGUOUS_PRINT_SYMPTOM_REGEXES = [
    r"\bno\s+(?:puedo|puede|podemos|logro|logra|deja|permite)\s+(?:imprimir|escanear|liberar|ver|encontrar)",
    r"\bno\s+(?:imprime|imprimen|funciona|funcionan|responde|responden|aparece|aparecen|sale|salen|carga|cargan|detecta|detectan|registra|registran)\b",
    r"\b(?:bloquead|atascad|detenid|retenid|pendient|desaparec|perdid|offline|desconectad|lento|lenta|error|falla|fallo)\w*\b",
    r"\b(?:trabajo|trabajos|documento|documentos)\b.*\b(?:no|sin|desaparec|pendient|retenid|atascad)\w*\b",
]

PRINT_CONTEXT_REGEX = re.compile(
    r"\b(?:impres\w*|imprim\w*|printer\w*|trabajo\w*|cola\w*|queue\w*|spooler|"
    r"multifuncional\w*|copiadora\w*|monitor\w*|scanner\w*|escaner\w*|escáner\w*|"
    r"papel|toner|tóner|driver\w*|firmware)\b",
    re.IGNORECASE,
)

QUESTION_FUNCTION_WORDS = {
    "que", "cual", "cuales", "como", "cuando", "donde", "porque", "para", "hacer", "hago",
    "instalar", "instalo", "instala", "instalacion", "configurar", "configuro", "configura",
    "usar", "uso", "funciona", "funciones", "tiene", "tienen", "necesita", "necesitan",
    "requisitos", "sirve", "explica", "explicar", "quiero", "puedo", "puede", "de", "del",
    "la", "el", "los", "las", "un", "una", "con", "en", "por", "y", "o", "se", "su",
}

IDENTITY_STOPWORDS = QUESTION_FUNCTION_WORDS | {
    "arus", "informacion", "documentacion", "documento", "disponible", "actual", "sistema",
    "herramienta", "producto", "software", "procedimiento", "proceso",
}

SUBJECT_HINT_WORDS = {
    "administrador", "admin", "monitor", "cliente", "servidor", "agente", "control", "tracking",
    "facturacion", "template", "garantia", "cuotas", "reportes", "impresora", "dispositivo",
    "cola", "dashboard", "suministros", "firmware", "escalamiento", "prefactura",
}


def normalize_semantic_text(value: str) -> str:
    value = unicodedata.normalize("NFKD", str(value or "").lower())
    value = "".join(char for char in value if not unicodedata.combining(char))
    value = re.sub(r"[^a-z0-9\s]", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def light_stem(token: str) -> str:
    """Small language-agnostic-enough stemmer for identity matching, not semantics."""
    token = normalize_semantic_text(token)
    for suffix in (
        "aciones", "iciones", "amiento", "imientos", "imiento", "adores", "adoras",
        "acion", "icion", "mente", "idades", "idad", "ciones", "cion", "ando", "iendo",
        "ados", "adas", "ido", "ida", "ados", "adas", "es", "os", "as", "s",
    ):
        if token.endswith(suffix) and len(token) - len(suffix) >= 4:
            return token[:-len(suffix)]
    return token


def semantic_identity_tokens(value: str) -> set[str]:
    tokens = set()
    for token in normalize_semantic_text(value).split():
        if len(token) < 4 or token in IDENTITY_STOPWORDS:
            continue
        tokens.add(light_stem(token))
    return {token for token in tokens if len(token) >= 3}


def get_explicit_product_reference(user_message: str) -> tuple[str, dict] | None:
    text = normalize_route_text(user_message)
    for product_id, registry_item in get_detected_product_entities_with_registry(text):
        canonical = str(registry_item.get("canonical_name", "")).strip()
        aliases = [str(value).strip() for value in registry_item.get("aliases", []) or []]
        for candidate in [canonical] + aliases:
            normalized = normalize_route_text(candidate)
            if not normalized or normalized in GENERIC_PRINT_ENTITY_TERMS:
                continue
            if entity_alias_is_explicitly_mentioned(text, normalized):
                return product_id, registry_item
    return None


def has_explicit_product_entity(user_message: str) -> bool:
    return get_explicit_product_reference(user_message) is not None


def has_explicit_process_reference(user_message: str) -> bool:
    return bool(detect_entities_in_text(normalize_route_text(user_message), PROCESS_ALIAS_INDEX))


def has_independent_question_subject(user_message: str) -> bool:
    text = normalize_route_text(user_message)
    if has_explicit_product_entity(text) or has_explicit_process_reference(text):
        return True
    informative = semantic_identity_tokens(text)
    # Two content-bearing terms make the request self-contained. Examples:
    # "distribucion facturacion", "cuotas impresion", "firmware impresora".
    return len(informative) >= 2


def extract_conversation_subject_terms(user_message: str, product_name: str | None = None) -> list[str]:
    normalized = normalize_semantic_text(user_message)
    product_tokens = semantic_identity_tokens(product_name or "")
    terms = []
    for token in normalized.split():
        stemmed = light_stem(token)
        if stemmed in product_tokens or token in QUESTION_FUNCTION_WORDS or len(token) < 4:
            continue
        if token in SUBJECT_HINT_WORDS and token not in terms:
            terms.append(token)
    return terms[:3]


def document_identity_alignment(query: str, metadata: dict, content: str = "") -> dict:
    """Universal lexical identity alignment for products and business processes."""
    metadata = metadata or {}
    identity = " ".join([
        str(metadata.get("title", "")), str(metadata.get("source", "")),
        str(metadata.get("source_url", "")), str(metadata.get("canonical_url", "")),
    ])
    query_tokens = semantic_identity_tokens(query)
    identity_tokens = semantic_identity_tokens(identity)
    overlap = query_tokens & identity_tokens
    denominator = max(1, min(len(query_tokens), 5))
    ratio = len(overlap) / denominator
    return {
        "query_tokens": query_tokens,
        "identity_tokens": identity_tokens,
        "overlap_tokens": overlap,
        "overlap_count": len(overlap),
        "ratio": ratio,
    }


def compute_document_identity_anchor_score(query: str, metadata: dict, content: str = "") -> float:
    alignment = document_identity_alignment(query, metadata, content)
    count = alignment["overlap_count"]
    ratio = alignment["ratio"]
    if count >= 3 and ratio >= 0.6:
        return 18.0
    if count >= 2 and ratio >= 0.4:
        return 10.0
    if count >= 1:
        return 2.0
    return 0.0


def has_document_identity_anchor(user_query: str, docs: list, min_overlap: int = 2, min_ratio: float = 0.4) -> bool:
    for doc in docs or []:
        alignment = document_identity_alignment(user_query, doc.metadata or {}, doc.page_content or "")
        if alignment["overlap_count"] >= min_overlap and alignment["ratio"] >= min_ratio:
            return True
    return False


def is_ambiguous_print_issue(user_message: str) -> bool:
    text = normalize_route_text(user_message)
    if has_explicit_product_entity(text):
        return False
    return bool(PRINT_CONTEXT_REGEX.search(text)) and any(
        re.search(pattern, text, flags=re.IGNORECASE) for pattern in AMBIGUOUS_PRINT_SYMPTOM_REGEXES
    )


def build_ambiguous_print_issue_response(user_message: str) -> str:
    text = normalize_route_text(user_message)
    if re.search(r"\b(?:cola|queue|spooler)\w*\b", text):
        return (
            "Para orientar el problema de la cola necesito identificar el entorno. "
            "Indícame si corresponde a Windows, PaperCut, GAV Tracking u otra herramienta.\n\n"
            "Comparte también el estado visible del trabajo, por ejemplo Imprimiendo, En pausa o Error, "
            "y si la afectación ocurre en una sola cola o en varias."
        )
    if re.search(r"\bmonitor\w*\b", text):
        return (
            "La palabra monitor puede referirse a componentes diferentes. "
            "Indícame si se trata de HP SDS Monitor, un monitor físico u otra herramienta de impresión.\n\n"
            "Comparte el mensaje de error y el equipo, servidor o dispositivo afectado, si los conoces."
        )
    if re.search(r"\b(?:trabajo|trabajos|documento|documentos)\w*\b", text):
        return (
            "Para revisar el problema con los trabajos necesito saber en qué producto o cola ocurre.\n\n"
            "Indica la impresora o cola, la hora aproximada del envío, el estado visible del trabajo "
            "y si afecta a uno o varios usuarios."
        )
    return (
        "Para orientarte correctamente necesito identificar el entorno donde ocurre el problema de impresión. "
        "Indícame el producto o herramienta involucrada y la impresora, dispositivo o cola afectada.\n\n"
        "Comparte también el mensaje de error, el momento aproximado de la falla y si afecta a uno o varios usuarios."
    )


# -----------------------------------------------------------------------------
# Query Entities helpers
# -----------------------------------------------------------------------------
    
    
def get_detected_entity_aliases(user_query: str) -> list[str]:
    """
    Return all matched aliases present in the query text,
    from both product and process registries.
    """
    text = user_query.lower()
    aliases = []

    for alias in PRODUCT_ALIAS_INDEX.keys():
        if alias in text and alias not in aliases:
            aliases.append(alias)

    for alias in PROCESS_ALIAS_INDEX.keys():
        if alias in text and alias not in aliases:
            aliases.append(alias)

    return aliases


def score_title_and_source_matches(user_query: str, metadata: dict) -> float:
    """
    Boost documents whose title/source strongly match detected entity aliases
    or important query fragments.
    """
    score = 0.0
    title = str(metadata.get("title", "")).lower()
    source = str(metadata.get("source", "")).lower()

    detected_aliases = get_detected_entity_aliases(user_query)

    for alias in detected_aliases:
        if alias in title:
            score += 4.0
        if alias in source:
            score += 3.0

    # Additional phrase-level boost for exact query fragments
    query_text = user_query.lower().strip()

    if len(query_text) >= 8:
        if query_text in title:
            score += 5.0
        if query_text in source:
            score += 4.0

    return score

# -----------------------------------------------------------------------------
# Retrieval helpers
# -----------------------------------------------------------------------------
def get_entity_aliases_for_query(user_query: str) -> list[str]:
    """
    Return unique aliases detected in the query from both registries.
    """
    text = user_query.lower()
    aliases = []

    for alias in PRODUCT_ALIAS_INDEX.keys():
        if alias in text and alias not in aliases:
            aliases.append(alias)

    for alias in PROCESS_ALIAS_INDEX.keys():
        if alias in text and alias not in aliases:
            aliases.append(alias)

    return aliases


def has_strong_entity_document_match(user_query: str, docs: list) -> bool:
    """
    Detect when retrieved docs are clearly aligned with the user's query,
    even if generic support heuristics classify support as weak.

    This is especially useful for internal operational procedures where
    metadata may be sparse, but title/source alignment is very strong.
    """
    if not docs:
        return False

    aliases = get_entity_aliases_for_query(user_query)
    if not aliases:
        return False

    strong_hits = 0

    for doc in docs[:4]:
        md = doc.metadata
        title = str(md.get("title", "")).lower()
        source = str(md.get("source", "")).lower()
        vendor = str(md.get("vendor", "")).lower()
        source_type = str(md.get("source_type", "")).lower()

        alias_match = any(alias in title or alias in source for alias in aliases)

        internal_match = (
            vendor == "arus_internal"
            or "da arus" in source
            or "/da arus/" in source
            or "da0" in source
            or "da0" in title
            or "in0" in source
            or "in0" in title
        )

        if alias_match:
            strong_hits += 2

        if alias_match and internal_match:
            strong_hits += 2

        if alias_match and source_type in {"pdf", "manual", "kb_article"}:
            strong_hits += 1

    return strong_hits >= 3

def get_best_source_value(metadata: dict) -> str:
    """
    Return the best available source value for both PDF and web documents.
    Web crawled docs can have source_url or canonical_url instead of source.
    """
    metadata = metadata or {}
    return str(
        metadata.get("source")
        or metadata.get("source_url")
        or metadata.get("canonical_url")
        or "unknown_source"
    )


def clean_source_label_text(value: str) -> str:
    """
    Clean source text for display.
    This avoids showing broken HTML/JSON fragments in Fuente(s).
    """
    text = str(value or "").strip()
    text = text.replace("&quot;", '"')
    text = re.sub(r"\s+", " ", text)

    # If a malformed HTML anchor reaches metadata, keep only the href URL.
    href_match = re.search(r'href="([^"]+)"', text)
    if href_match:
        text = href_match.group(1)

    return text.strip()


def format_source_label(metadata: dict) -> str:
    """
    Build a readable source label for PDF and web sources.

    For PDFs:
    - show file name and page when available.

    For web:
    - show full URL because Path(url).name loses important context.
    """
    metadata = metadata or {}

    title = str(metadata.get("title", "") or "").strip()
    source = clean_source_label_text(get_best_source_value(metadata))
    page = metadata.get("page_label", metadata.get("page", None))

    is_web = source.startswith("http://") or source.startswith("https://")
    source_name = source if is_web else (Path(source).name if "/" in source else source)

    if page is None:
        return f"{title} | {source_name}" if title else source_name

    return (
        f"{title} | {source_name} | page {page}"
        if title
        else f"{source_name} | page {page}"
    )

def compact_page_list(pages: list[int]) -> str:
    """
    Format page labels without implying a continuous range when pages are sparse.
    Examples:
    - [1] -> "page 1"
    - [1, 2, 3] -> "pages 1–3"
    - [1, 36, 246, 298] -> "pages 1, 36, 246, 298"
    """
    pages = sorted(set(pages))

    if not pages:
        return ""

    if len(pages) == 1:
        return f"page {pages[0]}"

    is_contiguous = all(
        pages[i] + 1 == pages[i + 1]
        for i in range(len(pages) - 1)
    )

    if is_contiguous:
        return f"pages {pages[0]}–{pages[-1]}"

    return "pages " + ", ".join(str(page) for page in pages)

def build_real_source_labels(docs: list) -> list:
    """
    Build real source labels for final citation.

    Important fix:
    Web documents usually do not have page/page_label.
    The previous version only created a source group when page was present,
    so web sources were silently dropped and real_source_labels became empty.
    """
    grouped: dict[tuple[str, str], dict[str, list]] = defaultdict(
        lambda: {"numeric_pages": [], "other_pages": []}
    )

    for doc in docs:
        md = doc.metadata or {}

        title = str(md.get("title", "") or "").strip()
        source = clean_source_label_text(get_best_source_value(md))

        is_web = source.startswith("http://") or source.startswith("https://")
        source_name = source if is_web else (Path(source).name if "/" in source else source)

        page = md.get("page_label", md.get("page", None))
        key = (title, source_name)

        # Critical line:
        # Create the group even when there is no page.
        # This allows web sources to appear in Fuente(s).
        _ = grouped[key]

        if page is not None:
            try:
                grouped[key]["numeric_pages"].append(int(str(page)))
            except Exception:
                grouped[key]["other_pages"].append(str(page))

    labels = []

    for (title, source_name), page_data in grouped.items():
        numeric_pages = page_data["numeric_pages"]
        other_pages = sorted(set(page_data["other_pages"]))

        page_parts = []

        if numeric_pages:
            page_parts.append(compact_page_list(numeric_pages))

        if other_pages:
            page_parts.append("pages " + ", ".join(other_pages))

        if page_parts:
            page_text = "; ".join(page_parts)
            labels.append(
                f"{title} | {source_name} | {page_text}"
                if title
                else f"{source_name} | {page_text}"
            )
        else:
            labels.append(
                f"{title} | {source_name}"
                if title
                else source_name
            )

    return labels

def build_source_block(real_source_labels: list[str]) -> str:
    if not real_source_labels:
        return "- Base de conocimiento actual sin coincidencias documentales suficientes"
    return "\n".join(f"- {label}" for label in real_source_labels[:3])


def make_chroma_filter(**kwargs):
    clauses = [{k: v} for k, v in kwargs.items() if v is not None]
    if not clauses:
        return None
    if len(clauses) == 1:
        return clauses[0]
    return {"$and": clauses}

def detect_query_entities(user_query: str) -> dict:
    """
    Detect product and process entities present in the query text.
    """
    text = user_query.lower()

    product_ids = detect_entities_in_text(text, PRODUCT_ALIAS_INDEX)
    process_ids = detect_entities_in_text(text, PROCESS_ALIAS_INDEX)

    return {
        "products": product_ids,
        "processes": process_ids,
    }



# -----------------------------------------------------------------------------
# Generic entity-aware retrieval helpers
# -----------------------------------------------------------------------------
@st.cache_resource
def get_vectorstore_metadata_value_counts() -> dict[str, dict[str, int]]:
    """
    Count stable metadata values already present in Chroma.
    This lets the retriever apply safe metadata filters only when the requested
    entity has a real matching product/vendor/component in the vectorstore.
    """
    counts: dict[str, dict[str, int]] = {
        "vendor": defaultdict(int),
        "product": defaultdict(int),
        "component": defaultdict(int),
        "collection_name": defaultdict(int),
        "folder_origin": defaultdict(int),
    }

    try:
        collection = get_vectorstore()._collection
        data = collection.get(include=["metadatas"], limit=20000)
        for metadata in data.get("metadatas", []) or []:
            metadata = metadata or {}
            for field in counts:
                value = metadata.get(field)
                if value is not None and str(value).strip():
                    counts[field][str(value).lower()] += 1
    except Exception:
        pass

    return {field: dict(values) for field, values in counts.items()}



def entity_alias_is_explicitly_mentioned(text: str, alias: str) -> bool:
    """
    Check alias presence without allowing short aliases to match inside words.
    Example: alias "hac" must not match "hacer".
    """
    alias = " ".join(str(alias).lower().strip().split())
    if not alias:
        return False

    escaped = re.escape(alias)

    # Multi-word aliases should be matched as a phrase with word boundaries.
    if " " in alias:
        return re.search(rf"(?<!\w){escaped}(?!\w)", text) is not None

    # Short aliases/acronyms must be exact tokens.
    return re.search(rf"\b{escaped}\b", text) is not None


def registry_entity_is_explicitly_mentioned(user_query: str, registry_item: dict) -> bool:
    text = user_query.lower()
    aliases = [str(a).lower() for a in registry_item.get("aliases", []) or []]
    canonical = str(registry_item.get("canonical_name", "")).lower()

    candidates = []
    if canonical:
        candidates.append(canonical)
    candidates.extend(aliases)

    return any(entity_alias_is_explicitly_mentioned(text, candidate) for candidate in candidates)


def get_detected_product_entities_with_registry(user_query: str) -> list[tuple[str, dict]]:
    """
    Return detected product entities, validating aliases with token/phrase boundaries.
    This prevents short aliases such as HAC from matching inside words like "hacer".
    """
    query_entities = detect_query_entities(user_query)
    product_ids = query_entities.get("products", []) or []

    validated = []
    for product_id in product_ids:
        registry_item = PRODUCT_ENTITY_REGISTRY.get(product_id)
        if not registry_item:
            continue
        if registry_entity_is_explicitly_mentioned(user_query, registry_item):
            validated.append((product_id, registry_item))

    return validated


    query_entities = detect_query_entities(user_query)
    product_ids = query_entities.get("products", []) or []
    return [
        (product_id, PRODUCT_ENTITY_REGISTRY[product_id])
        for product_id in product_ids
        if product_id in PRODUCT_ENTITY_REGISTRY
    ]


def build_safe_metadata_filter_for_entities(user_query: str):
    """
    Build a safe Chroma metadata filter from domain_registry retrieval_hints.
    This is global: it works for any entity whose metadata is actually present
    in Chroma, instead of hardcoding per-product rules.

    It intentionally avoids filters for sparse or missing metadata because those
    caused empty retrieval for some products earlier.
    """
    if is_papercut_query(user_query):
        return make_chroma_filter(vendor="papercut")

    counts = get_vectorstore_metadata_value_counts()
    product_counts = counts.get("product", {})
    vendor_counts = counts.get("vendor", {})

    for product_id, registry_item in get_detected_product_entities_with_registry(user_query):
        hints = registry_item.get("retrieval_hints", {}) or {}
        product_hint = hints.get("product")
        vendor_hint = hints.get("vendor")
        component_hint = hints.get("component")

        if not product_hint:
            continue

        product_key = str(product_hint).lower()
        vendor_key = str(vendor_hint).lower() if vendor_hint else None

        # Apply product filter only when the product metadata exists in Chroma.
        if product_counts.get(product_key, 0) >= 3:
            filter_kwargs = {"product": product_hint}

            # Add vendor only when that vendor is present; this makes the filter
            # more precise without risking empty results due to casing/sparsity.
            if vendor_hint and vendor_counts.get(vendor_key, 0) >= 3:
                filter_kwargs["vendor"] = str(vendor_hint).lower()

            # Component filters are useful only when the metadata actually exists.
            if component_hint:
                component_counts = counts.get("component", {})
                if component_counts.get(str(component_hint).lower(), 0) >= 3:
                    filter_kwargs["component"] = component_hint

            return make_chroma_filter(**filter_kwargs)

    return None


def get_entity_preferred_terms(user_query: str) -> list[str]:
    """
    Return canonical names and aliases for detected entities.
    Used by retrieval profile and reranking across all products/domains.
    """
    terms: list[str] = []
    for _, registry_item in get_detected_product_entities_with_registry(user_query):
        canonical_name = registry_item.get("canonical_name")
        if canonical_name:
            terms.append(str(canonical_name).lower())
        terms.extend(str(alias).lower() for alias in registry_item.get("aliases", []) or [])

        hints = registry_item.get("retrieval_hints", {}) or {}
        for value in hints.values():
            if value:
                terms.append(str(value).lower())

    # Stable de-duplication preserving order.
    seen = set()
    unique_terms = []
    for term in terms:
        term = term.strip()
        if term and term not in seen:
            seen.add(term)
            unique_terms.append(term)
    return unique_terms


def compute_generic_entity_alignment_score(user_query: str, metadata: dict, content: str) -> float:
    """
    Generic entity-aware reranking boost used for all registered products.
    It rewards exact product metadata matches and title/source/alias matches.
    """
    score = 0.0
    metadata = metadata or {}
    content = (content or "").lower()

    title = str(metadata.get("title", "")).lower()
    source = str(metadata.get("source", "")).lower()
    vendor = str(metadata.get("vendor", "")).lower()
    product = str(metadata.get("product", "")).lower()
    component = str(metadata.get("component", "")).lower()
    collection_name = str(metadata.get("collection_name", "")).lower()
    folder_origin = str(metadata.get("folder_origin", "")).lower()
    title_source = " ".join([title, source, vendor, product, component, collection_name, folder_origin])

    for product_id, registry_item in get_detected_product_entities_with_registry(user_query):
        hints = registry_item.get("retrieval_hints", {}) or {}
        hint_product = str(hints.get("product", "")).lower()
        hint_vendor = str(hints.get("vendor", "")).lower()
        hint_component = str(hints.get("component", "")).lower()
        aliases = [str(a).lower() for a in registry_item.get("aliases", []) or []]
        canonical = str(registry_item.get("canonical_name", "")).lower()
        terms = [canonical] + aliases + [hint_product, hint_component]
        terms = [t for t in terms if t]

        if hint_product and product == hint_product:
            score += 8.0
        if hint_vendor and vendor == hint_vendor:
            score += 1.0
        if hint_component and component == hint_component:
            score += 2.5

        if any(term in title_source for term in terms):
            score += 4.0
        if any(term in content[:1800] for term in terms):
            score += 1.5

        # Penalize documents from a different stable product when the query has
        # a clearly detected product and the document does not mention that entity.
        if hint_product and product and product != hint_product:
            if not any(term in title_source or term in content[:1800] for term in terms):
                score -= 4.0

    return score


def compute_explicit_entity_identity_score(user_query: str, metadata: dict, content: str) -> float:
    """Transversal entity-title/source alignment for sparse internal domains.

    Internal tools can share generic metadata such as sanitized_support_assets.
    Exact title/source matches therefore deserve a strong boost, while sibling
    internal documents that do not mention the requested entity are penalized.
    The implementation is registry-driven, not product-question-specific.
    """
    metadata = metadata or {}
    title = str(metadata.get("title", "")).lower()
    source = str(metadata.get("source", "")).lower()
    content_head = str(content or "").lower()[:1400]
    identity = f"{title} {source}"

    score = 0.0
    detected = get_detected_product_entities_with_registry(user_query)
    if not detected:
        return score

    for _, registry_item in detected:
        canonical = str(registry_item.get("canonical_name", "")).lower().strip()
        aliases = [
            str(alias).lower().strip()
            for alias in registry_item.get("aliases", []) or []
            if str(alias).strip()
        ]
        explicit_terms = [term for term in [canonical] + aliases if len(term) >= 4]
        if not explicit_terms:
            continue

        identity_match = any(
            entity_alias_is_explicitly_mentioned(identity, term)
            for term in explicit_terms
        )
        content_match = any(
            entity_alias_is_explicitly_mentioned(content_head, term)
            for term in explicit_terms
        )

        if identity_match:
            score += 14.0
        elif content_match:
            score += 3.0
        else:
            vendor = str(metadata.get("vendor", "")).lower()
            product = str(metadata.get("product", "")).lower()
            if vendor == "arus_internal" or product == "sanitized_support_assets":
                score -= 7.0

    return score


# -----------------------------------------------------------------------------
# vNext transversal retrieval helpers - V8
# -----------------------------------------------------------------------------
# This layer is intentionally issue-oriented instead of product-question-specific.
# It improves retrieval for recurring support symptoms through configurable packs.

BACKEND_VNEXT_MARKER = "v14_transversal_identity_and_topic_alignment"

ISSUE_RETRIEVAL_PACKS = {
    "missing_print_jobs": {
        "intent_any": ["troubleshooting"],
        "query_any": [
            "desaparec", "no aparecen", "no aparece", "perdido", "perdidos",
            "missing", "disappearing", "where have my print jobs gone",
            "trabajos enviados no imprimen", "trabajo enviado no imprime",
        ],
        "expansions": [
            "missing or disappearing print jobs",
            "where have my print jobs gone",
            "print jobs not being tracked",
            "print jobs not held",
            "jobs pending release",
            "temporarily hidden message",
            "print provider release station",
        ],
        "boost_identity": {
            "MissingOrDisappearingPrintJobs": 120.0,
            "Troubleshooting Missing or Disappearing Print Jobs": 100.0,
            "PrintJobsNotHeld": 60.0,
            "PrintingNotBeingTracked": 55.0,
            "TemporarilyHiddenMessage": 35.0,
            "find-me-printing-troubleshooting": 25.0,
        },
        "boost_content": {
            "where have my print jobs gone": 12.0,
            "print jobs not held": 8.0,
            "not being tracked by PaperCut": 8.0,
            "temporarily hidden": 6.0,
        },
        "penalize_identity": {
            "AmalgamatePrinterQueues": -35.0,
            "HideDocumentNameOnWindowsPrinters": -35.0,
            "DownloadEmbeddedManuals": -35.0,
            "Easy-secure-cerner-printing-with-papercut": -35.0,
            "WindowsType4PrintDrivers": -35.0,
            "HowToRenameAPrinter": -35.0,
            "PurchasingNewPrinters": -35.0,
            "managing-cloud-hosted-epic-print-jobs-with-papercut-mf": -35.0,
            "PrintToFile": -35.0,
            "WindowsSlowPrinting": -35.0,
            "YouAreChargingToARestrictedAccount": -35.0,
            "QueueRedirectionLinuxExample": -35.0,
            "DeployMobilityQueuesByGroup": -35.0,
            "PreventUsersFromPrintingJobsViaMobility": -35.0,
            "PrintArchivingLPR": -35.0,
            "MigratingNGToNewServer": -35.0,
            "HowToMigrateWindowsPrintQueues": -35.0,
            "BatchDeletingPrinters": -35.0,
            "PrinterFailover": -35.0,
            "FixingPrintSpoolerCrashes": -35.0,
            "ActiveUserClients": -35.0,
            "DoINeedAPrintServer": -35.0,
            "WebPrintStatusMessages": -35.0,
            "ChangingServerNameIP": -35.0,
        },
    },
    "jobs_not_held": {
        "intent_any": ["troubleshooting"],
        "query_any": [
            "no quedan retenidos", "no queda retenido", "no se retienen",
            "no se pausa", "no se pausan", "salen directamente",
            "se imprimen directamente", "not held", "not paused",
            "bypass hold", "bypass release",
        ],
        "expansions": [
            "print jobs not held or paused",
            "hold release queue jobs print directly",
            "print jobs not being tracked",
        ],
        "boost_identity": {
            "PrintJobsNotHeld": 80.0,
            "PrintingNotBeingTracked": 45.0,
        },
        "boost_content": {
            "not being paused": 10.0,
            "not held": 10.0,
            "not being tracked": 8.0,
        },
        "penalize_identity": {
            "ChangingJobTimeoutOnReleaseStation": -18.0,
            "TroubleshootingServerPerformanceIssues": -12.0,
        },
    },
    "jobs_remain_held": {
        "intent_any": ["troubleshooting"],
        "query_any": [
            "quedan retenidos", "queda retenido", "siguen retenidos",
            "sigue retenido", "no se liberan", "no se libera",
            "pendientes de liberación", "pendientes de liberacion",
            "remain held", "remain in hold", "stuck in hold",
            "jobs pending release",
        ],
        "expansions": [
            "jobs pending release hold release queue",
            "configure how long jobs are held",
            "release station jobs remain held",
            "temporarily hidden print provider",
        ],
        "boost_identity": {
            "ChangingJobTimeoutOnReleaseStation": 70.0,
            "TroubleshootingServerPerformanceIssues": 48.0,
            "TemporarilyHiddenMessage": 42.0,
            "device-mf-copier-integration-release": 36.0,
            "PrintJobsNotHeld": -22.0,
        },
        "boost_content": {
            "jobs pending release": 14.0,
            "hold/release jobs": 12.0,
            "release station": 9.0,
            "job timeout": 9.0,
        },
        "penalize_identity": {
            "WebPrintStatusMessages": -18.0,
            "Touch-FreeSecurePrintRelease": -10.0,
            "UserClientPopupAndNotificationIssues": -10.0,
        },
    },
    "find_me_printing": {
        "intent_any": ["troubleshooting", "procedural", "conceptual"],
        "query_any": ["find-me", "find me", "findme", "follow me", "pull print", "cola virtual"],
        "expansions": ["set up find-me printing", "troubleshooting find-me printing virtual queues", "secure print release find-me printing", "destination queues virtual print queue"],
        "boost_identity": {"find-me-printing-setup-mf": 60.0, "find-me-printing-troubleshooting": 60.0, "device-mf-copier-integration-release-find-me": 50.0, "find-me-printing-and-load-balancing-faq": 35.0},
        "boost_content": {"find-me printing": 8.0, "virtual print queue": 8.0, "destination queues": 6.0},
        "penalize_identity": {},
    },
    "queue_stuck_or_blocked": {
        "intent_any": ["troubleshooting"],
        "query_any": ["cola", "queue", "spooler", "bloqueada", "atascada", "stuck"],
        "expansions": ["print queue stuck", "jobs stuck with status of printing", "windows print spooler stability", "print queue driver troubleshooting", "printer queue not printing"],
        "boost_identity": {"JobsStuckWithStatusOfPrinting": 60.0, "FixingPrintSpoolerCrashes": 35.0, "BasicPrintingTests": 20.0, "find-me-printing-troubleshooting": 16.0},
        "boost_content": {"print queue": 6.0, "spooler": 6.0, "stuck": 5.0, "driver": 3.0},
        "penalize_identity": {},
    },
}

TANGENTIAL_SOURCE_RULES = [
    {"query_absent_any": ["mobility", "mobility print", "impresión móvil", "impresion movil", "mobile print"], "source_any": ["mobility-print", "mobilityprint", "mobility"], "penalty": -20.0},
    {"query_absent_any": ["print deploy", "print-deploy"], "source_any": ["print-deploy", "printdeploy"], "penalty": -20.0},
    {"query_absent_any": ["job ticketing", "job-ticketing"], "source_any": ["job-ticketing", "jobticketing"], "penalty": -20.0},
]


def normalize_for_match(value: str) -> str:
    return str(value or "").lower().replace("-", "").replace("_", "").replace("/", "").replace(" ", "")


def is_papercut_query(query: str) -> bool:
    text = str(query or "").lower()
    return "papercut" in text or "paper cut" in text


def get_doc_source_identity(metadata: dict) -> str:
    metadata = metadata or {}
    return " ".join([
        str(metadata.get("title", "")),
        str(metadata.get("source", "")),
        str(metadata.get("source_url", "")),
        str(metadata.get("canonical_url", "")),
        str(metadata.get("vendor", "")),
        str(metadata.get("product", "")),
        str(metadata.get("source_type", "")),
        str(metadata.get("document_family", "")),
    ]).lower()


def get_matching_issue_packs(query: str, query_intent: str | None = None) -> list[tuple[str, dict]]:
    text = str(query or "").lower()
    query_intent = query_intent or classify_query_intent(query)
    matches = []
    for pack_name, pack in ISSUE_RETRIEVAL_PACKS.items():
        allowed_intents = pack.get("intent_any") or []
        if allowed_intents and query_intent not in allowed_intents:
            continue
        if any(trigger in text for trigger in pack.get("query_any", []) or []):
            matches.append((pack_name, pack))
    return matches


def build_transversal_expanded_queries(query: str, query_intent: str | None = None) -> list[str]:
    """Build a compact, intent-aware expansion set.

    Debug retrieval can still inspect the final six documents, but fewer vector
    queries reduce latency and candidate noise, especially for PaperCut.
    """
    query_intent = query_intent or classify_query_intent(query)
    expansions = [query]
    entity_terms = get_entity_preferred_terms(query)
    entity_context = " ".join(entity_terms[:4])

    for _, pack in get_matching_issue_packs(query, query_intent):
        for expansion in (pack.get("expansions", []) or [])[:4]:
            expansions.append(f"{entity_context} {expansion}".strip())

    if query_intent == "conceptual" and entity_context:
        expansions.extend([
            f"{entity_context} overview introduction purpose features",
            f"{entity_context} descripción general para qué sirve componentes",
        ])

    if is_papercut_query(query):
        expansions.append(f"PaperCut NG MF {query}")

    seen = set()
    unique = []
    for item in expansions:
        key = str(item).lower().strip()
        if key and key not in seen:
            seen.add(key)
            unique.append(item)

    max_queries = 7 if query_intent == "troubleshooting" else 5
    return unique[:max_queries]


def compute_issue_pack_rerank_score(query: str, doc, query_intent: str | None = None) -> float:
    query_intent = query_intent or classify_query_intent(query)
    metadata = doc.metadata or {}
    identity = get_doc_source_identity(metadata)
    normalized_identity = normalize_for_match(identity)
    content = str(doc.page_content or "").lower()
    score = 0.0
    for _, pack in get_matching_issue_packs(query, query_intent):
        for term, boost in (pack.get("boost_identity") or {}).items():
            if normalize_for_match(term) in normalized_identity or str(term).lower() in identity:
                score += float(boost)
        for term, boost in (pack.get("boost_content") or {}).items():
            if str(term).lower() in content[:1600]:
                score += float(boost)
        for term, penalty in (pack.get("penalize_identity") or {}).items():
            if normalize_for_match(term) in normalized_identity:
                score += float(penalty)
    text = str(query or "").lower()
    for rule in TANGENTIAL_SOURCE_RULES:
        query_absent = not any(term in text for term in rule.get("query_absent_any", []))
        source_has = any(normalize_for_match(term) in normalized_identity for term in rule.get("source_any", []))
        if query_absent and source_has:
            score += float(rule.get("penalty", 0.0))
    return score


def get_anchor_docs_for_issue_packs(vectorstore, query: str, query_intent: str | None = None, metadata_filter=None) -> list:
    """Deterministically add exact title/source matches from issue packs.

    Vector similarity can miss the exact KB article due cross-lingual wording.
    This scan is bounded by metadata filter/vendor and only adds documents whose
    source/title match configured issue-pack anchors. It is transversal because
    anchors live in ISSUE_RETRIEVAL_PACKS, not in retrieval code.
    """
    query_intent = query_intent or classify_query_intent(query)
    packs = get_matching_issue_packs(query, query_intent)
    if not packs:
        return []
    anchor_terms = []
    for _, pack in packs:
        anchor_terms.extend((pack.get("boost_identity") or {}).keys())
    if not anchor_terms:
        return []

    where_filter = metadata_filter if metadata_filter else None
    try:
        raw = vectorstore._collection.get(where=where_filter, include=["documents", "metadatas"], limit=20000)
    except Exception:
        try:
            raw = vectorstore._collection.get(include=["documents", "metadatas"], limit=20000)
        except Exception:
            return []

    documents = raw.get("documents") or []
    metadatas = raw.get("metadatas") or []
    anchor_docs = []
    seen = set()
    normalized_terms = [normalize_for_match(t) for t in anchor_terms]
    for content, metadata in zip(documents, metadatas):
        metadata = metadata or {}
        identity = normalize_for_match(get_doc_source_identity(metadata))
        if not any(term in identity for term in normalized_terms):
            continue
        key = metadata.get("source") or metadata.get("source_url") or metadata.get("canonical_url") or metadata.get("title")
        if key in seen:
            continue
        seen.add(key)
        anchor_docs.append(Document(page_content=content or "", metadata=metadata))
    return anchor_docs[:25]

def detect_query_profile(query: str):
    """
    Build a retrieval profile using query intent and lightweight hints.

    Important:
    - Do not apply hard metadata filters by default.
    - Hard filters caused empty retrieval for PaperCut MF and HP SDS when
      metadata did not match exactly.
    - Prefer broad retrieval + reranking.
    """
    text = query.lower()
    query_intent = classify_query_intent(query)

    initial_map = CONFIG.get("retrieval_top_k_by_intent", {})
    final_map = CONFIG.get("retrieval_final_top_k_by_intent", {})

    profile = {
        "intent": query_intent,
        "k_initial": initial_map.get(query_intent, initial_map.get("default", 12)),
        "k_final": final_map.get(query_intent, final_map.get("default", 4)),
        "filter": None,
        "must_terms": [],
        "avoid_terms": [],
        "preferred_terms": [],
    }

    if get_matching_issue_packs(query, query_intent):
        profile["k_initial"] = max(profile.get("k_initial", 12), 60)
        profile["k_final"] = max(profile.get("k_final", 4), 6)

    if is_papercut_query(query) and query_intent == "troubleshooting":
        profile["k_initial"] = max(profile.get("k_initial", 12), 80)
        profile["k_final"] = max(profile.get("k_final", 4), 6)

    if "papercut" in text:
        profile["preferred_terms"].extend([
            "papercut", "papercut mf", "print jobs", "jobs",
            "release", "hold", "held", "find-me",
            "trabajos", "liberación", "liberacion",
        ])

    if "papercut" in text and any(term in text for term in ["mobility", "mobility print", "impresión móvil", "impresion movil", "mobile print"]):
        profile["preferred_terms"].extend(["mobility print", "mobile print", "impresión móvil", "impresion movil"])

    if any(term in text for term in ["sds", "hp smart device services", "dca", "sda", "jamc"]):
        profile["preferred_terms"].extend([
            "sds", "smart device services", "hp smart device services",
            "monitor", "dca", "sda", "jamc",
            "requirements", "requisitos", "prerrequisitos",
        ])

    if any(term in text for term in ["cola", "queue", "spooler", "bloqueada", "atascada", "no imprime"]):
        profile["preferred_terms"].extend([
            "cola", "queue", "spooler", "print queue",
            "bloqueada", "atascada", "stuck", "held",
        ])

    if query_intent == "warranty":
        profile["preferred_terms"].extend([
            "garantía", "garantia", "warranty", "rma",
            "suministro", "suministros", "consumible", "consumibles",
            "reemplazo",
        ])
        profile["avoid_terms"].extend([
            "dashboard", "control operacion", "control operación",
            "pin", "autogestion", "autogestión",
        ])

    if query_intent == "escalation":
        profile["preferred_terms"].extend([
            "escalar", "escalamiento", "nivel 2", "nivel 3",
            "incidente", "ticket", "caso", "proveedor", "fabricante",
        ])

    entity_terms = get_entity_preferred_terms(query)
    if entity_terms:
        profile["preferred_terms"].extend(entity_terms)

    safe_filter = build_safe_metadata_filter_for_entities(query)
    if safe_filter is not None:
        profile["filter"] = safe_filter
        profile["k_initial"] = max(profile.get("k_initial", 12), 18)
        profile["k_final"] = max(profile.get("k_final", 4), 4)

    return profile
    
    # ------------------------------------------------------------------
    # Fallback generic heuristics only for stable metadata families
    # ------------------------------------------------------------------
    if any(term in text for term in ["papercut", "paper cut"]):
        profile["filter"] = make_chroma_filter(vendor="papercut")
        return profile

    if any(term in text for term in ["sds", "hp smart device services", "jamc", "dca"]):
        profile["filter"] = make_chroma_filter(vendor="hp", product="sds")
        return profile

    if any(term in text for term in ["web jet admin", "web jetadmin", "wja"]):
        profile["filter"] = make_chroma_filter(vendor="hp", product="web_jetadmin")
        return profile

    if any(term in text for term in ["access control", "hp ac", "hac"]):
        profile["filter"] = make_chroma_filter(vendor="hp", product="hp_access_control")
        return profile

    if any(term in text for term in ["gav tracking", "gav"]):
        profile["filter"] = make_chroma_filter(vendor="gav", product="gav_tracking")
        return profile

    if any(term in text for term in ["epson remote services", "ers"]):
        profile["filter"] = make_chroma_filter(vendor="epson", product="epson_remote_services")
        return profile

    if any(term in text for term in ["epson print admin", "epa"]):
        profile["filter"] = make_chroma_filter(vendor="epson", product="epson_print_admin")
        return profile

    # For internal/operational questions (DA Arus / Print Evolve / MFPsecure / SIMP),
    # do not constrain retrieval with metadata filters.
    return profile

    # ------------------------------------------------------------------
    # Fallback generic heuristics if no entity hints were detected
    # ------------------------------------------------------------------
    if any(term in text for term in ["papercut", "print jobs", "trabajos de impresión", "trabajos de impresion"]):
        profile["filter"] = make_chroma_filter(vendor="papercut")
        return profile

    if any(term in text for term in ["sds", "hp smart device services", "jamc", "dca"]):
        profile["filter"] = make_chroma_filter(vendor="hp", product="sds")
        return profile

    if any(term in text for term in ["web jet admin", "web jetadmin", "wja"]):
        profile["filter"] = make_chroma_filter(vendor="hp", product="web_jetadmin")
        return profile

    if any(term in text for term in ["access control", "hp ac", "hac"]):
        profile["filter"] = make_chroma_filter(vendor="hp", product="hp_access_control")
        return profile

    if any(term in text for term in ["gav tracking", "gav"]):
        profile["filter"] = make_chroma_filter(vendor="gav", product="gav_tracking")
        return profile

    if any(term in text for term in ["epson remote services", "ers"]):
        profile["filter"] = make_chroma_filter(vendor="epson", product="epson_remote_services")
        return profile

    if any(term in text for term in ["epson print admin", "epa"]):
        profile["filter"] = make_chroma_filter(vendor="epson", product="epson_print_admin")
        return profile

    return profile

def build_entity_retrieval_hints(query_entities: dict) -> dict:
    """
    Build retrieval hints from detected entities.

    Important:
    - hard_filter = True only when the entity has reliable metadata alignment
      with the vectorstore (e.g. HP SDS, WJA, GAV, HAC).
    - hard_filter = False for internal/support/DA Arus style entities or when
      the entity concept does not map cleanly to vectorstore product metadata.
    """
    hints = {
        "vendor": None,
        "product": None,
        "component": None,
        "hard_filter": False,
    }

    for product_id in query_entities.get("products", []):
        entity = PRODUCT_ENTITY_REGISTRY.get(product_id)
        if not entity:
            continue

        entity_hints = entity.get("retrieval_hints", {})
        hint_vendor = entity_hints.get("vendor")
        hint_product = entity_hints.get("product")
        hint_component = entity_hints.get("component")

        if hints["vendor"] is None and hint_vendor:
            hints["vendor"] = hint_vendor
        if hints["product"] is None and hint_product:
            hints["product"] = hint_product
        if hints["component"] is None and hint_component:
            hints["component"] = hint_component

        # Use hard filters only for entities whose metadata is likely
        # to exist consistently in the vectorstore.
        if product_id in {
            "hp_sds",
            "hp_sds_monitor",
            "hp_sds_dca",
            "jamc",
            "hp_web_jetadmin",
            "hp_access_control",
            "gav_tracking",
            "papercut_mf",
            "papercut_hive",
            "papercut_ng",
            "epson_remote_services",
            "epson_print_admin",
        }:
            hints["hard_filter"] = True

        # Internal/operational tools should not force a hard metadata filter.
        if product_id in {
            "print_evolve",
            "mfpsecure",
            "mipa_agent",
            "dashboard_simp",
            "da_arus",
        }:
            hints["hard_filter"] = False

    return hints

def compute_rerank_score(query: str, doc, query_intent: str | None = None) -> float:
    """
    Query-aware heuristic reranking.

    Goals:
    - Recover PaperCut/SDS documents even when metadata filters are imperfect.
    - Reduce source contamination.
    - Promote exact title/source/product matches.
    - Keep priority useful, but not dominant.
    """
    text = query.lower()
    content = doc.page_content.lower()
    metadata = doc.metadata or {}

    query_intent = query_intent or classify_query_intent(query)

    title = str(metadata.get("title", "")).lower()
    source = str(metadata.get("source", "")).lower()
    vendor = str(metadata.get("vendor", "")).lower()
    product = str(metadata.get("product", "")).lower()
    component = str(metadata.get("component", "")).lower()
    document_family = str(metadata.get("document_family", "")).lower()
    source_type = str(metadata.get("source_type", "")).lower()

    title_source = f"{title} {source} {vendor} {product} {component} {document_family}"

    score = 0.0
    score += compute_generic_entity_alignment_score(query, metadata, content)
    score += compute_explicit_entity_identity_score(query, metadata, content)
    score += compute_document_identity_anchor_score(query, metadata, content)
    score += compute_issue_pack_rerank_score(query, doc, query_intent)

    # Global conceptual-query boost.
    # For "qué es / what is" style questions, prefer introduction, overview,
    # definition and purpose chunks over admin/detail-only chunks.
    if query_intent == "conceptual":
        conceptual_overview_terms = [
            "introduction",
            "introducción",
            "introduccion",
            "overview",
            "descripción general",
            "descripcion general",
            "definition",
            "definición",
            "definicion",
            "purpose",
            "propósito",
            "proposito",
            "what is",
            "qué es",
            "que es",
            "solution",
            "solución",
            "solucion",
            "allows an organization",
            "permite",
            "componentes",
            "components",
        ]

        if any(term in content[:1600] for term in conceptual_overview_terms):
            score += 3.5

        # Prefer early meaningful intro pages over deep admin/reference pages.
        try:
            page_number = int(str(metadata.get("page", 999)))
        except Exception:
            page_number = 999

        if page_number <= 30 and any(
            term in content[:1600]
            for term in conceptual_overview_terms
        ):
            score += 1.5

    # Priority should help, but not dominate semantic relevance.
    try:
        priority = int(metadata.get("priority", 3))
    except Exception:
        priority = 3
    score += max(0, 4 - priority) * 0.6

    # Source type signal.
    if source_type in {"pdf", "troubleshooting", "known_issue"}:
        score += 0.8
    elif source_type in {"kb_article", "manual", "guide"}:
        score += 0.5

    # Keyword overlap.
    query_tokens = [
        tok for tok in re.findall(r"\w+", text)
        if len(tok) > 2
    ]
    overlap = sum(1 for tok in query_tokens if tok in content)
    score += overlap * 0.25

    # Title/source exact-ish matching has high value.
    for tok in query_tokens:
        if tok in title_source:
            score += 0.45

    # PaperCut-specific boost.
    if "papercut" in text:
        if "papercut" in title_source:
            score += 5.0
        if "papercut" in content:
            score += 2.0

        if any(t in text for t in ["desaparecen", "desaparece", "disappearing", "missing", "trabajos"]):
            if any(t in content for t in [
                "print job", "print jobs", "job", "jobs",
                "held", "hold", "release", "released",
                "trabajo", "trabajos", "liberar", "liberación", "liberacion",
                "desaparece", "desaparecen",
            ]):
                score += 3.5

        # Penalize unrelated internal docs if they do not mention PaperCut.
        if "papercut" not in title_source and "papercut" not in content:
            score -= 4.0

    # HP SDS / requirements boost.
    if any(t in text for t in ["sds", "smart device services", "hp smart device services"]):
        if any(t in title_source for t in ["sds", "smart device services"]):
            score += 5.0
        if any(t in content for t in ["sds", "smart device services"]):
            score += 2.0

        if query_intent == "requirements":
            if any(t in content for t in [
                "requirements", "requisitos", "prerrequisitos",
                "system requirements", "minimum requirements",
                "compatible", "compatibilidad",
                "operating system", "sistema operativo",
                "hardware", "network", "red",
            ]):
                score += 3.0

    # Queue / spooler troubleshooting boost.
    if any(t in text for t in ["cola", "queue", "spooler", "bloqueada", "atascada"]):
        if any(t in title_source for t in ["cola", "queue", "spooler"]):
            score += 3.0
        if any(t in content for t in [
            "cola", "queue", "spooler", "print queue",
            "bloqueada", "atascada", "stuck",
            "detiene", "stopped", "reiniciar", "restart",
        ]):
            score += 2.0

    # Warranty / supplies boost and contamination control.
    if query_intent == "warranty":
        if any(t in title_source for t in [
            "garantía", "garantia", "warranty",
            "suministro", "suministros",
            "consumible", "consumibles",
        ]):
            score += 6.0

        if any(t in content for t in [
            "garantía", "garantia", "warranty",
            "suministro", "suministros",
            "consumible", "consumibles",
            "reemplazo", "rma",
        ]):
            score += 2.0

        if any(t in title_source for t in [
            "dashboard", "control operacion", "control operación",
            "pin", "autogestion", "autogestión",
        ]):
            score -= 5.0

    # Escalation boost.
    if query_intent == "escalation":
        if any(t in content for t in [
            "escalar", "escalamiento", "nivel 2", "nivel 3",
            "incidente", "ticket", "caso", "proveedor", "fabricante",
        ]):
            score += 2.5

    # Penalize cover/legal/confidential-only chunks.
    legal_noise_terms = [
        "aviso legal",
        "información restringida",
        "informacion restringida",
        "confidencial",
        "uso exclusivo",
    ]
    if any(t in content[:800] for t in legal_noise_terms):
        meaningful_terms = overlap
        if meaningful_terms <= 1:
            score -= 3.0
        else:
            score -= 1.0

    # Generic noisy docs.
    if "known issues" in title and query_intent != "troubleshooting":
        score -= 1.5
    if "end user articles" in title:
        score -= 1.0
    if "knowledge base" in title and "papercut" not in text:
        score -= 1.0

    return score

def is_tangential_source_for_query(query: str, doc) -> bool:
    """
    Detect whether a source is likely tangential to the user's query.

    This is product-agnostic. It prevents the model from using procedures
    from adjacent but different processes, such as PIN, warranty, installation,
    maintenance, billing, brochures or portals, when the query is about a
    different support need.
    """
    text = query.lower()
    metadata = doc.metadata or {}

    content = str(doc.page_content or "").lower()
    title = str(metadata.get("title", "")).lower()
    source = str(metadata.get("source", "")).lower()
    document_family = str(metadata.get("document_family", "")).lower()
    component = str(metadata.get("component", "")).lower()
    product = str(metadata.get("product", "")).lower()

    query_intent = classify_query_intent(query)

    # Use title/source/metadata as stronger signal of what the document is about.
    # Content can contain incidental mentions, so title/source are more important.
    source_identity = f"{title} {source} {document_family} {component} {product}"
    source_head = f"{source_identity} {content[:800]}"

    def query_has_any(terms: list[str]) -> bool:
        return any(term in text for term in terms)

    def source_identity_has_any(terms: list[str]) -> bool:
        return any(term in source_identity for term in terms)

    def source_has_any(terms: list[str]) -> bool:
        return any(term in source_head for term in terms)

    process_categories = {
        "pin_autogestion": [
            "pin",
            "autogestion",
            "autogestión",
            "credencial",
            "credenciales",
            "portal",
            "papercut hive",
            "hive",
        ],
        "warranty": [
            "garantía",
            "garantia",
            "garantías",
            "garantias",
            "warranty",
            "rma",
            "reemplazo",
        ],
        "installation": [
            "instalar",
            "instalación",
            "instalacion",
            "incorporar",
            "enrolar",
            "enroll",
            "setup",
            "configurar",
        ],
        "maintenance": [
            "mantenimiento",
            "preventivo",
            "limpiar cabezal",
            "cabezal",
            "limpieza",
        ],
        "billing": [
            "facturación",
            "facturacion",
            "cobro",
            "tarifa",
            "valorización",
            "valorizacion",
        ],
        "brochure": [
            "brochure",
            "folleto",
            "comercial",
        ],
    }

    # -------------------------------------------------------------------------
    # Troubleshooting
    # -------------------------------------------------------------------------
    if query_intent == "troubleshooting":
        for category_name, category_terms in process_categories.items():
            query_is_about_category = query_has_any(category_terms)

            # Strong tangential signal: the document title/source/metadata is centered
            # on a different process that the user did not ask about.
            source_is_centered_on_category = source_identity_has_any(category_terms)

            if source_is_centered_on_category and not query_is_about_category:
                return True

        # Additional guard:
        # If the query is about jobs/queue/disappearing work, do not use documents
        # centered on PIN/autogestion/portal unless the user explicitly asks for PIN or portal.
        job_or_queue_query = query_has_any([
            "trabajo",
            "trabajos",
            "desaparece",
            "desaparecen",
            "desaparecido",
            "cola",
            "queue",
            "retenido",
            "retenidos",
            "liberar",
        ])

        pin_or_portal_source = source_identity_has_any(
            process_categories["pin_autogestion"]
        )

        pin_or_portal_query = query_has_any(
            process_categories["pin_autogestion"]
        )

        if job_or_queue_query and pin_or_portal_source and not pin_or_portal_query:
            return True

    # -------------------------------------------------------------------------
    # Requirements
    # -------------------------------------------------------------------------
    if query_intent == "requirements":
        # Reject brochures/general marketing documents for requirements.
        if source_has_any(process_categories["brochure"]):
            return True

        # Reject warranty/maintenance docs for requirements unless explicitly asked.
        for category_name in ["warranty", "maintenance", "billing"]:
            category_terms = process_categories[category_name]
            if source_identity_has_any(category_terms) and not query_has_any(category_terms):
                return True

    # -------------------------------------------------------------------------
    # Warranty
    # -------------------------------------------------------------------------
    if query_intent == "warranty":
        warranty_terms = process_categories["warranty"] + [
            "suministro",
            "suministros",
            "consumible",
            "consumibles",
        ]

        if not source_has_any(warranty_terms):
            return True

    # -------------------------------------------------------------------------
    # Procedural
    # -------------------------------------------------------------------------
    if query_intent == "procedural":
        # If user asks for a procedure, avoid unrelated warranty/billing/brochure docs.
        for category_name in ["warranty", "billing", "brochure"]:
            category_terms = process_categories[category_name]
            if source_identity_has_any(category_terms) and not query_has_any(category_terms):
                return True

    return False

def should_keep_ranked_doc(
    query: str,
    doc,
    score: float,
    top_score: float,
    query_intent: str,
) -> bool:
    """
    Decide whether a reranked document is relevant enough to be sent
    to the final LLM context.

    This function is intentionally strict by intent to reduce source contamination.
    """
    text = query.lower()
    content = doc.page_content.lower()
    metadata = doc.metadata or {}

    title = str(metadata.get("title", "")).lower()
    source = str(metadata.get("source", "")).lower()
    vendor = str(metadata.get("vendor", "")).lower()
    product = str(metadata.get("product", "")).lower()
    component = str(metadata.get("component", "")).lower()
    document_family = str(metadata.get("document_family", "")).lower()

    title_source = f"{title} {source} {vendor} {product} {component} {document_family}"

    if top_score <= 0:
        return score > 0

    relative_score = score / top_score

    legal_noise_terms = [
        "aviso legal",
        "información de uso interno",
        "informacion de uso interno",
        "información restringida",
        "informacion restringida",
        "confidencial",
        "uso exclusivo",
        "divulgación, reenvío, copia",
        "divulgacion, reenvio, copia",
        "estrictamente prohibida",
    ]

    is_legal_or_cover_noise = any(term in content[:1200] for term in legal_noise_terms)

    operational_papercut_terms = [
        "trabajos de impresión",
        "trabajos de impresion",
        "registro de trabajos",
        "registro de trabajos de cada usuario",
        "información de los usuarios",
        "informacion de los usuarios",
        "usuarios",
        "liberar",
        "liberación",
        "liberacion",
        "trabajos retenidos",
        "cola",
        "print jobs",
        "held jobs",
        "release jobs",
    ]

    useful_sds_requirement_terms = [
        "requirements",
        "requisitos",
        "prerrequisitos",
        "system requirements",
        "minimum requirements",
        "sistema operativo",
        "operating system",
        "windows server",
        "windows 10",
        "virtualización",
        "virtualizacion",
        "vmware",
        "hyperv",
        "hardware",
        "red",
        "network",
    ]

    useful_warranty_terms = [
        "garantía",
        "garantia",
        "garantías",
        "garantias",
        "warranty",
        "suministro",
        "suministros",
        "consumible",
        "consumibles",
        "proveedor",
        "proveedores",
        "reemplazo",
        "rma",
        "trámite de garantías",
        "tramite de garantias",
    ]

    useful_escalation_terms = [
        "escalar",
        "escalamiento",
        "nivel 2",
        "nivel 3",
        "incidente",
        "ticket",
        "caso",
        "proveedor",
        "fabricante",
        "informar al área",
        "informar al area",
        "mesa de ayuda",
    ]

    # PaperCut-focused queries.
    if "papercut" in text:
        has_papercut = "papercut" in title_source or "papercut" in content
        has_operational_papercut_content = any(
            term in content for term in operational_papercut_terms
        )
    
        # Reject cover/legal chunks even if they mention PaperCut MF.
        if is_legal_or_cover_noise and not has_operational_papercut_content:
            return False
    
        # Keep real operational PaperCut content.
        if has_papercut and has_operational_papercut_content and score >= 4:
            return True
    
        # Fallback for strong PaperCut chunks, but only if they are not legal/cover noise.
        if (
            has_papercut
            and not is_legal_or_cover_noise
            and score >= 8
            and relative_score >= 0.55
        ):
            return True
    
        return False

    # SDS requirements.
    if any(term in text for term in [
        "sds",
        "smart device services",
        "hp smart device services",
    ]):
        has_sds = any(term in title_source or term in content for term in [
            "sds",
            "smart device services",
            "dca",
            "sda",
            "jamc",
        ])

        has_requirement_signal = any(term in title_source or term in content for term in useful_sds_requirement_terms)

        if query_intent == "requirements":
            # For requirements, reject brochure/general marketing docs.
            if (
                "brochure" in title_source
                or "brochure" in source
                or document_family == "brochure"
            ):
                return False
        
            if has_sds and has_requirement_signal and score >= 5:
                return True
        
            if has_sds and "instalar monitor sds" in title_source and score >= 8:
                return True
        
            return False
            
        return has_sds and score >= 4

    # Warranty queries.
    if query_intent == "warranty":
        has_warranty_signal = any(term in title_source or term in content for term in useful_warranty_terms)

        # Strongly prefer the actual warranty document.
        if "garantía" in title_source or "garantia" in title_source:
            return score >= 3

        # Reject HP WJA and generic printer manuals for warranty questions.
        if "web jetadmin" in title_source or product == "web_jetadmin":
            return False

        if "mantprev" in title_source or "mantenimiento preventivo" in title_source:
            return False

        if has_warranty_signal and score >= 4 and relative_score >= 0.30:
            return True

        return False

    # Escalation queries.
    if query_intent == "escalation":
        has_escalation_signal = any(term in title_source or term in content for term in useful_escalation_terms)

        if has_escalation_signal and score >= 3:
            return True

        return score >= 5 and relative_score >= 0.6

    # Generic fallback: remove legal-only chunks and weak tail documents.
    if is_legal_or_cover_noise:
        return False

    if score >= 4 and relative_score >= 0.35:
        return True

    return False
def compute_keyword_overlap_ratio(query: str, content: str) -> float:
    query_tokens = [tok for tok in re.findall(r"\w+", query.lower()) if len(tok) > 2]
    if not query_tokens:
        return 0.0
    overlap = sum(1 for tok in query_tokens if tok in content.lower())
    return overlap / max(len(query_tokens), 1)


def assess_retrieval_support(query: str, docs: list) -> dict[str, Any]:
    if not docs:
        return {"support_level": "none", "top_score": 0.0, "avg_overlap": 0.0}

    scores = [compute_rerank_score(query, d) for d in docs]
    overlaps = [compute_keyword_overlap_ratio(query, d.page_content) for d in docs]
    top_score = max(scores) if scores else 0.0
    avg_overlap = sum(overlaps) / len(overlaps) if overlaps else 0.0

    if top_score >= 6.0 and avg_overlap >= 0.12:
        support_level = "strong"
    elif top_score >= 4.0 and avg_overlap >= 0.06:
        support_level = "partial"
    else:
        support_level = "weak" if docs else "none"

    return {
        "support_level": support_level,
        "top_score": round(top_score, 3),
        "avg_overlap": round(avg_overlap, 3),
    }


def classify_query_intent(user_query: str) -> str:
    text = user_query.lower()

    requirements_patterns = [
        "qué requerimientos", "que requerimientos",
        "qué requisitos", "que requisitos",
        "cuáles son los requisitos", "cuales son los requisitos",
        "cuáles son requisitos", "cuales son requisitos",
        "requisitos para instalar", "requisitos para instalación", "requisitos para instalacion",
        "requerimientos para instalar", "requerimientos para instalación", "requerimientos para instalacion",
        "requerimientos necesarios", "requisitos necesarios",
        "system requirements", "minimum requirements",
        "requisitos mínimos", "requisitos minimos",
        "prerrequisitos", "prerequisites",
        "compatibilidad", "compatible",
    ]

    troubleshooting_patterns = [
        "qué hacer si", "que hacer si",
        "qué debo hacer si", "que debo hacer si",
        "debo hacer si",
        "qué debería hacer si", "que deberia hacer si", "qué deberia hacer si", "que debería hacer si",
        "error", "falla", "fallando",
        "cola", "queue", "spooler",
        "bloqueada", "bloqueado", "atascada", "atascado", "atasco",
        "offline", "no imprime", "no deja imprimir",
        "desaparecen trabajos", "trabajos desaparecen",
        "desaparece", "desaparecen", "desaparecido",
        "disappearing", "disappear", "missing jobs",
        "stuck", "not held", "cannot add", "no puedo", "no deja",
        "qué debo revisar", "que debo revisar",
        "qué debería revisar", "que deberia revisar",
        "qué debo validar", "que debo validar",
        "qué debería validar", "que deberia validar",
        "trabajos retenidos", "trabajo retenido",
        "quedan retenidos", "queda retenido",
    ]

    warranty_patterns = [
        "garantía", "garantia", "warranty",
        "rma", "reemplazo", "suministro", "suministros",
        "consumible", "consumibles",
    ]

    escalation_patterns = [
        "escalar", "escalamiento", "nivel 2", "nivel 3",
        "abrir caso", "caso proveedor", "fabricante",
        "cuándo debo escalar", "cuando debo escalar",
    ]

    architecture_patterns = [
        "arquitectura", "integración", "integracion",
        "diagrama", "flujo", "modelo de seguridad", "arquitectura de seguridad",
    ]

    procedural_patterns = [
        "cómo instalar", "como instalar",
        "cómo se instala", "como se instala",
        "cómo realizar la instalación", "como realizar la instalacion",
        "cómo agregar", "como agregar",
        "cómo incorporar", "como incorporar",
        "cómo configurar", "como configurar",
        "cómo se configura", "como se configura",
        "cómo registrar", "como registrar",
        "cómo se registra", "como se registra",
        "cómo habilitar", "como habilitar",
        "cómo crear", "como crear",
        "cómo realizar", "como realizar",
        "cómo reinicio", "como reinicio",
        "cómo reiniciar", "como reiniciar",
        "reinicio manualmente", "reiniciar manualmente", "reiniciar el servicio", "reiniciar servicio",
        "procedimiento", "pasos", "trámite", "tramite",
        "cómo consultar", "como consultar",
        "cómo puedo comprobar", "como puedo comprobar",
        "comprobar y asignar",
        "consultar y asignar",
        "consultar pin",
        "comprobar pin",
        "asignar pin",
        "crear pin",
        "modificar pin",
        "actualizar pin",
        "visualizar pin",
        "buscar usuario",
        "gestionar pin",
        "cómo uso", "como uso", "cómo usar", "como usar",
    ]

    conceptual_patterns = [
        "qué es", "que es",
        "para qué sirve", "para que sirve",
        "cómo funciona", "como funciona",
        "qué hace", "que hace",
        "cuáles son los componentes", "cuales son los componentes",
        "componentes de",
        "explica", "diferencia entre",
    ]

    if any(p in text for p in warranty_patterns):
        return "warranty"

    if any(p in text for p in escalation_patterns):
        return "escalation"

    if any(p in text for p in requirements_patterns):
        return "requirements"

    if any(p in text for p in troubleshooting_patterns):
        return "troubleshooting"

    if any(p in text for p in procedural_patterns):
        return "procedural"

    if any(p in text for p in conceptual_patterns):
        return "conceptual"

    if any(p in text for p in architecture_patterns):
        return "architecture"

    return "default"

def has_hard_documentary_anchor(user_query: str, docs: list, query_intent: str) -> bool:
    if not docs:
        return False

    for doc in docs:
        content = doc.page_content.lower()
        md = doc.metadata
        product = str(md.get("product", "")).lower()
        component = str(md.get("component", "")).lower()
        family = str(md.get("document_family", "")).lower()
        title = str(md.get("title", "")).lower()
        source = str(md.get("source", "")).lower()

        if query_intent == "requirements":
            if (
                family == "requirements"
                or component == "requirements"
                or "requirement" in title
                or "requer" in title
                or "requirement" in source
                or "requer" in source
            ) and product in {"sds", "web_jetadmin", "hp_access_control", "gav_tracking"}:
                return True
            req_terms = ["requirements", "requisitos", "requerimientos", "hardware", "windows", "server", "ram", "disk", "vmware", "hyperv", "cpu", "monitor"]
            if any(t in content for t in req_terms):
                return True

        elif query_intent == "procedural":
            terms = ["install", "instal", "configure", "configur", "add", "agreg", "incorpor", "device", "printer", "embedded", "authentication", "oxp"]
            if any(t in content for t in terms):
                return True

        elif query_intent == "troubleshooting":
            terms = ["error", "issue", "problem", "troubleshoot", "stuck", "missing", "queue", "offline", "not held"]
            if any(t in content for t in terms):
                return True

        elif query_intent == "conceptual":
            if product or content:
                return True

    # Product metadata is not required for a strong process-document match.
    # This applies equally to billing, guarantees, PIN, firmware, installations,
    # and any future process whose query aligns with a document title/source.
    if query_intent in {"procedural", "default", "warranty", "architecture"}:
        return has_document_identity_anchor(user_query, docs)

    return False


FOLLOW_UP_REGEXES = [
    r"^(?:y\s+)?(?:eso|lo anterior|esa herramienta|ese software|ese sistema|ese producto|esa solución|esa solucion)$",
    r"^(?:qué|que|cuáles|cuales)\s+(?:requisitos|funciones|componentes|versiones|sistemas|plataformas|puertos|limitaciones)(?:\s+tiene|\s+necesita|\s+soporta)?$",
    r"^(?:cómo|como)\s+(?:se\s+)?(?:instala|configura|usa|funciona|actualiza|registra|desinstala)$",
    r"^(?:para\s+qué|para\s+que)\s+sirve$",
    r"^(?:qué|que)\s+versión\s+soporta$",
    r"^(?:y\s+)?(?:cómo|como|cuándo|cuando|dónde|donde|por qué|por que)$",
]


def is_explicit_follow_up_query(user_query: str) -> bool:
    text = normalize_route_text(user_query)
    if has_independent_question_subject(text):
        return False
    if len(text.split()) > 8:
        return False
    return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in FOLLOW_UP_REGEXES)


def get_conversation_topic(session_state: ChatSessionState) -> dict:
    topic = getattr(session_state, "conversation_topic", None)
    return dict(topic) if isinstance(topic, dict) else {}


def update_conversation_topic(session_state: ChatSessionState, user_message: str, intent: str | None = None):
    product_reference = get_explicit_product_reference(user_message)
    product_id = None
    product_name = None
    if product_reference:
        product_id, registry_item = product_reference
        product_name = str(registry_item.get("canonical_name") or product_id).strip()

    process_reference = has_explicit_process_reference(user_message)
    subject_terms = extract_conversation_subject_terms(user_message, product_name)
    process_name = normalize_route_text(user_message) if process_reference and not product_name else None

    if product_name or process_name:
        session_state.conversation_topic = {
            "product_id": product_id,
            "product_name": product_name,
            "process_name": process_name,
            "subject_terms": subject_terms,
            "intent": intent or classify_query_intent(user_message),
            "source_query": user_message,
        }


def build_contextual_follow_up_query(user_message: str, session_state: ChatSessionState) -> str | None:
    topic = get_conversation_topic(session_state)
    product_name = topic.get("product_name")
    process_name = topic.get("process_name")
    subject_terms = topic.get("subject_terms") or []
    if not product_name and not process_name:
        return None
    subject = " ".join(str(value) for value in subject_terms if value).strip()
    reference = f"{subject} de {product_name}" if product_name and subject else (product_name or process_name)
    return f"{user_message} Tema referido: {reference}"

def should_use_memory_for_query(user_query: str, query_intent: str) -> bool:
    """
    Use conversation memory only for explicit follow-up questions or escalation.
    This reduces prompt size, cost and cross-topic contamination.
    """
    if is_explicit_follow_up_query(user_query):
        return True

    if query_intent == "escalation":
        return True

    return False

def is_low_risk_general_query(user_query: str) -> bool:
    text = user_query.lower()
    low_risk_patterns = [
        "qué es", "que es", "para qué sirve", "para que sirve", "cómo funciona", "como funciona",
        "explica", "diferencia entre", "qué hace", "que hace",
    ]
    return any(p in text for p in low_risk_patterns)


def should_use_general_fallback(user_query: str, support_info: dict) -> bool:
    intent = classify_query_intent(user_query)
    if intent != "conceptual":
        return False
    return support_info["support_level"] != "strong"

def deduplicate_ranked_docs(docs: list) -> list:
    """
    Remove duplicated or near-duplicated chunks from the final context.

    Duplicates are detected using:
    - source
    - page or page_label
    - normalized content preview
    """
    unique_docs = []
    seen_keys = set()

    for doc in docs:
        metadata = doc.metadata or {}

        source = str(metadata.get("source", "unknown_source"))
        page = str(metadata.get("page", metadata.get("page_label", "unknown_page")))

        normalized_preview = " ".join(
            str(doc.page_content).lower().split()
        )[:300]

        key = (source, page, normalized_preview)

        if key in seen_keys:
            continue

        seen_keys.add(key)
        unique_docs.append(doc)

    return unique_docs

def is_low_information_chunk(doc) -> bool:
    """
    Detect chunks that are unlikely to help the LLM answer:
    covers, legal notices, table of contents, title-only pages or very short chunks.

    This is global and product-agnostic.
    """
    metadata = doc.metadata or {}
    content = " ".join(str(doc.page_content or "").lower().split())

    title = str(metadata.get("title", "")).lower()
    page_label = str(metadata.get("page_label", "")).lower()
    document_family = str(metadata.get("document_family", "")).lower()

    if not content:
        return True

    # Very short chunks usually contain only cover/title fragments.
    if len(content) < 120:
        return True

    low_value_terms = [
        "copyright and legal notice",
        "trademark credits",
        "table of contents",
        "índice",
        "indice",
        "aviso legal",
        "información de uso interno",
        "informacion de uso interno",
        "información restringida",
        "informacion restringida",
        "confidencial",
        "uso exclusivo",
    ]

    if any(term in content[:1200] for term in low_value_terms):
        return True

    # Cover/title-like technical guide pages.
    cover_like_patterns = [
        "technical training guide version",
        "administrator guide",
        "user guide",
        "guía del usuario",
        "guia del usuario",
    ]

    if page_label in {"i", "1"} and len(content) < 300:
        if any(pattern in content for pattern in cover_like_patterns):
            return True

    # Table of figures pages are usually not useful as final evidence.
    if "table of figures" in content[:1200]:
        return True

    return False

def extract_filter_clauses(metadata_filter) -> dict:
    """
    Convert a Chroma filter into a simple dict when possible.

    Supports:
    - {"vendor": "hp"}
    - {"$and": [{"product": "sds"}, {"vendor": "hp"}, {"component": "monitor"}]}
    """
    if not metadata_filter:
        return {}

    if "$and" in metadata_filter and isinstance(metadata_filter["$and"], list):
        merged = {}
        for clause in metadata_filter["$and"]:
            if isinstance(clause, dict):
                merged.update(clause)
        return merged

    if isinstance(metadata_filter, dict):
        return dict(metadata_filter)

    return {}


def build_controlled_filter_sequence(metadata_filter, query: str) -> list:
    """
    Build safe fallback filters without broad contamination.

    For explicit product queries:
    1. original filter
    2. vendor + product
    3. product only
    4. vendor only

    For PaperCut:
    - keep vendor-level behavior because NG/MF docs are shared.
    """
    if not metadata_filter:
        return [None]

    clauses = extract_filter_clauses(metadata_filter)

    vendor = clauses.get("vendor")
    product = clauses.get("product")
    component = clauses.get("component")

    filters = []

    # 1. Original filter first
    filters.append(metadata_filter)

    # PaperCut special case already uses vendor-level filtering.
    if is_papercut_query(query):
        if vendor:
            filters.append({"vendor": vendor})
        return deduplicate_filter_sequence(filters)

    # 2. vendor + product, dropping component
    if vendor and product:
        filters.append(make_chroma_filter(vendor=vendor, product=product))

    # 3. product only
    if product:
        filters.append({"product": product})

    # 4. vendor only
    if vendor:
        filters.append({"vendor": vendor})

    return deduplicate_filter_sequence(filters)


def deduplicate_filter_sequence(filters: list) -> list:
    """
    Remove duplicated filters while preserving order.
    """
    unique = []
    seen = set()

    for item in filters:
        key = json.dumps(item, sort_keys=True, ensure_ascii=False) if item is not None else "None"
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)

    return unique
    
def retrieve_context(query: str, top_k: int = 4):
    """Compatibility delegate. Productive retrieval lives in app.retrieval_runtime."""
    from app.retrieval_runtime import retrieve_context as _retrieve_context
    return _retrieve_context(query, top_k)

# -----------------------------------------------------------------------------
# Prompting + generation
# -----------------------------------------------------------------------------
SYSTEM_PROMPT = """
Eres Arus PrintAssist, un asistente especializado exclusivamente en soporte de primer nivel para servicios de impresión.

Tu función es:
- responder preguntas sobre impresoras, software de impresión y herramientas del servicio,
- orientar diagnósticos básicos de primer nivel,
- usar la base documental disponible como fuente principal,
- ayudar a estructurar un resumen de incidente si el caso requiere escalamiento.

Debes seguir estrictamente estas reglas:
- Responde únicamente sobre temas relacionados con impresión, software de impresión, herramientas del servicio y procedimientos técnicos.
- No respondas preguntas fuera de alcance.
- No inventes procedimientos críticos si la información disponible no es suficiente.
- Si la información documental no soporta claramente una respuesta, dilo de forma breve y profesional.
- No inventes nombres de fuentes.
- Solo puedes citar las fuentes exactas que te hayan sido proporcionadas en la lista de fuentes disponibles.
- No uses expresiones genéricas como \"Documentación oficial de...\" salvo que aparezcan literalmente en las fuentes disponibles.
- No menciones RAG, contexto recuperado, fallback, modelo ni arquitectura interna.
- Responde en español.
- Mantén un tono cordial, claro, profesional y orientado a resolver la necesidad del usuario.
- La respuesta debe priorizar utilidad práctica y trazabilidad real.
"""

def build_intent_instruction(
    query_intent: str,
    support_level: str,
    has_sources: bool,
    hard_anchor: bool = False,
    strong_entity_match: bool = False,
) -> str:
    """
    Build global response-policy instructions by query intent.

    This function must stay product-agnostic.
    Product/entity detection should influence retrieval and reranking,
    not create rigid product-specific answer flows.
    """

    grounding_policy = f"""
#### POLÍTICA GLOBAL DE GROUNDING

Nivel de soporte documental detectado: {support_level}
Hay fuentes recuperadas: {has_sources}
Hay anclaje documental fuerte: {hard_anchor}
Hay coincidencia fuerte entidad-documento: {strong_entity_match}

Reglas globales:
- Responde únicamente con base en la documentación recuperada.
- No inventes causas, pasos, compatibilidades, versiones, SLA, proveedores ni flujos.
- Si las fuentes son parciales, explica qué sí está soportado y qué no se puede concluir.
- Si hay fuentes recuperadas, no digas "no se encontraron coincidencias". En su lugar, indica que la documentación recuperada es limitada o no identifica una causa/procedimiento completo.
- Diferencia claramente entre:
  - información explícitamente documentada,
  - validaciones posibles,
  - límites de la documentación,
  - criterios prudentes de escalamiento.
- No menciones RAG, retrieval, chunks, embeddings, modelo ni arquitectura interna.

#### POLÍTICA DE CONSISTENCIA ENTIDAD-CONTEXTO

Reglas obligatorias:
- Si la pregunta menciona una herramienta, producto, proceso o síntoma específico, usa solo información que esté claramente relacionada con esa herramienta, producto, proceso o síntoma.
- No transfieras procedimientos entre productos parecidos o relacionados.
- No uses pasos de una fuente secundaria si esa fuente trata otro producto, otro proceso o un escenario distinto.
- Puedes citar una fuente tangencial solo si aporta una validación directamente aplicable a la pregunta.
- Si una fuente habla de PIN, autogestión, portal, credenciales, instalación, garantía, mantenimiento, facturación u otro proceso distinto al preguntado, no la uses para proponer acciones, salvo que el usuario pregunte explícitamente por ese proceso.
- No uses una fuente de PaperCut Hive para explicar PaperCut MF, ni una fuente de instalación para explicar troubleshooting, ni una fuente de garantía para explicar operación, salvo conexión explícita en el contexto.
- Si una fuente secundaria no está directamente alineada con la pregunta, puedes omitirla en la respuesta aunque esté disponible en la lista de fuentes.
"""

    if query_intent == "troubleshooting":
        return grounding_policy + """
    #### POLÍTICA PARA TROUBLESHOOTING
    
    Objetivo:
    Orientar diagnóstico inicial de soporte N1 sin inventar causa raíz, pasos técnicos ni validaciones no documentadas.
    
    La sección Respuesta debe usar exactamente esta estructura:
    
    ### Diagnóstico documental
    Explica qué permite concluir la documentación recuperada.
    Si las fuentes recuperadas no explican una causa raíz específica, escribe:
    "La documentación recuperada no identifica una causa raíz específica, pero sí permite realizar validaciones iniciales."
    
    No escribas:
    - "no se encontraron coincidencias" si sí hay fuentes recuperadas.
    - "el trabajo llegó al servidor" o "no llegó al servidor" salvo que la fuente lo indique explícitamente.
    - "problemas de conexión", "permisos", "agente de impresión", "logs", "servidor", "configuración del servidor", "driver" o "red" salvo que esos elementos aparezcan en el contexto documental.
    
    ### Validaciones iniciales
    Lista solo validaciones soportadas por las fuentes recuperadas.
    Una validación soportada puede ser:
    - revisar un registro mencionado en la documentación,
    - consultar una pantalla o menú documentado,
    - verificar una cola si la documentación habla de esa cola,
    - aplicar una acción explícitamente indicada por la fuente.
    
    No agregues validaciones genéricas de soporte técnico aunque parezcan razonables.
    
    ### Acciones recomendadas
    Lista acciones N1 permitidas por la documentación.
    Si la documentación solo permite consultar o validar, no presentes eso como solución.
    Si no hay procedimiento de resolución documentado, escribe:
    "No hay un procedimiento de resolución documentado en las fuentes recuperadas para este síntoma."
    
    ### Cuándo escalar
    Recomienda escalamiento cuando:
    - no exista procedimiento documentado suficiente,
    - el síntoma persista después de las validaciones soportadas,
    - falte evidencia para confirmar el diagnóstico,
    - exista impacto operativo relevante.
    
    Cuando recomiendes escalar, pide evidencia concreta:
    - usuario afectado,
    - equipo o impresora involucrada,
    - hora aproximada del trabajo,
    - cola o herramienta usada,
    - resultado de las validaciones documentadas,
    - capturas o mensajes de error si existen.
    
    Restricciones:
    - No presentes inferencias como hechos.
    - No completes el troubleshooting con conocimiento general.
    - No agregues pasos que no estén en el contexto.
    - Si una acción no aparece en la documentación, no la incluyas.
    - No uses procedimientos de autogestión, PIN, portales, credenciales, instalación, garantía, mantenimiento o administración si la pregunta es sobre un síntoma de troubleshooting y la fuente no conecta explícitamente ese procedimiento con el síntoma.
    - Si una fuente solo menciona un producto relacionado pero no el síntoma, úsala únicamente como referencia secundaria o no la uses.
    - La sección "Acciones recomendadas" debe contener solo acciones directamente soportadas por el contexto y alineadas con el síntoma consultado.
    - La sección "Cuándo escalar" no debe nombrar responsables específicos salvo que el documento los indique como responsables del escalamiento para ese tipo de caso.
    """

    if query_intent == "requirements":
        return grounding_policy + """
    #### POLÍTICA PARA REQUERIMIENTOS
    
    Objetivo:
    Responder requisitos técnicos sin mezclar pasos de instalación.
    
    La sección Respuesta debe organizarse por categorías cuando la documentación lo permita:
    
    ### Prerrequisitos del entorno
    Incluye condiciones previas explícitas.
    
    ### Sistemas operativos compatibles
    Lista únicamente sistemas operativos presentes en las fuentes.
    
    ### Plataformas compatibles
    Incluye virtualización, nube, servidor u otras plataformas solo si aparecen en fuentes.
    
    ### Requisitos mínimos de hardware
    Incluye CPU, memoria, disco u otros valores solo si están documentados.
    
    ### Requisitos de red o seguridad
    Incluye puertos, conectividad, ICMP, firewall, credenciales, certificados o permisos únicamente si aparecen en fuentes.
    
    ### Límites o notas
    Incluye advertencias, excepciones o notas relevantes.
    
    Restricciones:
    - No conviertas la respuesta en procedimiento de instalación.
    - No mezcles brochure, descripción comercial o arquitectura general como si fueran requisitos.
    - Si una categoría no está documentada, omítela.
    - Si las fuentes se contradicen, indícalo.
    """

    if query_intent == "procedural":
        return grounding_policy + """
    #### POLÍTICA PARA PROCEDIMIENTOS
    
    Objetivo:
    Guiar procedimientos operativos usando solo pasos documentados.
    
    La sección Respuesta debe usar esta estructura:
    
    ### Objetivo del procedimiento
    Resume para qué sirve el procedimiento documentado.
    
    ### Pasos soportados por la documentación
    Lista los pasos en orden lógico según las fuentes.
    No completes pasos faltantes con conocimiento general.
    
    ### Validaciones posteriores
    Incluye verificaciones de resultado solo si están soportadas por las fuentes.
    
    ### Precauciones o límites
    Indica si el procedimiento está incompleto, aplica solo a ciertos escenarios o requiere validación adicional.
    
    Restricciones:
    - No inventes pantallas, menús, botones, versiones o rutas.
    - Si no hay pasos suficientes, dilo y recomienda validar documentación adicional o escalar.
    """

    if query_intent == "conceptual":
        return grounding_policy + """
    #### POLÍTICA PARA CONSULTAS CONCEPTUALES
    
    Objetivo:
    Explicar conceptos, productos, componentes o funciones de forma clara y acotada.
    
    La sección Respuesta debe usar esta estructura cuando aplique:
    
    ### Definición
    Explica qué es el producto, herramienta, proceso o componente.
    
    ### Para qué sirve
    Explica su propósito operativo según las fuentes.
    
    ### Componentes o funciones principales
    Incluye componentes, módulos o capacidades documentadas.
    
    ### Límites según documentación disponible
    Indica lo que la documentación no permite afirmar.
    
    Restricciones:
    - Puedes usar lenguaje simple, pero no excedas el alcance documental.
    - No conviertas una consulta conceptual en procedimiento si el usuario no lo pidió.
    """

    if query_intent == "warranty":
        return grounding_policy + """
    #### POLÍTICA PARA GARANTÍAS
    
    Objetivo:
    Orientar trámites de garantía sin inventar SLA, proveedores, causales, RMA ni responsables no documentados.
    
    La sección Respuesta debe usar exactamente esta estructura:
    
    ### Alcance del trámite
    Explica qué cubre el documento o proceso recuperado.
    
    ### Información requerida
    Lista datos, evidencias o condiciones solicitadas por las fuentes.
    Si la documentación no especifica datos requeridos, indícalo claramente.
    
    ### Pasos documentados
    Lista únicamente los pasos presentes en la documentación.
    No completes pasos faltantes con supuestos.
    
    ### Cuándo validar o escalar
    Indica cuándo validar con proveedor, responsable interno o nivel superior si la fuente no define el flujo completo.
    
    Restricciones:
    - No uses el formato de troubleshooting para consultas de garantía.
    - No uses los encabezados "Diagnóstico documental", "Validaciones iniciales", "Acciones recomendadas" ni "Cuándo escalar", salvo que el usuario haya planteado explícitamente un incidente de troubleshooting.
    - No mezcles mantenimiento preventivo, configuración, operación de impresión o troubleshooting con garantía, salvo que la fuente lo conecte explícitamente.
    - No inventes tiempos de atención, causales, formatos, SLA, RMA ni responsables.
    """

    if query_intent == "escalation":
        return grounding_policy + """
    #### POLÍTICA PARA ESCALAMIENTO
    
    Objetivo:
    Ayudar a estructurar información para escalamiento técnico sin inventar diagnóstico.
    
    La sección Respuesta debe usar esta estructura:
    
    ### Información mínima para escalar
    Resume los datos necesarios del caso: software, síntoma, acciones realizadas, equipo, usuario, ubicación, impacto y evidencia.
    
    ### Evidencia recomendada
    Indica evidencias útiles según la documentación o el contexto disponible.
    
    ### Resumen sugerido
    Construye un resumen claro y accionable si hay datos suficientes.
    
    ### Campos faltantes
    Pide solo la información que falte.
    No vuelvas a pedir datos que el usuario ya entregó.
    
    Restricciones:
    - No inventes causa raíz.
    - No inventes prioridad o severidad si no hay datos de impacto.
    - Si no hay fuente documental suficiente, aclara que el resumen se basa en la información entregada por el usuario.
    """

    if query_intent == "architecture":
        return grounding_policy + """
    #### POLÍTICA PARA ARQUITECTURA
    
    Objetivo:
    Explicar arquitectura, componentes, integraciones o flujos técnicos de forma trazable.
    
    La sección Respuesta debe usar esta estructura:
    
    ### Componentes identificados
    Lista componentes explícitamente documentados.
    
    ### Flujo o interacción
    Describe cómo interactúan solo si la documentación lo soporta.
    
    ### Dependencias o requisitos
    Incluye dependencias técnicas documentadas.
    
    ### Límites de la documentación
    Indica puntos no cubiertos por las fuentes.
    
    Restricciones:
    - No inventes diagramas, componentes, protocolos o dependencias.
    - No mezcles arquitectura con procedimiento salvo que el usuario lo pida.
    """

    return grounding_policy + """
    #### POLÍTICA GENERAL DE RESPUESTA
    
    Objetivo:
    Responder de forma útil, conservadora y trazable.
    
    La sección Respuesta debe:
    - Contestar la pregunta del usuario con base en las fuentes disponibles.
    - Explicar límites si el soporte documental es parcial.
    - Evitar afirmaciones no respaldadas.
    - Recomendar validación o escalamiento cuando la documentación no sea suficiente.
    """

def build_response_format_contract(query_intent: str) -> str:
    """
    Defines the exact visible response structure expected for each query intent.
    This is product-agnostic and should apply across all supported domains.
    """

    if query_intent == "troubleshooting":
        return """
#### CONTRATO DE FORMATO PARA TROUBLESHOOTING

La sección Respuesta debe usar exactamente estos encabezados Markdown:

### Diagnóstico documental
Explica qué permite concluir la documentación y qué no permite concluir.

### Validaciones iniciales
Lista solo validaciones soportadas por la documentación recuperada.

### Acciones recomendadas
Lista acciones N1 soportadas por las fuentes. Si no hay procedimiento documentado, dilo claramente.

### Cuándo escalar
Indica cuándo escalar y qué evidencia recopilar.

No uses referencias internas como [Chunk 1], [Chunk 2] o similares.
"""

    if query_intent == "requirements":
        return """
#### CONTRATO DE FORMATO PARA REQUERIMIENTOS

La sección Respuesta debe usar únicamente las categorías que estén documentadas:

### Prerrequisitos del entorno
### Sistemas operativos compatibles
### Plataformas de virtualización compatibles
### Requisitos mínimos de hardware
### Requisitos de red / seguridad
### Límites o notas

No conviertas la respuesta en pasos de instalación.
No uses referencias internas como [Chunk 1], [Chunk 2] o similares.
"""

    if query_intent == "warranty":
        return """
#### CONTRATO DE FORMATO PARA GARANTÍAS

La sección Respuesta debe usar exactamente estos encabezados Markdown:

### Alcance del trámite
Explica qué cubre el documento o proceso recuperado.

### Información requerida
Lista la información, condiciones o datos requeridos por la fuente. Si la fuente no los especifica, dilo.

### Pasos documentados
Lista solo los pasos explícitos en la documentación.

### Cuándo validar o escalar
Indica cuándo validar con proveedor, responsable interno o nivel superior si la fuente no define el flujo completo.

No uses formato de troubleshooting.
No uses encabezados como "Diagnóstico documental", "Validaciones iniciales", "Acciones recomendadas" o "Cuándo escalar" para consultas de garantía.
No uses referencias internas como [Chunk 1], [Chunk 2] o similares.
"""

    if query_intent == "procedural":
        return """
#### CONTRATO DE FORMATO PARA PROCEDIMIENTOS

La sección Respuesta debe usar exactamente estos encabezados Markdown:

### Objetivo del procedimiento
### Pasos soportados por la documentación
### Validaciones posteriores
### Precauciones o límites

No inventes pasos faltantes.
No uses referencias internas como [Chunk 1], [Chunk 2] o similares.
"""

    if query_intent == "conceptual":
        return """
#### CONTRATO DE FORMATO PARA CONSULTAS CONCEPTUALES

La sección Respuesta debe usar estos encabezados cuando aplique:

### Definición
### Para qué sirve
### Componentes o funciones principales
### Límites según documentación disponible

No conviertas una consulta conceptual en procedimiento.
No uses referencias internas como [Chunk 1], [Chunk 2] o similares.
"""

    if query_intent == "escalation":
        return """
#### CONTRATO DE FORMATO PARA ESCALAMIENTO

La sección Respuesta debe usar exactamente estos encabezados Markdown:

### Información mínima para escalar
### Evidencia recomendada
### Resumen sugerido
### Campos faltantes

No inventes diagnóstico, prioridad ni severidad.
No vuelvas a pedir datos ya entregados por el usuario.
No uses referencias internas como [Chunk 1], [Chunk 2] o similares.
"""

    return """
#### CONTRATO DE FORMATO GENERAL

La sección Respuesta debe ser clara, útil y trazable.
Usa encabezados Markdown cuando ayuden a la comprensión.
No uses referencias internas como [Chunk 1], [Chunk 2] o similares.
"""
    

def build_rag_messages(
    user_query: str,
    retrieved_context: str,
    memory_text: str,
    support_level: str = "strong",
    allow_general_fallback: bool = False,
    real_source_labels: list[str] | None = None,
    hard_anchor: bool = False,
    strong_entity_match: bool = False,
):
    real_source_labels = real_source_labels or []
    source_block = build_source_block(real_source_labels)
    query_intent = classify_query_intent(user_query)
    has_sources = bool(real_source_labels)

    intent_instruction = build_intent_instruction(
        query_intent=query_intent,
        support_level=support_level,
        has_sources=has_sources,
        hard_anchor=hard_anchor,
        strong_entity_match=strong_entity_match,
    )
    response_format_contract = build_response_format_contract(query_intent)

    if allow_general_fallback:
        fallback_instruction = (
            "Puedes complementar de forma prudente con orientación general solo si la pregunta es de bajo riesgo "
            "y el contexto documental es parcial. No expliques al usuario el proceso interno."
        )
    else:
        fallback_instruction = (
            "Debes basar la respuesta principalmente en la información documental disponible. "
            "Si la información no es suficiente para responder con precisión, no inventes pasos críticos."
        )

    user_content = f"""
### MEMORIA CORTA DE LA CONVERSACIÓN
{memory_text}

### INFORMACIÓN DOCUMENTAL DISPONIBLE
{retrieved_context}

### FUENTES DISPONIBLES PARA CITAR
{source_block}

### PREGUNTA DEL USUARIO
{user_query}

### INTENCIÓN DETECTADA
{query_intent}

### NIVEL DE SOPORTE DOCUMENTAL
{support_level}

### POLÍTICA DE RESPUESTA POR INTENCIÓN
{intent_instruction}

### CONTRATO DE FORMATO VISIBLE
{response_format_contract}

### FORMATO DE RESPUESTA OBLIGATORIO
Debes responder siempre con estas dos secciones principales, en este orden:

Respuesta:
- Usa encabezados Markdown con "###" dentro de la sección Respuesta, según el contrato de formato visible.
- No uses encabezados como bullets.
- No escribas encabezados y contenido en la misma línea.
- Cada encabezado debe tener su propio párrafo.
- Usa únicamente el formato indicado por la intención detectada.
- No mezcles formatos entre intenciones.
- No uses referencias internas como [Chunk 1], [Chunk 2], etc.
- No agregues causas, validaciones ni acciones que no estén soportadas por la información documental disponible.
- Si una recomendación no está explícitamente documentada, no la incluyas.

Fuente(s):
- Incluye únicamente fuentes de la lista de fuentes disponibles para citar.
- No inventes fuentes.
- No cites chunks internos.
- Si no hay fuentes suficientes, escribe:
  - Base de conocimiento actual sin coincidencias documentales suficientes

### REGLAS DE ESTILO
- Responde en español.
- Usa tono profesional, claro y orientado a soporte N1.
- No expliques tu proceso interno.
- No menciones contexto recuperado, RAG, fallback, chunks, embeddings ni modelo.
- No inventes nombres de fuente.
- No cites "Documentación oficial de ..." si no aparece exactamente en la lista de fuentes disponibles.
- Si hace falta advertir algo importante, añade solo una línea final como: Aviso: ...

### INSTRUCCIÓN ADICIONAL
{fallback_instruction}
"""

    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]
    
def clean_user_facing_answer(answer: str) -> str:
    text = answer.strip()
    text = re.sub(r"^\s*nota\s*:\s*", "Aviso: ", text, flags=re.IGNORECASE | re.MULTILINE)
    text = re.sub(r"^\s*limitaci[oó]n\s*:\s*", "Aviso: ", text, flags=re.IGNORECASE | re.MULTILINE)
    text = re.sub(r"\n{3,}", "\n\n", text)

    lines = [line.rstrip() for line in text.splitlines()]
    cleaned = []
    avisos = []

    for line in lines:
        stripped = line.strip()
        if not stripped:
            cleaned.append("")
            continue
        if stripped.lower().startswith("aviso:"):
            if stripped not in avisos:
                avisos.append(stripped)
        else:
            cleaned.append(line)

    final = "\n".join(cleaned).strip()
    if avisos:
        final += "\n\n" + "\n".join(avisos)
    return re.sub(r"\n{3,}", "\n\n", final).strip()


def answer_uses_fake_generic_sources(answer: str) -> bool:
    generic_patterns = ["documentación oficial de", "documentacion oficial de", "official documentation of"]
    text = answer.lower()
    return any(pattern in text for pattern in generic_patterns)


def enforce_real_source_traceability(answer: str, real_source_labels: list[str], support_info: dict, user_query: str) -> str:
    text = answer.strip()
    aviso_lines = [
        line.strip() for line in text.splitlines() if line.strip().lower().startswith("aviso:")
    ]
    split_parts = re.split(r"\n\s*fuente\(s\)\s*:\s*", text, flags=re.IGNORECASE)
    response_part = split_parts[0].strip()

    if support_info["support_level"] in {"weak", "none"}:
        source_block = "Fuente(s):\n- Base de conocimiento actual sin coincidencias documentales suficientes"
    else:
        source_block = "Fuente(s):\n" + build_source_block(real_source_labels)

    final_text = f"{response_part}\n\n{source_block}"
    if aviso_lines:
        seen = []
        for a in aviso_lines:
            if a not in seen:
                seen.append(a)
        final_text += "\n\n" + "\n".join(seen)
    return final_text.strip()


def build_requirements_no_support_answer(user_query: str) -> str:
    topic_match = re.search(r"(?:Tema referido:|Producto o herramienta referida:)\s*(.+)$", user_query, flags=re.IGNORECASE)
    subject = topic_match.group(1).strip() if topic_match else "el producto o componente consultado"
    return f"""Respuesta:
La documentación disponible no especifica requisitos técnicos suficientemente claros para {subject}. No es posible confirmar hardware mínimo, sistemas operativos compatibles, dependencias, permisos o requisitos de red con las fuentes actuales.

Fuente(s):
- Base de conocimiento actual sin coincidencias documentales suficientes

Aviso: La ausencia de requisitos documentados no implica que no existan; requiere una fuente técnica específica del producto o componente."""


def build_conservative_no_support_answer(user_query: str, real_source_labels: list[str] | None = None) -> str:
    source_block = "- Base de conocimiento actual sin coincidencias documentales suficientes"
    if real_source_labels:
        source_block = "\n".join(f"- {label}" for label in real_source_labels[:2])
    return f"""Respuesta:
No encontré información suficientemente específica y confiable en la base de conocimiento actual para responder con precisión a esta consulta. Si se trata de una tarea operativa o de configuración, te recomiendo validar con documentación adicional o escalar el caso si el impacto lo requiere.

Fuente(s):
{source_block}

Aviso: La base documental actual no ofrece soporte suficientemente claro para dar un procedimiento preciso."""


# -----------------------------------------------------------------------------
# Requirements answer builder
# -----------------------------------------------------------------------------
def build_combined_requirement_text(docs: list) -> str:
    def page_num(doc):
        try:
            return int(doc.metadata.get("page", 999))
        except Exception:
            return 999

    docs_sorted = sorted(docs, key=page_num)
    parts = []
    for doc in docs_sorted:
        content = getattr(doc, "page_content", None)
        if content:
            parts.append(str(content))

    text = "\n".join(parts)
    text = text.replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def build_requirements_answer_from_docs(user_query: str, docs: list) -> str:
    """
    Build a grounded and complete answer for requirements queries
    using deterministic extraction from the retrieved PDF text.
    """
    text = build_combined_requirement_text(docs)
    source_labels = build_real_source_labels(docs)

    normalized = text.replace("\r", "\n")
    normalized = re.sub(r"[ \t]+", " ", normalized)
    normalized = re.sub(r"\n{3,}", "\n\n", normalized)

    def normalize_item(value: str) -> str:
        value = " ".join(value.strip().split())
        return value.strip(" ;,.-")

    def extract_block(start_patterns: list[str], end_patterns: list[str]) -> str:
        lower_text = normalized.lower()

        start_pos = None
        chosen_marker = None
        for pattern in start_patterns:
            pos = lower_text.find(pattern.lower())
            if pos != -1:
                if start_pos is None or pos < start_pos:
                    start_pos = pos
                    chosen_marker = pattern

        if start_pos is None:
            return ""

        start_pos += len(chosen_marker)

        end_pos = len(normalized)
        for pattern in end_patterns:
            pos = lower_text.find(pattern.lower(), start_pos)
            if pos != -1 and pos < end_pos:
                end_pos = pos

        return normalized[start_pos:end_pos].strip()

    def extract_bullets_regex(block: str) -> list[str]:
        """Extract bullet items robustly, preserving wrapped bullet lines."""
        if not block:
            return []

        matches = re.findall(
            r"(?:^|\n)\s*[•\-]\s*(.+?)(?=(?:\n\s*[•\-]\s)|\Z)",
            block,
            flags=re.DOTALL,
        )

        items = []
        for item in matches:
            item = normalize_item(item)
            noise_patterns = [
                "HP SDS MANAGER SYSTEM REQUIREMENTS",
                "HP SDS – SYSTEM REQUIREMENTS",
                "© EKM",
                "COMPANY NUMBER",
            ]
            low = item.lower()
            if any(noise.lower() in low for noise in noise_patterns):
                continue
            if item and item not in items:
                items.append(item)
        return items

    def join_items_full(items: list[str], max_items: int = 8) -> str:
        cleaned = []
        for item in items[:max_items]:
            value = " ".join(item.split()).strip()
            if value and value not in cleaned:
                cleaned.append(value)
        return "; ".join(cleaned)

    environment_block = extract_block(
        start_patterns=[
            "Los siguientes son los requisitos operativos requeridos",
            "requisitos operativos requeridos para un monitor HP SDS",
        ],
        end_patterns=[
            "Los sistemas operativos soportados",
            "Plataformas de virtualización compatibles",
            "Hardware",
        ],
    )

    os_block = extract_block(
        start_patterns=[
            "Los sistemas operativos soportados son los siguientes",
            "Los sistemas operativos soportados",
        ],
        end_patterns=[
            "Plataformas de virtualización compatibles",
            "Hardware",
        ],
    )

    hardware_block = extract_block(
        start_patterns=[
            "Los requisitos mínimos de hardware para HP SDS Monitor",
            "Los requisitos mínimos de hardware",
            "Hardware",
        ],
        end_patterns=[
            "Preparando el entorno",
            "NOTA:",
        ],
    )

    network_block = extract_block(
        start_patterns=[
            "Para que HP SDS Monitor funcione, se deben cumplir los siguientes criterios",
            "Preparando el entorno",
        ],
        end_patterns=[
            "VeriSign Class 3 Public",
            "1NOTA:",
            "2NOTA:",
        ],
    )

    environment_items = extract_bullets_regex(environment_block)
    os_items = extract_bullets_regex(os_block)
    hardware_items = extract_bullets_regex(hardware_block)
    network_items = extract_bullets_regex(network_block)

    # Deterministic fallbacks for this specific document
    if not environment_items:
        environment_items = []
        for pattern in [
            r"•\s*\.NET\s*4\.5",
            r"•\s*Access to the Internet or HTTP proxy server",
            r"•\s*IPv4 network",
        ]:
            match = re.search(pattern, normalized, flags=re.IGNORECASE)
            if match:
                environment_items.append(normalize_item(match.group(0).lstrip("•- ").strip()))

    if not os_items:
        os_candidates = re.findall(
            r"(Windows Server 2008 R2|Windows Server 2008|Windows Server 2012|Windows Server 2016|Windows Server 2019 y por encima|Windows 7|Windows 8|Windows 10)",
            normalized,
            flags=re.IGNORECASE,
        )
        os_items = []
        for item in os_candidates:
            item = normalize_item(item)
            if item and item not in os_items:
                os_items.append(item)

    cleaned_hw = []
    for item in hardware_items:
        if "NOTA:" in item:
            item = item.split("NOTA:")[0].strip()
        item = normalize_item(item)
        if item and item not in cleaned_hw:
            cleaned_hw.append(item)
    hardware_items = cleaned_hw

    if not hardware_items:
        hardware_items = []
        for pattern in [
            r"32-bit \(x86\) or 64-bit \(x64\) Processor: 1 GHz \(gigahertz\)",
            r"Memory: 1 GB \(gigabyte\) RAM",
            r"Espacio necesario para la instalación: mínimo 200 MB de espacio libre en disco",
        ]:
            match = re.search(pattern, normalized, flags=re.IGNORECASE)
            if match:
                hardware_items.append(normalize_item(match.group(0)))

    if not network_items:
        network_items = []
        fallback_network_patterns = [
            r"Su infraestructura de red debe permitir el enrutamiento del tráfico ICMP Echo \(\"Ping\"\) entre JAMC y las impresoras.*?(?=•|$)",
            r"Su infraestructura de servidor de seguridad de Internet/proxy HTTP debe permitir la comunicación.*?(?=•|$)",
            r"Cuando se usan credenciales de proxy HTTP, la autenticación de acceso básico debe estar habilitada.*?(?=•|$)",
            r"Las credenciales de la cuenta de servicio.*?(?=•|$)",
        ]
        for pattern in fallback_network_patterns:
            match = re.search(pattern, normalized, flags=re.IGNORECASE | re.DOTALL)
            if match:
                value = normalize_item(match.group(0))
                if value and value not in network_items:
                    network_items.append(value)

    virtualization_value = ""
    virt_match = re.search(
        r"Plataformas de virtualización compatibles[:\s]+([^\n]+)",
        normalized,
        flags=re.IGNORECASE,
    )
    if virt_match:
        virtualization_value = normalize_item(virt_match.group(1))

    note_value = ""
    note_match = re.search(
        r"NOTA:\s*(Se admiten los sistemas Windows con varias NIC.*?)(?:\n|$)",
        normalized,
        flags=re.IGNORECASE,
    )
    if note_match:
        note_value = normalize_item(note_match.group(1))

    bullets = []
    if environment_items:
        bullets.append(f"- **Prerrequisitos del entorno:** {join_items_full(environment_items, max_items=4)}")
    if os_items:
        bullets.append(f"- **Sistemas operativos compatibles:** {join_items_full(os_items, max_items=8)}")
    if virtualization_value:
        bullets.append(f"- **Plataformas de virtualización compatibles:** {virtualization_value}")
    if hardware_items:
        bullets.append(f"- **Requisitos mínimos de hardware:** {join_items_full(hardware_items, max_items=4)}")
    if network_items:
        bullets.append(f"- **Requisitos de red / seguridad:** {join_items_full(network_items, max_items=4)}")

    if not bullets:
        return build_conservative_no_support_answer(user_query=user_query, real_source_labels=source_labels)

    source_heading = "Fuente principal:" if len(source_labels) == 1 else "Fuentes principales:"
    source_block = source_heading + "\n" + "\n".join(f"- {label}" for label in source_labels[:2])
    aviso = f"\n\nAviso: {note_value}" if note_value else ""

    return f"""Respuesta:
Con base en la documentación disponible, estos son los requisitos relevantes identificados para esta consulta:

{chr(10).join(bullets)}

{source_block}{aviso}"""


def compact_source_heading(source_labels: list[str]) -> str:
    return "Fuente principal:" if len(source_labels) == 1 else "Fuentes principales:"


def field_accepts_no_value(field_name: str) -> bool:
    return field_name in {"software_version", "contract_client_location", "evidence", "impact_type"}

def build_llm_unavailable_answer(error: Exception | None = None) -> str:
    """
    User-facing response when the LLM provider is not available.
    Avoid exposing internal stack traces or secrets.
    """
    return (
        "Respuesta:\n"
        "- En este momento el servicio de generación de respuestas no está disponible. "
        "La base documental y el retrieval pueden estar funcionando, pero el modelo de lenguaje "
        "configurado no pudo responder.\n\n"
        "Fuente(s):\n"
        "- Base de conocimiento actual sin respuesta generada por el modelo.\n\n"
        "Aviso: Revisa la configuración del modelo o proveedor de inferencia antes de intentar nuevamente."
    )
def answer_is_sources_only(answer: str) -> bool:
        text = answer.strip().lower()
    
        if not text:
            return True
    
        has_response = "respuesta:" in text
        has_sources = "fuente" in text
    
        # If it has sources but no real response section, treat as bad generation.
        if has_sources and not has_response:
            return True
    
        # Very short answers are usually malformed.
        if len(text) < 80:
            return True
    
        return False
def serialize_llm_response_for_debug(response, max_chars: int = 3000) -> str:
    """
    Convert the raw LLM response object into a safe debug string.
    This helps diagnose provider-specific response formats.
    """
    try:
        if hasattr(response, "model_dump_json"):
            return response.model_dump_json(indent=2)[:max_chars]
    except Exception:
        pass

    try:
        if hasattr(response, "model_dump"):
            return json.dumps(response.model_dump(), ensure_ascii=False, indent=2)[:max_chars]
    except Exception:
        pass

    try:
        if isinstance(response, dict):
            return json.dumps(response, ensure_ascii=False, indent=2)[:max_chars]
    except Exception:
        pass

    try:
        return repr(response)[:max_chars]
    except Exception:
        return "Unable to serialize LLM response."


def extract_llm_answer_text(response) -> str:
    """
    Extract text from different possible chat completion response shapes.
    Some providers may return content in slightly different locations.
    """
    try:
        choice = response.choices[0]
    except Exception:
        return ""

    # Object-style response: choice.message.content
    try:
        message = choice.message
        content = getattr(message, "content", None)

        if isinstance(content, str):
            return content.strip()

        if isinstance(content, list):
            parts = []
            for item in content:
                if isinstance(item, dict):
                    text_value = item.get("text") or item.get("content")
                    if text_value:
                        parts.append(str(text_value))
                else:
                    text_value = getattr(item, "text", None) or getattr(item, "content", None)
                    if text_value:
                        parts.append(str(text_value))
            return "\n".join(parts).strip()

        # Some providers may expose reasoning or alternative fields.
        for attr_name in ["reasoning_content", "text", "generated_text"]:
            value = getattr(message, attr_name, None)
            if isinstance(value, str) and value.strip():
                return value.strip()

    except Exception:
        pass

    # Dict-style response.
    try:
        if isinstance(choice, dict):
            message = choice.get("message", {})
            content = message.get("content")

            if isinstance(content, str):
                return content.strip()

            if isinstance(content, list):
                parts = []
                for item in content:
                    if isinstance(item, dict):
                        text_value = item.get("text") or item.get("content")
                        if text_value:
                            parts.append(str(text_value))
                return "\n".join(parts).strip()

            for key in ["reasoning_content", "text", "generated_text"]:
                value = message.get(key) or choice.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
    except Exception:
        pass

    return ""
    

def get_effective_disable_thinking() -> bool:
    value = st.secrets.get("HF_DISABLE_THINKING", True)

    if isinstance(value, bool):
        return value

    return str(value).strip().lower() in {"1", "true", "yes", "y", "si", "sí"}


def prepare_messages_for_no_think(messages: list[dict]) -> list:
    """Add a direct-answer instruction to reduce hidden/thinking token usage
    in Qwen 3.x style models.
    """
    prepared = []

    for msg in messages:
        prepared.append(dict(msg))

    if not prepared:
        return prepared

    for idx in range(len(prepared) - 1, -1, -1):
        if prepared[idx].get("role") == "user":
            prepared[idx]["content"] = (
                str(prepared[idx].get("content", ""))
                + "\n\n"
                + "INSTRUCCIÓN DE GENERACIÓN:\n"
                + "- /no_think\n"
                + "- Responde directamente en español.\n"
                + "- No generes razonamiento interno.\n"
                + "- No dejes la respuesta vacía.\n"
                + "- Debes producir contenido visible bajo la sección Respuesta.\n"
            )
            break

    return prepared



def call_hf_chat_completion(hf_client, messages: list[dict]):
    """
    Centralized Hugging Face chat completion call.
    Adds /no_think support for Qwen-style models and a short retry for temporary provider overload.
    """
    max_tokens = get_effective_max_tokens()
    disable_thinking = get_effective_disable_thinking()

    effective_messages = prepare_messages_for_no_think(messages) if disable_thinking else messages

    call_kwargs = {
        "messages": effective_messages,
        "max_tokens": max_tokens,
        "temperature": LLM_CONFIG["temperature"],
    }

    if disable_thinking:
        call_kwargs["extra_body"] = {
            "enable_thinking": False,
            "chat_template_kwargs": {"enable_thinking": False},
        }

    last_error = None
    for attempt in range(3):
        try:
            return hf_client.chat_completion(**call_kwargs)
        except TypeError:
            call_kwargs.pop("extra_body", None)
            return hf_client.chat_completion(**call_kwargs)
        except Exception as e:
            last_error = e
            error_text = str(e).lower()
            is_busy = (
                "429" in error_text
                or "too many requests" in error_text
                or "engine_overloaded" in error_text
                or "model busy" in error_text
                or "504 gateway" in error_text
                or "gateway time-out" in error_text
            )
            if is_busy and attempt < 2:
                time.sleep(2 * (attempt + 1))
                continue
            raise

    raise last_error
def get_effective_max_tokens() -> int:
    """
    Resolve max_tokens from Streamlit secrets first, then fallback to LLM_CONFIG.
    """
    try:
        value = st.secrets.get("HF_MAX_TOKENS", None)

        if value is not None:
            return int(value)

        return int(LLM_CONFIG.get("max_tokens", 600))

    except Exception:
        return 600


def get_effective_max_tokens_source() -> str:
    """
    Show whether max_tokens came from Streamlit secrets or config fallback.
    Useful for debugging deployment configuration.
    """
    try:
        if st.secrets.get("HF_MAX_TOKENS", None) is not None:
            return "streamlit_secrets.HF_MAX_TOKENS"
    except Exception:
        pass

    return "LLM_CONFIG.max_tokens_or_default"


def update_last_llm_diagnostics(
    llm_call_ok: bool,
    error=None,
    raw_answer: str = "",
    raw_response_debug: str = "",
    response=None,
):
    """
    Store consistent LLM diagnostics in Streamlit session state.
    This keeps debug output stable for both success and error cases.
    """
    finish_reason = None
    usage_info = None

    if response is not None:
        try:
            finish_reason = response.choices[0].finish_reason
        except Exception:
            finish_reason = None

        try:
            if hasattr(response, "usage"):
                usage_info = response.usage
                if hasattr(usage_info, "model_dump"):
                    usage_info = usage_info.model_dump()
        except Exception:
            usage_info = None

    st.session_state["last_llm_diagnostics"] = {
        "llm_call_ok": llm_call_ok,
        "model": get_effective_llm_model(),
        "provider": get_effective_hf_provider(),
        "temperature": LLM_CONFIG.get("temperature"),
        "max_tokens": get_effective_max_tokens(),
        "max_tokens_source": get_effective_max_tokens_source(),
        "disable_thinking": get_effective_disable_thinking(),
        "finish_reason": finish_reason,
        "usage": usage_info,
        "raw_answer_length": len(raw_answer or ""),
        "raw_answer_preview": (raw_answer or "")[:1000],
        "has_respuesta_section": "respuesta:" in (raw_answer or "").lower(),
        "has_fuentes_section": "fuente" in (raw_answer or "").lower(),
        "raw_response_debug": raw_response_debug,
        "error": str(error) if error else None,
        "timestamp": datetime.now().isoformat(),
    }

def remove_internal_chunk_references(answer: str) -> str:
    """
    Remove internal retrieval references that should not be visible to end users.
    The final answer should cite only real source labels in Fuente(s).
    """
    text = answer

    text = re.sub(r"\s*\[Chunk\s*\d+\]", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*\(Chunk\s*\d+\)", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*Chunk\s*\d+\s*", " ", text, flags=re.IGNORECASE)

    # Clean extra spaces before punctuation.
    text = re.sub(r"\s+([,.;:])", r"\1", text)

    # Normalize excessive blank lines.
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()
REQUIREMENT_IDENTITY_TERMS = [
    "requirements", "requirement", "requisitos", "requerimientos", "prerrequisitos",
    "system requirements", "minimum requirements",
]
REQUIREMENT_TECHNICAL_TERMS = [
    "operating system", "sistema operativo", "windows server", "windows 10", "windows 11",
    "cpu", "processor", "procesador", "memory", "memoria", "ram", "disk", "disco",
    "port", "ports", "puerto", "puertos", "firewall", "network", "red", "certificate",
    "certificado", "permission", "permissions", "permisos", "virtualization", "virtualización",
    "vmware", "hyper-v", "hyperv", "dependency", "dependencies", "dependencia", "dependencias",
]


def doc_supports_requirements_query(user_query: str, doc) -> bool:
    metadata = doc.metadata or {}
    title = str(metadata.get("title", "")).lower()
    source = str(metadata.get("source", "")).lower()
    component = str(metadata.get("component", "")).lower()
    family = str(metadata.get("document_family", "")).lower()
    content = str(doc.page_content or "").lower()
    identity = f"{title} {source} {component} {family}"

    identity_match = any(term in identity for term in REQUIREMENT_IDENTITY_TERMS)
    technical_hits = sum(1 for term in REQUIREMENT_TECHNICAL_TERMS if term in content[:2600])

    topic_tokens = semantic_identity_tokens(user_query)
    identity_tokens = semantic_identity_tokens(identity + " " + content[:1400])
    component_tokens = topic_tokens & {light_stem(value) for value in SUBJECT_HINT_WORDS}
    if component_tokens and not component_tokens.issubset(identity_tokens):
        return False

    return identity_match or technical_hits >= 3


def select_docs_for_llm_context(user_query: str, docs: list, query_intent: str) -> list:
    """Select a small, intent-aligned context without filling arbitrary source slots."""
    if not docs:
        return []

    candidate_docs = list(docs)
    if query_intent == "requirements":
        candidate_docs = [doc for doc in candidate_docs if doc_supports_requirements_query(user_query, doc)]
        if not candidate_docs:
            return []

    max_docs_by_intent = {
        "troubleshooting": 4, "procedural": 3, "requirements": 3, "conceptual": 3,
        "warranty": 3, "architecture": 4, "escalation": 3, "default": 3,
    }
    max_docs = max_docs_by_intent.get(query_intent, 3)

    scored = []
    for position, doc in enumerate(candidate_docs):
        alignment = document_identity_alignment(user_query, doc.metadata or {}, doc.page_content or "")
        base_order_score = max(0, 20 - position)
        score = base_order_score + alignment["overlap_count"] * (5 if query_intent == "procedural" else 2)
        scored.append((doc, score, position, alignment))
    scored.sort(key=lambda item: (item[1], -item[2]), reverse=True)

    # Universal procedural rule: when the lead title/source strongly represents
    # the requested action/object and clearly dominates, do not pad the context.
    if query_intent == "procedural" and scored:
        lead = scored[0][3]
        second = scored[1][3] if len(scored) > 1 else {"overlap_count": 0, "ratio": 0.0}
        if (
            lead["overlap_count"] >= 2
            and lead["ratio"] >= 0.5
            and (
                lead["overlap_count"] >= second["overlap_count"] + 1
                or lead["ratio"] >= second["ratio"] + 0.25
            )
        ):
            max_docs = 1
        elif lead["overlap_count"] >= 2 and lead["ratio"] >= 0.4:
            max_docs = min(max_docs, 2)

    selected = []
    seen_sources = set()
    for doc, _, _, _ in scored:
        metadata = doc.metadata or {}
        source_key = str(
            metadata.get("source") or metadata.get("source_url")
            or metadata.get("canonical_url") or metadata.get("title")
        )
        if source_key in seen_sources:
            continue
        seen_sources.add(source_key)
        selected.append(doc)
        if len(selected) >= max_docs:
            break
    return selected


def build_context_from_docs(docs: list, max_chars_per_doc: int = 2600) -> str:
    """Build compact model context from already-selected documents."""
    context_blocks = []
    for index, doc in enumerate(docs, start=1):
        source_label = format_source_label(doc.metadata or {})
        content = str(doc.page_content or "").strip()[:max_chars_per_doc]
        context_blocks.append(f"[Chunk {index}] Source: {source_label}\n{content}")
    return "\n\n".join(context_blocks)


# -----------------------------------------------------------------------------
# Downloadable PDF source metadata
# -----------------------------------------------------------------------------
PDF_LIBRARY_ROOT = Path("data/knowledge_base_pdfs")
MAX_RESPONSE_PDF_SOURCES = 3
MAX_INLINE_PDF_SIZE_BYTES = 15 * 1024 * 1024
DOWNLOADABLE_PDF_VENDORS = {"hp", "gav"}
BLOCKED_PDF_VENDORS = {"arus_internal"}


def resolve_pdf_relative_path(source_value: str) -> Path | None:
    """Map build-time PDF paths to data/knowledge_base_pdfs safely."""
    source_text = str(source_value or "").replace("\\", "/").strip()
    if not source_text.lower().endswith(".pdf"):
        return None
    marker = "knowledge_base_pdfs/"
    lower = source_text.lower()
    marker_index = lower.find(marker)
    if marker_index >= 0:
        relative_text = source_text[marker_index + len(marker):]
    else:
        relative_text = Path(source_text).name
    relative = Path(relative_text)
    if relative.is_absolute() or ".." in relative.parts:
        return None
    return relative


def build_response_pdf_sources(docs: list) -> list[dict[str, Any]]:
    """Return lightweight metadata for up to three downloadable HP/GAV PDFs."""
    sources = []
    seen = set()
    root = PDF_LIBRARY_ROOT.resolve()

    for doc in docs or []:
        metadata = doc.metadata or {}
        vendor = str(metadata.get("vendor", "")).lower().strip()
        if vendor in BLOCKED_PDF_VENDORS or vendor not in DOWNLOADABLE_PDF_VENDORS:
            continue

        source_value = get_best_source_value(metadata)
        relative = resolve_pdf_relative_path(source_value)
        if relative is None:
            continue

        candidate = (PDF_LIBRARY_ROOT / relative).resolve()
        try:
            candidate.relative_to(root)
        except ValueError:
            continue

        key = str(relative).lower()
        if key in seen:
            continue
        seen.add(key)

        exists = candidate.is_file()
        size_bytes = candidate.stat().st_size if exists else None
        page = metadata.get("page_label", metadata.get("page"))
        pages = [str(page)] if page is not None else []
        allowed = bool(exists and size_bytes is not None and size_bytes <= MAX_INLINE_PDF_SIZE_BYTES)

        sources.append({
            "title": str(metadata.get("title") or relative.stem),
            "file_name": relative.name,
            "relative_path": relative.as_posix(),
            "page_labels": pages,
            "vendor": vendor,
            "product": metadata.get("product"),
            "size_bytes": size_bytes,
            "exists": exists,
            "download_allowed": allowed,
            "status": "available" if allowed else ("too_large" if exists else "missing"),
        })
        if len(sources) >= MAX_RESPONSE_PDF_SOURCES:
            break

    return sources


def clear_last_response_pdf_sources():
    st.session_state["last_response_pdf_sources"] = []


# -----------------------------------------------------------------------------
# Generation
# -----------------------------------------------------------------------------

def generate_answer_with_rag(user_query: str, memory):
    hf_client = get_hf_client()

    turn_start = time.perf_counter()

    if hf_client is None:
        return (
            "No fue posible generar la respuesta porque falta la configuración "
            "del servicio de inferencia."
        )

    retrieved_context, retrieved_docs = retrieve_context(
        user_query,
        top_k=CONFIG["retrieval_top_k"],
    )

    support_info = assess_retrieval_support(user_query, retrieved_docs)
    query_intent = classify_query_intent(user_query)

    llm_context_docs = select_docs_for_llm_context(
        user_query=user_query,
        docs=retrieved_docs,
        query_intent=query_intent,
    )
    retrieved_context = build_context_from_docs(llm_context_docs)
    real_source_labels = build_real_source_labels(llm_context_docs)

    st.session_state["last_llm_context_stats"] = {
        "retrieved_docs": len(retrieved_docs),
        "llm_context_docs": len(llm_context_docs),
        "llm_context_chars": len(retrieved_context),
    }
    st.session_state["last_response_pdf_sources"] = build_response_pdf_sources(llm_context_docs)
    allow_general_fallback = should_use_general_fallback(user_query, support_info)
    hard_anchor = has_hard_documentary_anchor(user_query, retrieved_docs, query_intent)
    strong_entity_match = has_strong_entity_document_match(user_query, retrieved_docs)
    strong_document_identity_match = has_document_identity_anchor(user_query, retrieved_docs)
    if strong_document_identity_match:
        strong_entity_match = True

    if query_intent == "requirements":
        if (
            not llm_context_docs
            or (
                support_info["support_level"] in {"weak", "none"}
                and not hard_anchor
                and not strong_entity_match
            )
        ):
            answer = build_requirements_no_support_answer(user_query)

            latency_seconds = round(time.perf_counter() - turn_start, 3)

            record = build_turn_observability_record(
                user_message=user_query,
                route_type="conservative_no_support",
                query_intent=query_intent,
                support_info=support_info,
                hard_anchor=hard_anchor,
                strong_entity_match=strong_entity_match,
                retrieved_docs=retrieved_docs,
                real_source_labels=real_source_labels,
                llm_diagnostics=st.session_state.get("last_llm_diagnostics", {}),
                latency_seconds=latency_seconds,
                fallback_used=True,
            )
            update_last_turn_diagnostics(record)
            append_turn_observability_record(record)

            memory.add_turn(user_query, answer)
            return answer

    if query_intent in {"procedural", "troubleshooting"}:
        if (
            support_info["support_level"] in {"weak", "none"}
            and not hard_anchor
            and not strong_entity_match
        ):
            answer = build_conservative_no_support_answer(
                user_query=user_query,
                real_source_labels=real_source_labels,
            )

            latency_seconds = round(time.perf_counter() - turn_start, 3)

            record = build_turn_observability_record(
                user_message=user_query,
                route_type="conservative_no_support",
                query_intent=query_intent,
                support_info=support_info,
                hard_anchor=hard_anchor,
                strong_entity_match=strong_entity_match,
                retrieved_docs=retrieved_docs,
                real_source_labels=real_source_labels,
                llm_diagnostics=st.session_state.get("last_llm_diagnostics", {}),
                latency_seconds=latency_seconds,
                fallback_used=True,
            )
            update_last_turn_diagnostics(record)
            append_turn_observability_record(record)
            
            memory.add_turn(user_query, answer)
            return answer

    if (
        support_info["support_level"] in {"weak", "none"}
        and query_intent not in {"conceptual", "requirements"}
        and not strong_entity_match
    ):
        answer = build_conservative_no_support_answer(
            user_query=user_query,
            real_source_labels=real_source_labels,
        )

        latency_seconds = round(time.perf_counter() - turn_start, 3)

        record = build_turn_observability_record(
            user_message=user_query,
            route_type="conservative_no_support",
            query_intent=query_intent,
            support_info=support_info,
            hard_anchor=hard_anchor,
            strong_entity_match=strong_entity_match,
            retrieved_docs=retrieved_docs,
            real_source_labels=real_source_labels,
            llm_diagnostics=st.session_state.get("last_llm_diagnostics", {}),
            latency_seconds=latency_seconds,
            fallback_used=True,
        )
        update_last_turn_diagnostics(record)
        append_turn_observability_record(record)

        memory.add_turn(user_query, answer)
        return answer

    if should_use_memory_for_query(user_query, query_intent):
        memory_text = memory.format_history()
    else:
        memory_text = "No previous conversation."

    messages = build_rag_messages(
        user_query=user_query,
        retrieved_context=retrieved_context,
        memory_text=memory_text,
        support_level=support_info["support_level"],
        allow_general_fallback=allow_general_fallback,
        real_source_labels=real_source_labels,
        hard_anchor=hard_anchor,
        strong_entity_match=strong_entity_match,
    )

    try:
        response = call_hf_chat_completion(
            hf_client=hf_client,
            messages=messages,
        )
    except BadRequestError as e:
        update_last_llm_diagnostics(llm_call_ok=False, error=e)
        latency_seconds = round(time.perf_counter() - turn_start, 3)
        answer = build_llm_unavailable_answer(e)
        record = build_turn_observability_record(
            user_message=user_query,
            route_type="llm_error",
            query_intent=query_intent,
            support_info=support_info,
            hard_anchor=hard_anchor,
            strong_entity_match=strong_entity_match,
            retrieved_docs=retrieved_docs,
            real_source_labels=real_source_labels,
            llm_diagnostics=st.session_state.get("last_llm_diagnostics", {}),
            latency_seconds=latency_seconds,
            fallback_used=True,
            error=str(e),
        )
        update_last_turn_diagnostics(record)
        append_turn_observability_record(record)
    
        return answer
        
    except HfHubHTTPError as e:
        update_last_llm_diagnostics(llm_call_ok=False, error=e)
        latency_seconds = round(time.perf_counter() - turn_start, 3)
        answer = build_llm_unavailable_answer(e)
        record = build_turn_observability_record(
            user_message=user_query,
            route_type="llm_error",
            query_intent=query_intent,
            support_info=support_info,
            hard_anchor=hard_anchor,
            strong_entity_match=strong_entity_match,
            retrieved_docs=retrieved_docs,
            real_source_labels=real_source_labels,
            llm_diagnostics=st.session_state.get("last_llm_diagnostics", {}),
            latency_seconds=latency_seconds,
            fallback_used=True,
            error=str(e),
        )
        update_last_turn_diagnostics(record)
        append_turn_observability_record(record)
        return answer
        
    except Exception as e:
        update_last_llm_diagnostics(llm_call_ok=False, error=e)
        latency_seconds = round(time.perf_counter() - turn_start, 3)
        answer = build_llm_unavailable_answer(e)
        record = build_turn_observability_record(
            user_message=user_query,
            route_type="llm_error",
            query_intent=query_intent,
            support_info=support_info,
            hard_anchor=hard_anchor,
            strong_entity_match=strong_entity_match,
            retrieved_docs=retrieved_docs,
            real_source_labels=real_source_labels,
            llm_diagnostics=st.session_state.get("last_llm_diagnostics", {}),
            latency_seconds=latency_seconds,
            fallback_used=True,
            error=str(e),
        )
        update_last_turn_diagnostics(record)
        append_turn_observability_record(record)
        return answer

    raw_response_debug = serialize_llm_response_for_debug(response)
    answer = extract_llm_answer_text(response)
    raw_answer = answer

    update_last_llm_diagnostics(
        llm_call_ok=True,
        raw_answer=raw_answer,
        raw_response_debug=raw_response_debug,
        response=response,
    )

    answer = clean_user_facing_answer(answer)
    answer = remove_internal_chunk_references(answer)

    answer = enforce_real_source_traceability(
        answer=answer,
        real_source_labels=real_source_labels,
        support_info=support_info,
        user_query=user_query,
    )

    if answer_is_sources_only(answer):
        answer = (
            "Respuesta:\n"
            "El modelo de lenguaje respondió sin contenido útil para esta consulta. "
            "Sin embargo, sí se recuperaron fuentes documentales relacionadas. "
            "Revisa las fuentes listadas y valida el caso con documentación adicional o con el siguiente nivel de soporte si el impacto lo requiere.\n\n"
            "Fuente(s):\n"
            f"{build_source_block(real_source_labels)}\n\n"
            "Aviso: La generación del modelo fue incompleta, aunque el retrieval documental sí encontró fuentes."
        )
        st.session_state["last_llm_diagnostics"]["malformed_answer_detected"] = True
    else:
        st.session_state["last_llm_diagnostics"]["malformed_answer_detected"] = False

    latency_seconds = round(time.perf_counter() - turn_start, 3)

    record = build_turn_observability_record(
        user_message=user_query,
        route_type="rag_answer",
        query_intent=query_intent,
        support_info=support_info,
        hard_anchor=hard_anchor,
        strong_entity_match=strong_entity_match,
        retrieved_docs=retrieved_docs,
        real_source_labels=real_source_labels,
        llm_diagnostics=st.session_state.get("last_llm_diagnostics", {}),
        latency_seconds=latency_seconds,
        fallback_used=st.session_state.get(
            "last_llm_diagnostics", {}
        ).get("malformed_answer_detected", False),
    )
    update_last_turn_diagnostics(record)
    append_turn_observability_record(record)
    
    memory.add_turn(user_query, answer)
    return answer
    
# -----------------------------------------------------------------------------
# Debug helpers
# -----------------------------------------------------------------------------
def debug_query_diagnostics(user_query: str) -> dict[str, Any]:
    retrieved_context, retrieved_docs = retrieve_context(
        user_query,
        top_k=CONFIG["retrieval_top_k"],
    )

    support_info = assess_retrieval_support(user_query, retrieved_docs)
    query_intent = classify_query_intent(user_query)
    query_profile = detect_query_profile(user_query)
    hard_anchor = has_hard_documentary_anchor(
        user_query,
        retrieved_docs,
        query_intent,
    )
    real_source_labels = build_real_source_labels(retrieved_docs)

    docs_summary = []
    for doc in retrieved_docs:
        score = compute_rerank_score(user_query, doc, query_intent)
        docs_summary.append(
            {
                "title": doc.metadata.get("title"),
                "source": doc.metadata.get("source"),
                "vendor": doc.metadata.get("vendor"),
                "product": doc.metadata.get("product"),
                "component": doc.metadata.get("component"),
                "document_family": doc.metadata.get("document_family"),
                "source_group": doc.metadata.get("source_group"),
                "priority": doc.metadata.get("priority"),
                "page": doc.metadata.get("page"),
                "page_label": doc.metadata.get("page_label"),
                "rerank_score": round(score, 3),
                "content_preview": doc.page_content[:350],
            }
        )

    return {
        "query": user_query,
        "query_intent": query_intent,
        "query_profile": query_profile,
        "support_info": support_info,
        "hard_anchor": hard_anchor,
        "real_source_labels": real_source_labels,
        "retrieved_count": len(retrieved_docs),
        "retrieved_docs_summary": docs_summary,
    }


# -----------------------------------------------------------------------------
# Escalation logic
# -----------------------------------------------------------------------------
ESCALATION_TRIGGERS = [
    "quiero escalar", "necesito escalar", "deseo escalar", "escalar el caso",
    "escalar este caso", "abrir un caso", "abrir caso", "crear incidente",
    "generar incidente", "pasar a nivel 2", "enviar a nivel 2", "escalar a nivel 2",
    "escalar a nivel 3",
]


CORE_INCIDENT_FIELDS = ["software_involved", "error_description", "actions_attempted", "printer_data"]
ENRICHMENT_INCIDENT_FIELDS = ["software_version", "contract_client_location", "evidence", "impact_type"]

FIELD_QUESTIONS = {
    "software_involved": "¿Qué software o herramienta de impresión está involucrado en el incidente?",
    "software_version": "¿Conoces la versión del software involucrado? Si la conoces, compártela; si no, escribe 'no'.",
    "actions_attempted": "¿Qué acciones o validaciones ya realizaste antes de este punto?",
    "error_description": "¿Cuál es el error exacto o síntoma principal que estás observando?",
    "printer_data": "¿Qué datos de la impresora puedes compartir (modelo, conexión, ubicación, etc.)?",
    "contract_client_location": "¿Qué cliente, contrato o ubicación está asociado al caso? Si no aplica o no lo conoces, escribe 'no'.",
    "evidence": "¿Deseas adjuntar o describir alguna evidencia, como capturas o mensajes de error? Si no tienes, escribe 'no'.",
    "impact_type": "¿Qué tipo de afectación genera este incidente? Por ejemplo: un usuario, varios usuarios, dispositivo crítico, indisponibilidad total o intermitente.",
}

NO_VALUE_PATTERNS = {"no", "no aplica", "no tengo", "desconozco", "no sé", "no se"}
NON_INFORMATIVE_REPLY_PATTERNS = {"ya te dije", "ya lo dije", "ya respondí", "ya respondi", "lo mismo", "igual"}


def normalize_user_reply(user_message: str) -> str:
    return " ".join(user_message.strip().lower().split())


def is_no_value_answer(user_message: str) -> bool:
    return normalize_user_reply(user_message) in NO_VALUE_PATTERNS


def is_non_informative_reply(user_message: str) -> bool:
    return normalize_user_reply(user_message) in NON_INFORMATIVE_REPLY_PATTERNS


def looks_like_specific_printer_data(user_message: str) -> bool:
    text = user_message.lower()
    model_or_device_hint = any(term in text for term in [
        "laserjet", "officejet", "deskjet", "pagewide", "multifuncional", "mfp",
        "serial", "serie", "hostname", "usb", "ethernet", "wifi", "scanner", "escaner",
    ])
    ip_hint = bool(re.search(r"\b\d{1,3}(?:\.\d{1,3}){3}\b", user_message))
    hp_model_hint = bool(re.search(r"\bhp\s+[A-Za-z0-9\-]+\b", user_message, re.IGNORECASE))
    return model_or_device_hint or ip_hint or hp_model_hint


def should_activate_escalation_mode(user_message: str) -> bool:
    text = user_message.lower()
    return any(trigger in text for trigger in ESCALATION_TRIGGERS)


def get_missing_incident_fields(state: IncidentState):
    missing = []
    for field_name in CORE_INCIDENT_FIELDS:
        value = getattr(state, field_name, None)
        if not value:
            missing.append(field_name)
    if not missing:
        for field_name in ENRICHMENT_INCIDENT_FIELDS:
            value = getattr(state, field_name, None)
            if not value:
                missing.append(field_name)
    return missing


def apply_no_value_to_field(state: IncidentState, field_name: str):
    fallback_values = {
        "software_version": "No especificada por el usuario",
        "contract_client_location": "No especificado por el usuario",
        "evidence": "No adjunta evidencia",
        "impact_type": "No especificado por el usuario",
    }
    if field_name in fallback_values:
        setattr(state, field_name, fallback_values[field_name])


def generate_escalation_followup(state: IncidentState):
    missing = get_missing_incident_fields(state)
    return FIELD_QUESTIONS[missing[0]] if missing else None


KNOWN_SOFTWARE = ["hp smart device services", "sds", "papercut", "web jetadmin", "hp access control", "gav tracking"]
ACTION_PATTERNS = [
    "reinicié", "reinicie", "reiniciar", "reinstalé", "reinstale", "actualicé", "actualice",
    "verifiqué", "verifique", "probé", "probe", "validé", "valide", "desinstalé", "desinstale",
]
ERROR_PATTERNS = ["error", "falla", "bloqueada", "no responde", "no funciona", "cola", "atasco", "offline", "desconectada"]
VERSION_RE = re.compile(r"(?:versi[oó]n|version)\s*[:\-]?\s*([A-Za-z0-9\.\-_]+)", re.IGNORECASE)




def extract_printer_data_snippet(user_message: str) -> str | None:
    """
    Extract a concise printer/device fragment from free-form escalation text.
    Avoids storing the entire user message as printer_data.
    """
    patterns = [
        r"\bHP\s+[A-Za-z0-9\-]+(?:\s+de\s+la\s+sede\s+[A-Za-zÁÉÍÓÚáéíóúÑñ0-9\s\-]+)?",
        r"\b(?:LaserJet|OfficeJet|DeskJet|PageWide)\s+[A-Za-z0-9\-]+(?:\s+[^.,;]*)?",
        r"\b\d{1,3}(?:\.\d{1,3}){3}\b",
    ]

    for pattern in patterns:
        match = re.search(pattern, user_message, flags=re.IGNORECASE)
        if match:
            return " ".join(match.group(0).strip().split())

    if looks_like_specific_printer_data(user_message) and len(user_message) <= 120:
        return user_message.strip()

    return None


def extract_contract_location_snippet(user_message: str) -> str | None:
    """
    Extract a concise client/contract/location fragment from free-form text.
    Avoids storing the entire user message as contract_client_location.
    """
    text = user_message.strip()

    explicit_patterns = [
        r"(?:cliente|contrato)\s*[:\-]?\s*([A-Za-zÁÉÍÓÚáéíóúÑñ0-9\s\-_.]+?)(?:[.,;]|$)",
        r"(?:sede|ubicaci[oó]n|oficina)\s*[:\-]?\s*([A-Za-zÁÉÍÓÚáéíóúÑñ0-9\s\-_.]+?)(?:[.,;]|$)",
    ]

    for pattern in explicit_patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            value = match.group(1).strip()
            prefix = re.search(r"cliente|contrato|sede|ubicaci[oó]n|oficina", match.group(0), flags=re.IGNORECASE)
            if prefix:
                label = prefix.group(0).strip()
                return " ".join(f"{label} {value}".split())
            return " ".join(value.split())

    return None


def extract_incident_fields(user_message: str):
    text = user_message.lower()
    extracted = {
        "software_involved": None,
        "software_version": None,
        "actions_attempted": [],
        "error_description": None,
        "printer_data": None,
        "contract_client_location": None,
        "evidence": None,
        "impact_type": None,
    }

    papercut_match = re.search(
        r"\b(papercut(?:\s+(?:mf|ng|hive|pocket|mobility print))?)\s+v?(\d+(?:\.\d+)+)\b",
        user_message,
        re.IGNORECASE,
    )
    if papercut_match:
        extracted["software_involved"] = papercut_match.group(1).strip().lower()
        extracted["software_version"] = papercut_match.group(2).strip()

    sds_match = re.search(
        r"\b(hp smart device services|sds|web jetadmin|hp access control|gav tracking)\s+v?(\d+(?:\.\d+)+)\b",
        user_message,
        re.IGNORECASE,
    )
    if sds_match:
        extracted["software_involved"] = sds_match.group(1).strip().lower()
        extracted["software_version"] = sds_match.group(2).strip()

    if not extracted["software_involved"]:
        for software in KNOWN_SOFTWARE:
            if software in text:
                extracted["software_involved"] = software
                break

    version_match = VERSION_RE.search(user_message)
    if version_match and not extracted["software_version"]:
        extracted["software_version"] = version_match.group(1)

    detected_actions = [pattern for pattern in ACTION_PATTERNS if pattern in text]
    if detected_actions:
        extracted["actions_attempted"] = list(dict.fromkeys(detected_actions))

    if any(pattern in text for pattern in ERROR_PATTERNS) or any(
        expr in text for expr in [
            "no puedo", "no deja", "no me permite", "no aparece", "no aparecen",
            "no logro", "no carga", "se detiene", "se cae", "no registra",
            "no agrega", "no detecta", "no encuentra",
        ]
    ):
        extracted["error_description"] = user_message.strip()

    printer_snippet = extract_printer_data_snippet(user_message)
    if printer_snippet:
        extracted["printer_data"] = printer_snippet

    location_snippet = extract_contract_location_snippet(user_message)
    if location_snippet:
        extracted["contract_client_location"] = location_snippet

    if any(term in text for term in ["captura", "screenshot", "pantallazo", "evidencia", "log", "adjunto", "mensaje de error"]):
        # Keep full message only when it is mostly about evidence; otherwise this
        # will be asked as a pending field later.
        if len(user_message) <= 160:
            extracted["evidence"] = user_message.strip()

    if any(term in text for term in [
        "afecta", "varios usuarios", "muchos usuarios", "un usuario", "todos los usuarios",
        "dispositivo crítico", "dispositivo critico", "indisponibilidad", "intermitente",
        "operación detenida", "operacion detenida", "masivo", "masiva",
    ]):
        if len(user_message) <= 160:
            extracted["impact_type"] = user_message.strip()

    return extracted


def update_incident_state(state: IncidentState, extracted_fields: dict):
    if extracted_fields["software_involved"] and not state.software_involved:
        state.software_involved = extracted_fields["software_involved"]
    if extracted_fields["software_version"] and not state.software_version:
        state.software_version = extracted_fields["software_version"]
    if extracted_fields["error_description"] and not state.error_description:
        state.error_description = extracted_fields["error_description"]
    if extracted_fields["printer_data"] and not state.printer_data:
        state.printer_data = extracted_fields["printer_data"]
    if extracted_fields["contract_client_location"] and not state.contract_client_location:
        state.contract_client_location = extracted_fields["contract_client_location"]
    if extracted_fields["evidence"] and not state.evidence:
        state.evidence = extracted_fields["evidence"]
    if extracted_fields["impact_type"] and not state.impact_type:
        state.impact_type = extracted_fields["impact_type"]
    for action in extracted_fields["actions_attempted"]:
        if action not in state.actions_attempted:
            state.actions_attempted.append(action)
    return state


def build_incident_summary(state: IncidentState) -> str:
    return f"""Resumen del incidente:
- Software involucrado: {state.software_involved or 'No especificado'}
- Versión del software: {state.software_version or 'No especificada'}
- Error o síntoma principal: {state.error_description or 'No especificado'}
- Acciones realizadas: {', '.join(state.actions_attempted) if state.actions_attempted else 'No especificadas'}
- Datos de impresora: {state.printer_data or 'No especificados'}
- Cliente / contrato / ubicación: {state.contract_client_location or 'No especificado'}
- Evidencia: {state.evidence or 'No especificada'}
- Tipo de afectación: {state.impact_type or 'No especificado'}""".strip()


def process_escalation_turn(user_message: str, state: IncidentState, session_state: ChatSessionState):
    pending_field = getattr(session_state, "pending_incident_field", None)
    user_text = user_message.strip()

    if pending_field:
        if field_accepts_no_value(pending_field) and is_no_value_answer(user_message):
            apply_no_value_to_field(state, pending_field)

        elif is_no_value_answer(user_message) and not field_accepts_no_value(pending_field):
            return {
                "status": "collecting_information",
                "missing_fields": get_missing_incident_fields(state),
                "next_field": pending_field,
                "next_question": FIELD_QUESTIONS[pending_field],
                "incident_state": state.to_dict(),
            }

        elif is_non_informative_reply(user_message):
            return {
                "status": "collecting_information",
                "missing_fields": get_missing_incident_fields(state),
                "next_field": pending_field,
                "next_question": FIELD_QUESTIONS[pending_field],
                "incident_state": state.to_dict(),
            }

        elif pending_field == "software_involved":
            state.software_involved = user_text

        elif pending_field == "software_version":
            version_only = re.search(r"\b\d+(?:\.\d+)+\b", user_message)
            state.software_version = version_only.group(0) if version_only else user_text

        elif pending_field == "actions_attempted":
            if user_text not in state.actions_attempted:
                state.actions_attempted.append(user_text)

        elif pending_field == "error_description":
            state.error_description = user_text

        elif pending_field == "printer_data":
            state.printer_data = user_text

        elif pending_field == "contract_client_location":
            state.contract_client_location = user_text

        elif pending_field == "evidence":
            state.evidence = "No adjunta evidencia" if is_no_value_answer(user_message) else user_text

        elif pending_field == "impact_type":
            state.impact_type = user_text

        session_state.pending_incident_field = None

    else:
        extracted = extract_incident_fields(user_message)
        update_incident_state(state, extracted)

    missing_fields = get_missing_incident_fields(state)

    if missing_fields:
        next_field = missing_fields[0]
        session_state.pending_incident_field = next_field
        setattr(session_state, "escalation_summary_ready", False)

        return {
            "status": "collecting_information",
            "missing_fields": missing_fields,
            "next_field": next_field,
            "next_question": FIELD_QUESTIONS[next_field],
            "incident_state": state.to_dict(),
        }

    session_state.pending_incident_field = None
    setattr(session_state, "escalation_summary_ready", True)

    return {
        "status": "ready_for_summary",
        "missing_fields": [],
        "summary": build_incident_summary(state),
        "incident_state": state.to_dict(),
    }


def get_llm_usage_estimated_cost(usage_info) -> float | None:
    """
    Extract estimated_cost from provider usage when available.
    """
    if not usage_info:
        return None

    if isinstance(usage_info, dict):
        value = usage_info.get("estimated_cost")
        try:
            return float(value) if value is not None else None
        except Exception:
            return None

    return None


def build_turn_observability_record(
    user_message: str,
    route_type: str,
    query_intent: str | None = None,
    support_info: dict | None = None,
    hard_anchor: bool | None = None,
    strong_entity_match: bool | None = None,
    retrieved_docs: list | None = None,
    real_source_labels: list[str] | None = None,
    llm_diagnostics: dict | None = None,
    latency_seconds: float | None = None,
    fallback_used: bool = False,
    error: str | None = None,
) -> dict:
    """
    Build a compact observability record for debugging, cost tracking,
    future model comparison and hardware sizing.
    """
    support_info = support_info or {}
    retrieved_docs = retrieved_docs or []
    real_source_labels = real_source_labels or []
    llm_diagnostics = llm_diagnostics or {}

    usage = llm_diagnostics.get("usage")
    estimated_cost = get_llm_usage_estimated_cost(usage)

    sources_summary = []
    for doc in retrieved_docs[:6]:
        metadata = doc.metadata or {}
        raw_source = get_best_source_value(metadata)
        clean_source = clean_source_label_text(raw_source)
        sources_summary.append(
            {
                "title": metadata.get("title"),
                "source": clean_source,
                "source_url": clean_source if clean_source.startswith(("http://", "https://")) else None,
                "source_name": Path(clean_source).name if not clean_source.startswith(("http://", "https://")) else None,
                "vendor": metadata.get("vendor"),
                "product": metadata.get("product"),
                "component": metadata.get("component"),
                "document_family": metadata.get("document_family"),
                "page": metadata.get("page"),
                "page_label": metadata.get("page_label"),
            }
        )

    return {
        "timestamp": datetime.now().isoformat(),
        "route_type": route_type,
        "user_message": user_message,
        "query_intent": query_intent,
        "support_level": support_info.get("support_level"),
        "support_top_score": support_info.get("top_score"),
        "support_avg_overlap": support_info.get("avg_overlap"),
        "hard_anchor": hard_anchor,
        "strong_entity_match": strong_entity_match,
        "retrieved_count": len(retrieved_docs),
        "real_source_labels": real_source_labels,
        "retrieved_sources_summary": sources_summary,
        "llm_context": st.session_state.get("last_llm_context_stats", {}),
        "llm": {
            "llm_call_ok": llm_diagnostics.get("llm_call_ok"),
            "model": llm_diagnostics.get("model"),
            "provider": llm_diagnostics.get("provider"),
            "temperature": llm_diagnostics.get("temperature"),
            "max_tokens": llm_diagnostics.get("max_tokens"),
            "max_tokens_source": llm_diagnostics.get("max_tokens_source"),
            "disable_thinking": llm_diagnostics.get("disable_thinking"),
            "finish_reason": llm_diagnostics.get("finish_reason"),
            "usage": usage,
            "estimated_cost": estimated_cost,
            "error": llm_diagnostics.get("error"),
        },
        "latency_seconds": latency_seconds,
        "fallback_used": fallback_used,
        "error": error,
    }


def update_last_turn_diagnostics(record: dict):
    """
    Store last turn diagnostics in Streamlit session state for sidebar/debug UI.
    """
    st.session_state["last_turn_diagnostics"] = record


def append_turn_observability_record(record: dict):
    """
    Append observability record to JSONL file.
    Safe for prototype use. If persistence fails, do not break the app.
    """
    try:
        RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
        with open(TURN_OBSERVABILITY_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        pass

def summarize_turn_observability(limit: int = 500) -> dict[str, Any]:
    """
    Summarize accumulated turn observability records.

    This does not call the LLM. It reads the local JSONL observability file and
    aggregates cost, token usage, latency, intents, models and fallback/error data.
    """
    if not TURN_OBSERVABILITY_FILE.exists():
        return {
            "record_count": 0,
            "message": "No hay registros de observabilidad todavía.",
        }

    records = []

    try:
        with open(TURN_OBSERVABILITY_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue

                try:
                    records.append(json.loads(line))
                except Exception:
                    continue
    except Exception as e:
        return {
            "record_count": 0,
            "error": str(e),
        }

    if limit and len(records) > limit:
        records = records[-limit:]

    total_estimated_cost = 0.0
    total_prompt_tokens = 0
    total_completion_tokens = 0
    total_tokens = 0
    latency_values = []

    intents = defaultdict(int)
    models = defaultdict(int)
    providers = defaultdict(int)
    route_types = defaultdict(int)
    support_levels = defaultdict(int)
    source_counts = defaultdict(int)

    llm_error_count = 0
    fallback_count = 0

    for record in records:
        route_type = record.get("route_type")
        if route_type:
            route_types[route_type] += 1

        query_intent = record.get("query_intent")
        if query_intent:
            intents[query_intent] += 1

        support_level = record.get("support_level")
        if support_level:
            support_levels[support_level] += 1

        latency = record.get("latency_seconds")
        if isinstance(latency, (int, float)):
            latency_values.append(float(latency))

        if record.get("fallback_used"):
            fallback_count += 1

        for source_label in record.get("real_source_labels", []) or []:
            source_counts[source_label] += 1

        llm_info = record.get("llm", {}) or {}

        model = llm_info.get("model")
        if model:
            models[model] += 1

        provider = llm_info.get("provider")
        if provider:
            providers[provider] += 1

        if llm_info.get("error"):
            llm_error_count += 1

        usage = llm_info.get("usage") or {}

        try:
            total_prompt_tokens += int(usage.get("prompt_tokens") or 0)
        except Exception:
            pass

        try:
            total_completion_tokens += int(usage.get("completion_tokens") or 0)
        except Exception:
            pass

        try:
            total_tokens += int(usage.get("total_tokens") or 0)
        except Exception:
            pass

        try:
            estimated_cost = llm_info.get("estimated_cost")
            if estimated_cost is not None:
                total_estimated_cost += float(estimated_cost)
        except Exception:
            pass

    record_count = len(records)
    llm_call_records = sum(1 for r in records if (r.get("llm") or {}).get("llm_call_ok") is not None)

    avg_latency = None
    max_latency = None

    if latency_values:
        avg_latency = round(sum(latency_values) / len(latency_values), 3)
        max_latency = round(max(latency_values), 3)

    avg_total_tokens = round(total_tokens / record_count, 2) if record_count else 0
    avg_prompt_tokens = round(total_prompt_tokens / record_count, 2) if record_count else 0
    avg_completion_tokens = round(total_completion_tokens / record_count, 2) if record_count else 0
    avg_cost = round(total_estimated_cost / record_count, 8) if record_count else 0

    return {
        "record_count": record_count,
        "llm_call_records": llm_call_records,
        "total_estimated_cost": round(total_estimated_cost, 8),
        "avg_estimated_cost_per_turn": avg_cost,
        "total_prompt_tokens": total_prompt_tokens,
        "total_completion_tokens": total_completion_tokens,
        "total_tokens": total_tokens,
        "avg_prompt_tokens_per_turn": avg_prompt_tokens,
        "avg_completion_tokens_per_turn": avg_completion_tokens,
        "avg_total_tokens_per_turn": avg_total_tokens,
        "avg_latency_seconds": avg_latency,
        "max_latency_seconds": max_latency,
        "fallback_count": fallback_count,
        "llm_error_count": llm_error_count,
        "intents": dict(sorted(intents.items())),
        "support_levels": dict(sorted(support_levels.items())),
        "route_types": dict(sorted(route_types.items())),
        "models": dict(sorted(models.items())),
        "providers": dict(sorted(providers.items())),
        "top_sources": dict(
            sorted(
                source_counts.items(),
                key=lambda item: item[1],
                reverse=True,
            )[:10]
        ),
    }

# -----------------------------------------------------------------------------
# Logging / persistence
# -----------------------------------------------------------------------------
LOGS_FILE = RUNTIME_DIR / "conversation_logs.json"
INCIDENTS_FILE = RUNTIME_DIR / "incident_summaries.json"

TURN_OBSERVABILITY_FILE = RUNTIME_DIR / "turn_observability.jsonl"

def append_json_record(file_path: Path, record: dict):
    if file_path.exists():
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = []
    else:
        data = []

    data.append(record)
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def persist_session_logs(session_state: ChatSessionState):
    timestamp = datetime.now().isoformat()
    for entry in session_state.logs:
        record = {
            "timestamp": timestamp,
            "route_type": entry["route_type"],
            "user_message": entry["user_message"],
            "bot_message": entry["bot_message"],
        }
        append_json_record(LOGS_FILE, record)


def persist_incident_summary(session_state: ChatSessionState):
    record = {
        "timestamp": datetime.now().isoformat(),
        "incident_state": session_state.incident_state.to_dict(),
        "summary_text": build_incident_summary(session_state.incident_state),
    }
    append_json_record(INCIDENTS_FILE, record)


def export_incident_summary_text(session_state: ChatSessionState):
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    file_path = RUNTIME_DIR / f"incident_summary_{timestamp}.txt"
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(build_incident_summary(session_state.incident_state))
    return file_path


def finalize_escalation_case(session_state: ChatSessionState):
    persist_session_logs(session_state)
    persist_incident_summary(session_state)
    exported_file = export_incident_summary_text(session_state)
    return {"status": "persisted", "exported_file": str(exported_file)}


# -----------------------------------------------------------------------------
# Routing
# -----------------------------------------------------------------------------

def record_deterministic_route(user_message: str, bot_message: str, route_type: str, session_state: ChatSessionState):
    clear_last_response_pdf_sources()
    session_state.memory.add_turn(user_message, bot_message)
    session_state.log_turn(user_message, bot_message, route_type)
    record = build_turn_observability_record(
        user_message=user_message,
        route_type=route_type,
        query_intent=None,
        support_info={"support_level": "not_applicable", "top_score": 0, "avg_overlap": 0},
        hard_anchor=False,
        strong_entity_match=False,
        retrieved_docs=[],
        real_source_labels=[],
        llm_diagnostics={"llm_call_ok": None, "model": None, "provider": None, "usage": None, "error": None},
        latency_seconds=0.0,
        fallback_used=False,
    )
    update_last_turn_diagnostics(record)
    append_turn_observability_record(record)
    return bot_message


def reset_active_escalation(session_state: ChatSessionState, keep_last_summary: bool = True):
    last_summary = getattr(session_state, "last_escalation_summary", None) if keep_last_summary else None
    last_file = getattr(session_state, "last_escalation_exported_file", None) if keep_last_summary else None
    session_state.incident_state = IncidentState()
    session_state.pending_incident_field = None
    session_state.escalation_summary_ready = False
    session_state.escalation_persisted = False
    session_state.escalation_workflow_state = "normal"
    session_state.mode = "normal"
    session_state.last_escalation_summary = last_summary
    session_state.last_escalation_exported_file = last_file
    return session_state


def start_new_escalation(session_state: ChatSessionState):
    session_state.incident_state = IncidentState()
    session_state.incident_state.escalation_requested = True
    session_state.pending_incident_field = None
    session_state.escalation_summary_ready = False
    session_state.escalation_persisted = False
    session_state.escalation_workflow_state = "escalation_collecting"
    session_state.mode = "escalation"
    return session_state


def build_pending_field_help(session_state: ChatSessionState) -> str:
    field_name = getattr(session_state, "pending_incident_field", None)
    if not field_name:
        return (
            "Estoy recopilando la información del incidente. Puedes responder la pregunta actual "
            "o escribir 'cancelar' para abandonar el escalamiento."
        )
    return (
        "Para continuar con el escalamiento necesito este dato:\n\n"
        f"{FIELD_QUESTIONS[field_name]}\n\n"
        "Si no deseas continuar, escribe 'cancelar'."
    )


def complete_escalation_case(user_message: str, summary: str, session_state: ChatSessionState):
    clear_last_response_pdf_sources()
    session_state.pending_incident_field = None
    session_state.escalation_summary_ready = True
    session_state.escalation_workflow_state = "escalation_completed"
    session_state.last_escalation_summary = summary
    bot_message = (
        "He reunido la información principal del caso y el escalamiento quedó finalizado. "
        "Este es el resumen:\n\n"
        f"{summary}\n\n"
        "El siguiente mensaje se procesará como una nueva consulta normal."
    )
    session_state.memory.add_turn(user_message, bot_message)
    session_state.log_turn(user_message, bot_message, "escalation_summary_completed")
    if not getattr(session_state, "escalation_persisted", False):
        try:
            persisted = finalize_escalation_case(session_state)
            session_state.escalation_persisted = True
            session_state.last_escalation_exported_file = persisted.get("exported_file")
        except Exception as exc:
            session_state.escalation_persisted = False
            st.session_state["last_escalation_persistence_error"] = str(exc)
    session_state.mode = "normal"
    session_state.pending_incident_field = None
    session_state.incident_state.escalation_requested = False
    return bot_message


def handle_escalation_message(user_message: str, session_state: ChatSessionState):
    session_state = ensure_session_state_integrity(session_state)
    if getattr(session_state, "escalation_workflow_state", "normal") != "escalation_collecting":
        start_new_escalation(session_state)
    if is_escalation_cancel_command(user_message):
        reset_active_escalation(session_state, keep_last_summary=True)
        return record_deterministic_route(user_message, "El escalamiento fue cancelado. Puedes continuar con una nueva consulta de soporte.", "escalation_cancelled", session_state)
    if is_capabilities_help_message(user_message):
        return record_deterministic_route(user_message, build_pending_field_help(session_state), "escalation_field_help", session_state)
    if is_escalation_finish_command(user_message):
        missing = get_missing_incident_fields(session_state.incident_state)
        if missing:
            field_name = missing[0]
            session_state.pending_incident_field = field_name
            return record_deterministic_route(user_message, "Aún faltan datos mínimos para cerrar el escalamiento.\n\n" + FIELD_QUESTIONS[field_name], "escalation_finish_incomplete", session_state)
    result = process_escalation_turn(user_message, session_state.incident_state, session_state)
    if result["status"] == "collecting_information":
        session_state.pending_incident_field = result["next_field"]
        session_state.escalation_workflow_state = "escalation_collecting"
        session_state.mode = "escalation"
        return record_deterministic_route(user_message, result["next_question"], "escalation_collect", session_state)
    return complete_escalation_case(user_message, result["summary"], session_state)


def handle_normal_message(user_message: str, session_state: ChatSessionState):
    bot_message = generate_answer_with_rag(user_query=user_message, memory=session_state.memory)
    session_state.log_turn(user_message, bot_message, "rag_answer")
    update_conversation_topic(session_state, user_message, classify_query_intent(user_message))
    return bot_message


def handle_follow_up_message(user_message: str, session_state: ChatSessionState):
    contextual_query = build_contextual_follow_up_query(user_message, session_state)
    if not contextual_query:
        return record_deterministic_route(
            user_message,
            "Necesito un poco más de contexto. Indícame a qué producto, herramienta o proceso te refieres.",
            "follow_up_needs_context",
            session_state,
        )
    bot_message = generate_answer_with_rag(user_query=contextual_query, memory=session_state.memory)
    session_state.log_turn(user_message, bot_message, "rag_answer")
    topic = get_conversation_topic(session_state)
    topic["intent"] = classify_query_intent(user_message)
    topic["last_follow_up"] = user_message
    session_state.conversation_topic = topic
    st.session_state["last_follow_up_resolution"] = {
        "original_query": user_message,
        "resolved_query": contextual_query,
        "topic": topic,
    }
    return bot_message


def try_agent_core_deterministic_response(user_message: str, session_state: ChatSessionState):
    """Return an authorized deterministic response or None for legacy fallback."""
    try:
        enabled = bool(st.secrets.get("AGENT_CORE_V1_DETERMINISTIC_ENABLED", False))
    except Exception:
        enabled = False

    if not enabled:
        return None

    try:
        from app.integration.deterministic_activation_v1 import (
            append_activation_record,
            evaluate_deterministic_activation,
        )

        record = evaluate_deterministic_activation(user_message, session_state)
        append_activation_record(st.session_state, record)
        if not record.get("authorized"):
            return None

        response = str(record.get("response") or "").strip()
        if not response:
            return None

        route = str((record.get("decision") or {}).get("route") or "deterministic")
        return record_deterministic_route(
            user_message,
            response,
            f"agent_core_{route}",
            session_state,
        )
    except Exception as exc:
        # Any Agent Core error falls back to the unchanged legacy route.
        error_record = {
            "timestamp": datetime.now().isoformat(),
            "input": user_message,
            "error": f"{type(exc).__name__}: {exc}",
            "authorized": False,
            "fallback_to_legacy": True,
            "additional_llm_calls": 0,
            "additional_retrieval_calls": 0,
        }
        try:
            records = list(st.session_state.get("agent_core_deterministic_records", []) or [])
            records.append(error_record)
            st.session_state["agent_core_deterministic_records"] = records[-100:]
            st.session_state["agent_core_deterministic_last_record"] = error_record
        except Exception:
            pass
        return None

def try_agent_core_contextual_rag_response(user_message: str, session_state: ChatSessionState):
    """Use legacy RAG only when the existing router decision has enough technical context."""
    try:
        enabled = bool(st.secrets.get("AGENT_CORE_V1_CONTEXTUAL_RAG_ENABLED", False))
    except Exception:
        enabled = False

    if not enabled:
        return None

    try:
        from app.integration.contextual_rag_v1 import (
            append_contextual_record,
            build_contextual_query,
        )

        # Reuse the decision already produced by deterministic activation.
        # Do not call route_message() again because that increments state twice.
        activation_record = st.session_state.get(
            "agent_core_deterministic_last_record",
            {},
        ) or {}
        decision = activation_record.get("decision") or {}

        if decision.get("route") != "contextual_guidance":
            return None

        record = build_contextual_query(user_message, session_state)
        readiness = record.get("readiness") or {}

        if not readiness.get("ready_for_rag"):
            record.update(
                {
                    "route": "contextual_guidance",
                    "rag_called": False,
                    "llm_called": False,
                    "gate_result": "clarification_required",
                }
            )
            append_contextual_record(st.session_state, record)
            response = str(readiness.get("clarification_response") or "").strip()
            return record_deterministic_route(
                user_message,
                response,
                "agent_core_contextual_clarification",
                session_state,
            )

        record.update(
            {
                "route": "contextual_guidance",
                "rag_called": True,
                "llm_called": True,
                "gate_result": "rag_authorized",
            }
        )
        append_contextual_record(st.session_state, record)

        bot_message = generate_answer_with_rag(
            user_query=record["contextual_query"],
            memory=session_state.memory,
        )
        session_state.log_turn(
            user_message,
            bot_message,
            "agent_core_contextual_rag",
        )
        return bot_message
    except Exception as exc:
        try:
            records = list(
                st.session_state.get("agent_core_contextual_records", []) or []
            )
            records.append(
                {
                    "input": user_message,
                    "error": f"{type(exc).__name__}: {exc}",
                    "fallback_to_legacy": True,
                    "rag_called": False,
                    "llm_called": False,
                }
            )
            st.session_state["agent_core_contextual_records"] = records[-100:]
        except Exception:
            pass
        return None
def observe_agent_core_semantic_real_chat_shadow(
    user_message: str,
    session_state: ChatSessionState,
):
    try:
        enabled = bool(
            st.secrets.get(
                "AGENT_CORE_SEMANTIC_REAL_CHAT_SHADOW_ENABLED",
                False,
            )
        )
    except Exception:
        enabled = False

    if not enabled:
        return None

    try:
        from app.integration.semantic_real_chat_shadow import (
            observe_semantic_real_chat_turn,
        )

        return observe_semantic_real_chat_turn(
            user_message,
            session_state,
            st.session_state,
            st.secrets,
        )
    except Exception as exc:
        records = list(
            st.session_state.get(
                "agent_core_semantic_real_chat_records",
                [],
            )
            or []
        )
        records.append(
            {
                "input": user_message,
                "status": "observer_error",
                "error": f"{type(exc).__name__}: {exc}",
                "production_response_changed": False,
                "retrieval_executed": False,
                "state_applied_to_production": False,
            }
        )
        st.session_state[
            "agent_core_semantic_real_chat_records"
        ] = records[-100:]
        return None

def route_user_message(user_message: str, session_state: ChatSessionState):
    session_state = ensure_session_state_integrity(session_state)
    semantic_record = observe_agent_core_semantic_real_chat_shadow(
        user_message,
        session_state,
    )
    try:
        bridge_enabled = bool(st.secrets.get("AGENT_CORE_SEMANTIC_CONTEXTUAL_BRIDGE_ENABLED", False))
    except Exception:
        bridge_enabled = False
    if bridge_enabled and semantic_record:
        try:
            from app.integration.semantic_contextual_bridge import try_semantic_contextual_bridge
            semantic_answer, bridge_record = try_semantic_contextual_bridge(
                user_message, session_state, st.session_state, st.secrets, semantic_record
            )
            if semantic_answer is not None:
                session_state.memory.add_turn(user_message, semantic_answer)
                session_state.log_turn(user_message, semantic_answer, "semantic_contextual_bridge")
                return semantic_answer
        except Exception as exc:
            st.session_state["agent_core_semantic_contextual_bridge_error"] = f"{type(exc).__name__}: {exc}"
    workflow_state = getattr(session_state, "escalation_workflow_state", "normal")

    if workflow_state == "escalation_collecting" or session_state.mode == "escalation":
        return handle_escalation_message(user_message, session_state)

    if workflow_state == "escalation_completed" and (
        is_acknowledgement_message(user_message)
        or is_escalation_finish_command(user_message)
        or is_escalation_cancel_command(user_message)
    ):
        session_state.escalation_workflow_state = "normal"
        session_state.mode = "normal"
        return record_deterministic_route(
            user_message,
            "El caso anterior quedó cerrado. Cuando quieras, puedes realizar una nueva consulta.",
            "escalation_completed_ack",
            session_state,
        )

    if workflow_state == "escalation_completed":
        session_state.escalation_workflow_state = "normal"
        session_state.mode = "normal"

    agent_core_response = try_agent_core_deterministic_response(user_message, session_state)
    if agent_core_response is not None:
        return agent_core_response

    contextual_response = try_agent_core_contextual_rag_response(
        user_message,
        session_state,
    )
    if contextual_response is not None:
        return contextual_response

    if is_capabilities_help_message(user_message):
        return record_deterministic_route(user_message, CAPABILITIES_HELP_RESPONSE, "capabilities_help", session_state)
    if is_support_intake_message(user_message):
        return record_deterministic_route(user_message, SUPPORT_INTAKE_RESPONSE, "support_intake", session_state)
    if is_explicit_follow_up_query(user_message):
        return handle_follow_up_message(user_message, session_state)
    if should_activate_escalation_mode(user_message):
        start_new_escalation(session_state)
        return handle_escalation_message(user_message, session_state)
    if is_ambiguous_print_issue(user_message):
        return record_deterministic_route(
            user_message, build_ambiguous_print_issue_response(user_message),
            "ambiguous_print_issue", session_state,
        )
    if not is_in_scope_message(user_message):
        return record_deterministic_route(user_message, OUT_OF_SCOPE_RESPONSE, "out_of_scope", session_state)
    return handle_normal_message(user_message, session_state)



def get_backend_status():
    status = {
        "vectorstore_ok": False,
        "embedding_ok": False,
        "hf_client_ok": False,
        "llm_model": get_effective_llm_model(),
        "hf_provider": get_effective_hf_provider(),
        "llm_max_tokens": get_effective_max_tokens(),
        "llm_max_tokens_source": get_effective_max_tokens_source(),
        "llm_disable_thinking": get_effective_disable_thinking(),
        "error": None,
        "backend_vnext_marker": globals().get("BACKEND_VNEXT_MARKER", "not_set"),
    }

    try:
        _ = get_embedding_model()
        status["embedding_ok"] = True
    except Exception as e:
        status["error"] = f"Embedding model error: {e}"
        return status

    try:
        _ = get_vectorstore()
        status["vectorstore_ok"] = True
    except Exception as e:
        status["error"] = f"Vectorstore error: {e}"
        return status

    try:
        hf_client = get_hf_client()
        status["hf_client_ok"] = hf_client is not None
        if hf_client is None:
            status["error"] = "HF_TOKEN is missing or HF client could not be initialized."
    except Exception as e:
        status["error"] = f"HF client error: {e}"

    try:
        counts = get_vectorstore_metadata_value_counts()

        status["metadata_counts_top"] = {
            field: sorted(
                [(str(k), int(v)) for k, v in values.items()],
                key=lambda item: item[1],
                reverse=True,
            )[:20]
            for field, values in counts.items()
        }
    except Exception as exc:
        status["metadata_counts_error"] = str(exc)

    return status
