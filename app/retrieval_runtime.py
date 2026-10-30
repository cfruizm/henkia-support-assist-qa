from __future__ import annotations
import json
import re
import unicodedata
from collections import defaultdict
from pathlib import Path
import streamlit as st
from langchain_core.documents import Document
from app.config import CONFIG
from app.domain_registry import PRODUCT_ENTITY_REGISTRY, PRODUCT_ALIAS_INDEX, PROCESS_ALIAS_INDEX, detect_entities_in_text
from app.vectorstore_runtime import get_vectorstore

RETRIEVAL_RUNTIME_VERSION = "4C.2.1"
RUNTIME_OWNERSHIP = "productive_retrieval_boundary"
LEGACY_BACKEND_DEPENDENCY = False

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
    vectorstore = get_vectorstore()
    profile = detect_query_profile(query)
    query_intent = classify_query_intent(query)

    k_initial = profile.get("k_initial", top_k)
    k_final = profile.get("k_final", top_k)
    metadata_filter = profile.get("filter")

    def run_retrieval(retrieval_query: str, filter_value=None):
        search_kwargs = {"k": k_initial}
        if filter_value:
            search_kwargs["filter"] = filter_value
        retriever = vectorstore.as_retriever(search_kwargs=search_kwargs)
        return retriever.invoke(retrieval_query)

    retrieval_queries = build_transversal_expanded_queries(query, query_intent)
    docs = []
    seen_candidate_keys = set()

    def add_candidates(new_docs):
        for candidate in new_docs or []:
            md = candidate.metadata or {}
            key = (
                md.get("source")
                or md.get("source_url")
                or md.get("canonical_url")
                or md.get("title")
                or candidate.page_content[:160]
            )
            if key in seen_candidate_keys:
                continue
            seen_candidate_keys.add(key)
            docs.append(candidate)

    # Deterministic anchor candidates first. These guarantee exact title/source
    # matches are present before semantic reranking.
    add_candidates(get_anchor_docs_for_issue_packs(vectorstore, query, query_intent, metadata_filter))

    filter_sequence = build_controlled_filter_sequence(metadata_filter, query)

    for filter_value in filter_sequence:
        for retrieval_query in retrieval_queries:
            try:
                add_candidates(run_retrieval(retrieval_query, filter_value))
            except Exception:
                pass

        # If we already found candidates, stop relaxing filters.
        # This prevents broader filters from contaminating a good result set.
        if docs:
            break

    # Broad fallback is allowed only when there was no explicit metadata filter.
    # This avoids contaminating HP SDS / GAV / DA Arus queries with PaperCut web docs.
    if not docs and not metadata_filter:
        for retrieval_query in retrieval_queries:
            try:
                add_candidates(run_retrieval(retrieval_query, None))
            except Exception:
                pass

    if not docs:
        return "", []
        
    ranked_docs_with_scores = []

    for doc in docs:
        score = compute_rerank_score(query, doc, query_intent)
        ranked_docs_with_scores.append((doc, score))
    
    ranked_docs_with_scores.sort(
        key=lambda item: item[1],
        reverse=True,
    )
    
    top_score = ranked_docs_with_scores[0][1] if ranked_docs_with_scores else 0.0
    
    filtered_ranked_docs = [
        doc
        for doc, score in ranked_docs_with_scores
        if should_keep_ranked_doc(
            query=query,
            doc=doc,
            score=score,
            top_score=top_score,
            query_intent=query_intent,
        )
    ]
    
    # If the filter is too strict, fall back only to the strongest 2 reranked docs.
    # This avoids reintroducing low-quality contaminated context.
    if not filtered_ranked_docs:
        filtered_ranked_docs = [
            doc
            for doc, score in ranked_docs_with_scores[:2]
        ]
    
    ranked_docs = filtered_ranked_docs
    ranked_docs = deduplicate_ranked_docs(ranked_docs)

    ranked_docs = [
        doc for doc in ranked_docs
        if not is_tangential_source_for_query(query, doc)
    ]

    ranked_docs_without_low_info = [
        doc for doc in ranked_docs
        if not is_low_information_chunk(doc)
    ]

    # Prefer useful chunks, but avoid emptying the context completely.
    if ranked_docs_without_low_info:
        ranked_docs = ranked_docs_without_low_info

    if not ranked_docs:
        ranked_docs = deduplicate_ranked_docs(filtered_ranked_docs)

    # Safe fallback for explicit metadata-filtered queries.
    #
    # Why:
    # HP SDS, GAV, HP WJA and internal PDFs can have lower semantic scores than
    # PaperCut web articles. If the query had a safe metadata filter and we already
    # restricted retrieval to that product/vendor family, it is safer to keep the
    # best filtered candidates than to return no documents.
    #
    # This does NOT do broad retrieval and therefore does not reintroduce PaperCut
    # contamination into HP/GAV queries.
    if not ranked_docs and metadata_filter and ranked_docs_with_scores:
        ranked_docs = [
            doc
            for doc, score in ranked_docs_with_scores[:k_final]
        ]

    # Second safeguard:
    # If low-information/tangential filtering removed everything after a valid
    # metadata-filtered retrieval, keep the best filtered candidates.
    if metadata_filter and not ranked_docs and ranked_docs_with_scores:
        ranked_docs = [
            doc
            for doc, score in ranked_docs_with_scores[:k_final]
        ]
    
    # Source diversity: avoid sending 4 chunks from the same PDF when possible.
    max_docs_per_source = CONFIG.get("max_docs_per_source", 2)
    selected_docs = []
    source_counts = defaultdict(int)

    for doc in ranked_docs:
        source_key = str(doc.metadata.get("source", "unknown_source"))
        if source_counts[source_key] >= max_docs_per_source:
            continue

        selected_docs.append(doc)
        source_counts[source_key] += 1

        if len(selected_docs) >= k_final:
            break

    # If diversity was too restrictive, fill remaining slots.
    if len(selected_docs) < k_final:
        selected_ids = {id(doc) for doc in selected_docs}
        for doc in ranked_docs:
            if id(doc) in selected_ids:
                continue
            selected_docs.append(doc)
            if len(selected_docs) >= k_final:
                break

    context_blocks = []

    for i, doc in enumerate(selected_docs, start=1):
        source_label = format_source_label(doc.metadata)
        content = doc.page_content.strip()

        context_blocks.append(
            f"[Chunk {i}] Source: {source_label}\n{content}"
        )

    return "\n\n".join(context_blocks), selected_docs
