from __future__ import annotations

import re
import unicodedata

_STOP = {
    "a", "al", "algo", "cual", "cuales", "de", "del", "el", "en", "es", "ese",
    "esos", "esta", "estos", "la", "las", "lo", "los", "que", "se", "un", "una",
    "uno", "usa", "usan", "utiliza", "utilizan", "y",
}
_NUMBER = re.compile(r"(?<![A-Za-z0-9])([0-9]{2,5})(?![A-Za-z0-9])")
_CITATION = re.compile(r"\[(R[0-9]+)\]")


def _fold(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or "").casefold())
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", text).strip()


def _query_terms(message: str) -> list[str]:
    terms = []
    for term in re.findall(r"[a-z0-9]{3,}", _fold(message)):
        if term not in _STOP and not term.isdigit() and term not in terms:
            terms.append(term)
    return terms


def _numeric_segments(text: str) -> list[tuple[str, str]]:
    raw = " ".join(str(text or "").split())
    matches = list(_NUMBER.finditer(raw))
    out = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else min(len(raw), match.end() + 260)
        segment = raw[match.start():end].strip(" ,;:-")
        if segment:
            out.append((match.group(1), segment[:300]))
    return out


def _candidate_property(message: str, evidence: list[dict]) -> tuple[str | None, dict[str, dict]]:
    terms = _query_terms(message)
    by_term: dict[str, dict[str, dict]] = {}
    for item in evidence or []:
        source_id = str(item.get("id") or "").strip()
        if not source_id:
            continue
        for value, segment in _numeric_segments(str(item.get("text") or "")):
            folded_segment = _fold(segment)
            for term in terms:
                if re.search(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])", folded_segment):
                    by_term.setdefault(term, {}).setdefault(value, {"id": source_id, "segment": segment})
    eligible = [(term, values) for term, values in by_term.items() if 2 <= len(values) <= 8]
    if not eligible:
        return None, {}
    # Prefer the most selective property. A property such as TLS should win over a broad word.
    eligible.sort(key=lambda item: (len(item[1]), -len(item[0])))
    return eligible[0]


def ensure_enumeration_completeness(message: str, answer: str, evidence: list[dict]) -> tuple[str, dict]:
    """Repair a narrow numeric enumeration only when the answer already names the same set.

    The guard is intentionally conservative: it activates only when one query property is explicitly
    attached to two through eight numeric values in authorized evidence and the model already
    published at least one of those values. This prevents broad requirements answers from being
    rewritten and does not depend on products, protocols, documents or campaign-specific values.
    """
    original = str(answer or "").strip()
    property_term, documented = _candidate_property(message, evidence)
    diagnostic = {
        "checked": True,
        "property_term": property_term,
        "documented_values": sorted(documented),
        "response_values": [],
        "missing_values": [],
        "repaired": False,
    }
    if not property_term or not original:
        return original, diagnostic

    present = [value for value in documented if re.search(rf"(?<![0-9]){re.escape(value)}(?![0-9])", original)]
    missing = [value for value in documented if value not in present]
    diagnostic["response_values"] = sorted(present)
    diagnostic["missing_values"] = sorted(missing)

    # The existing answer must already be answering this numeric set. Never synthesize a new set.
    if not present or not missing or len(missing) > 4:
        return original, diagnostic

    additions = []
    added_ids = []
    for value in missing:
        fact = documented[value]
        source_id = fact["id"]
        segment = fact["segment"]
        additions.append(f"- **{value}:** {segment} [{source_id}]")
        if source_id not in added_ids:
            added_ids.append(source_id)

    repaired = original + "\n\n**Cobertura documental adicional**\n\n" + "\n".join(additions)
    diagnostic.update({"repaired": True, "added_citation_ids": added_ids})
    return repaired, diagnostic
