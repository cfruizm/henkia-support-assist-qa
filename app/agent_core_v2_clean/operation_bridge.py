"""Cross-language bridge for operation and support-concept terms.

Users write in Spanish while much of the documentation (vendor manuals, web
knowledge bases) is in English. Evidence authorities compared request tokens
literally, so "instala" never matched "installation" and correct documents were
rejected (no_operationally_aligned_evidence).

This bridge maps normalized Spanish stems of *operations and generic support
concepts* to English stems. It contains no product, vendor or document names
(project rule: product neutrality). Matching is by stem prefix on normalized,
accent-free tokens.
"""
from __future__ import annotations

import re
import unicodedata

from .text_stems import stem_index, term_matches

# Spanish stem -> English stems. Keep entries generic (verbs/support nouns).
_ES_TO_EN_STEMS: dict[str, tuple[str, ...]] = {
    "desinstal": ("uninstall", "remov"),
    "reinstal": ("reinstall", "install"),
    "instal": ("install", "setup", "deploy"),
    "configur": ("configur", "setup", "setting"),
    "actualiz": ("updat", "upgrad"),
    "requisit": ("requirement", "prerequisit", "require"),
    "prerrequisit": ("prerequisit", "requirement"),
    "requerimient": ("requirement",),
    "desaparec": ("disappear", "missing", "lost", "delet"),
    "faltant": ("missing",),
    "perdid": ("lost", "missing"),
    "liber": ("releas",),
    "retenid": ("held", "hold"),
    "detenid": ("stuck", "held", "paus", "stopp"),
    "atasc": ("jam", "stuck"),
    "trabaj": ("job",),
    "cola": ("queue",),
    "impres": ("print",),
    "imprim": ("print",),
    "escane": ("scan",),
    "digitaliz": ("scan",),
    "carpet": ("folder",),
    "puert": ("port",),
    "certificad": ("certificat",),
    "licenci": ("licens", "licenc"),
    "migr": ("migrat",),
    "respald": ("backup",),
    "restaur": ("restor",),
    "registr": ("regist", "log"),
    "conect": ("connect",),
    "conexion": ("connect",),
    "autentic": ("authent",),
    "tarjet": ("card",),
    "cuota": ("quota",),
    "report": ("report",),
    "inform": ("report",),
    "error": ("error",),
    "fall": ("fail", "error"),
    "valid": ("valid", "verif", "check"),
    "verific": ("verif", "check"),
    "revis": ("check", "review", "verif"),
    "diagnost": ("troubleshoot", "diagnos"),
    "solucion": ("troubleshoot", "solution", "resolv"),
    "paso": ("step",),
    "habilit": ("enabl",),
    "deshabilit": ("disabl",),
    "export": ("export",),
    "import": ("import",),
    "usuari": ("user",),
    "contrasen": ("password",),
    "clave": ("password", "key"),
    "servidor": ("server",),
    "dispositiv": ("device",),
    "firmware": ("firmware",),
    "controlador": ("driver",),
    "agente": ("agent",),
    "monitore": ("monitor",),
    "permis": ("permission",),
    # "acceso" is intentionally absent: "access" appears in product names and
    # would turn a subject-only match into a false operation match.
    "seguridad": ("secur",),
    "copia": ("copy",),
    "descarg": ("download",),
    "actualizacion": ("updat", "upgrad"),
}

# Organizational qualifiers that vendor documentation never states; they must not
# be required as operation dimensions ("procedimiento aprobado").
QUALIFIERS = frozenset({
    "aprobado", "aprobada", "aprobados", "aprobadas", "oficial", "oficiales",
    "correcto", "correcta", "adecuado", "adecuada", "recomendado", "recomendada",
    "mejor", "valido", "valida", "vigente", "estandar",
})

# Function words that carry no operation and must not be required dimensions.
FILLERS = frozenset({
    "antes", "despues", "debo", "debe", "deben", "debemos", "cuales", "donde",
    "cuando", "porque", "sigue", "siguen", "tengo", "tiene", "tienen", "ahora",
    "todavia", "tambien", "sobre", "entre", "desde", "hasta", "segun",
})

_STEMS_BY_LENGTH = sorted(_ES_TO_EN_STEMS, key=len, reverse=True)


def normalize(value: str) -> str:
    return unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode().casefold()


def english_stems(term: str) -> tuple[str, ...]:
    """English stems for a normalized Spanish term, or () when unknown."""
    term = normalize(term)
    for stem in _STEMS_BY_LENGTH:
        if term.startswith(stem):
            return _ES_TO_EN_STEMS[stem]
    return ()


def term_present(term: str, available: set[str], translations: dict | None = None, available_stems: set | None = None) -> bool:
    """True when the term appears in the available tokens.

    Order: exact token -> same stem (Snowball es/en, any word form) -> the term's
    English translation from the understanding contract -> legacy stem map
    (fallback, to be retired once stemming + translations are validated).
    """
    term = normalize(term)
    if term in available:
        return True
    index = available_stems if available_stems is not None else stem_index(available)
    if term_matches(term, index):
        return True
    translated = (translations or {}).get(term)
    if translated and term_matches(translated, index):
        return True
    legacy = english_stems(term)
    return bool(legacy) and any(token.startswith(stem) for stem in legacy for token in available)


def present_terms(terms: set[str], available: set[str], translations: dict | None = None) -> set[str]:
    index = stem_index(available)
    return {term for term in terms if term_present(term, available, translations, index)}


def translation_map(understanding) -> dict:
    """{normalized source term: english} from the understanding contract."""
    out = {}
    for item in (understanding or {}).get("term_translations") or []:
        if isinstance(item, dict):
            source, english = normalize(item.get("term")), str(item.get("english") or "").strip()
            for word in re.findall(r"[a-z0-9]+", source):
                if english and len(word) >= 3:
                    out.setdefault(word, english)
    return out


def tokens(value: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", normalize(value)))
