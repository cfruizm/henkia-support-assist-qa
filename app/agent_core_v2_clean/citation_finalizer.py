from __future__ import annotations
from dataclasses import dataclass, asdict
import re
from .source_footer import compact_sources, strip_generated_source_footer

_CITE = re.compile(r"\[(R\d+)\]")
_SOURCE_SECTION = re.compile(r"(?is)\n*\*\*Fuentes documentales\*\*\s*\n.*\Z")
_SOURCE_LINE = re.compile(r"(?m)^\s*-\s*\[(R\d+)\].*$")


@dataclass(frozen=True)
class CitationAudit:
    cited_ids: list[str]
    valid_ids: list[str]
    remapped_ids: dict[str, str]
    preserved_canonical_ids: list[str]
    unknown_ids: list[str]
    stripped_ids: list[str]
    valid: bool
    namespace: str

    def to_dict(self):
        return asdict(self)


def _page_value(value):
    text = str(value or "").strip()
    match = re.fullmatch(r"\d+", text)
    return int(text) if match else text


def _page_ranges(values):
    numeric = sorted({x for x in (_page_value(v) for v in values) if isinstance(x, int)})
    other = sorted({str(x) for x in (_page_value(v) for v in values) if x and not isinstance(x, int)})
    ranges = []
    index = 0
    while index < len(numeric):
        start = end = numeric[index]
        while index + 1 < len(numeric) and numeric[index + 1] == end + 1:
            index += 1
            end = numeric[index]
        ranges.append(str(start) if start == end else f"{start} a {end}")
        index += 1
    ranges.extend(other)
    if not ranges:
        return "página no especificada"
    if len(ranges) == 1:
        label = "páginas" if " a " in ranges[0] else "página"
        return f"{label} {ranges[0]}"
    return "páginas " + ", ".join(ranges[:-1]) + " y " + ranges[-1]


def _compact_source_footer(source, cited, evidence):
    clean=strip_generated_source_footer(source)
    footer=compact_sources(evidence,cited)
    return clean+("\n\n"+footer if footer else "")

def finalize_citations(text, plan):
    plan = plan or {}
    ep = plan.get("evidence_plan") or {}
    rp = plan.get("response_plan") or {}
    mapping = {str(k): str(v) for k, v in (ep.get("citation_map") or {}).items()}
    valid = {str(x) for x in ep.get("documented_ids") or []}
    source = str(text or "")
    remapped = {}
    preserved = []

    def resolve(cid):
        if cid in valid:
            preserved.append(cid)
            return cid
        target = mapping.get(cid)
        if target in valid:
            remapped[cid] = target
            return target
        return cid

    source = _CITE.sub(lambda match: f"[{resolve(match.group(1))}]", source)
    cited = sorted(set(_CITE.findall(source)), key=lambda value: int(value[1:]))
    unknown = sorted(x for x in cited if x not in valid)
    stripped = []
    if unknown:
        unknown_set = set(unknown)
        source = _CITE.sub(lambda match: "" if match.group(1) in unknown_set else match.group(0), source)
        stripped.extend(unknown)
        source = re.sub(r"[ \t]+(?=[,.;:])", "", source)
        source = re.sub(r" {2,}", " ", source)
        cited = sorted(set(_CITE.findall(source)), key=lambda value: int(value[1:]))
        unknown = []
    allow_documented = bool(rp.get("allow_documented_claims"))
    if not allow_documented:
        stripped = cited
        source = _CITE.sub("", source)
        source = _SOURCE_LINE.sub("", source)
        source = _SOURCE_SECTION.sub("", source)
        source = re.sub(r"\n{3,}", "\n\n", source).strip()
        unknown = []
    elif not unknown:
        source = _compact_source_footer(source, cited, ep.get("selected_evidence") or [])
    return source, CitationAudit(cited, sorted(valid), remapped, sorted(set(preserved)), unknown, stripped, not unknown, str(ep.get("citation_namespace") or "canonical"))


def enforce_answer_contract(payload, canonical_plan):
    result = dict(payload or {})
    text, audit = finalize_citations(result.get("text", ""), canonical_plan)
    result["text"] = text
    allow = bool(((canonical_plan or {}).get("response_plan") or {}).get("allow_documented_claims"))
    internal = bool(result.get("internal_knowledge_used"))
    result["documented_evidence_used"] = allow and bool(audit.cited_ids) and audit.valid
    if internal:
        result["knowledge_mode"] = "documented_plus_internal" if result["documented_evidence_used"] else "internal_only"
    elif result["documented_evidence_used"]:
        result["knowledge_mode"] = "documented_only"
    return result, audit.to_dict()
