"""Language-aware term matching with Snowball stemmers (Spanish and English).

Evidence authorities compared request words literally, so "instala" never matched
"instalación" or "installation". Stemming maps word forms to a common root without
any hand-written word list:

    instala / instalación / install / installation -> "instal"
    configurar / configuración / configure          -> "configur"

Stemming does not translate (liberar vs release); translations come from the
understanding contract (term_translations) and are matched with the same rules.
"""
from __future__ import annotations

import re
import unicodedata
from functools import lru_cache

try:
    import snowballstemmer
    _STEMMERS = (snowballstemmer.stemmer("spanish"), snowballstemmer.stemmer("english"))
except Exception:  # pragma: no cover - dependency missing: exact matching only
    _STEMMERS = ()

# A stem shorter than this only matches exactly; avoids "port" ~ "portal".
MIN_PREFIX_STEM = 5


def normalize(value: str) -> str:
    return unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode().casefold()


@lru_cache(maxsize=20000)
def stems(token: str) -> frozenset[str]:
    """Spanish and English stems of one normalized token (plus the token itself)."""
    token = normalize(token)
    found = {token}
    for stemmer in _STEMMERS:
        stem = stemmer.stemWord(token)
        if stem:
            found.add(stem)
    return frozenset(found)


def stem_index(tokens) -> set[str]:
    """All stems of a set of available tokens, computed once per evidence item."""
    out: set[str] = set()
    for token in tokens or ():
        out |= stems(token)
    return out


def _stem_match(term_stems, available_stems) -> bool:
    if term_stems & available_stems:
        return True
    for stem in term_stems:
        if len(stem) < MIN_PREFIX_STEM:
            continue
        for other in available_stems:
            if len(other) >= MIN_PREFIX_STEM and (other.startswith(stem) or stem.startswith(other)):
                return True
    return False


def collapse_by_stem(terms) -> set[str]:
    """One representative per root: word forms of the same root count once.

    Without this, "cambiar" and "cambio" in one request counted as two covered
    terms, so a generic verb alone reached the coverage threshold.
    """
    groups: dict[str, str] = {}
    for term in sorted(terms or (), key=lambda t: (len(t), t)):
        key = min(stems(term), key=len)
        groups.setdefault(key, term)
    return set(groups.values())


def term_matches(term: str, available_stems: set[str]) -> bool:
    """True when any word of `term` (a word or short phrase) matches by stem."""
    words = [w for w in re.findall(r"[a-z0-9]+", normalize(term)) if len(w) >= 3]
    if not words:
        return False
    return all(_stem_match(stems(word), available_stems) for word in words)
