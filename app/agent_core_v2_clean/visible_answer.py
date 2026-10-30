from __future__ import annotations
import re

SOURCE_RE=re.compile(r"(?is)(?:^|\n)\s*\*\*Fuente(?:s)? documental(?:es)?:\*\*\s*(.+?)\s*$")
PARTIAL_RE=re.compile(r"(?ims)^\s*>?\s*(?:ℹ️\s*)?(?:\*\*)?Cobertura(?:\s+documental)?\s+parcial\s*:(?:\*\*)?\s*(.+?)(?=\n\n|\Z)")
INTERNAL_RE=re.compile(r"(?im)^\s*>?\s*(?:⚠️\s*)?(?:\*\*)?Orientación complementaria(?:\s+basada en conocimiento general del modelo)?(?:\*\*)?\s*:\s*(.*?)\s*$")
INTERNAL_LEGACY_RE=re.compile(r"(?im)^\s*⚠️\s*\*\*Orientación complementaria basada en conocimiento general del modelo\*\*\s*$")
ORPHAN_RE=re.compile(r"^\s*(?:\*{0,2}\s*)?(?:\d+[.)]|[-*])\s*(?:\*{1,2})?\s*$")
MALFORMED_NUMBER_RE=re.compile(r"(?m)^(\s*)\*\*(\d+)([.)])\s+([^\n*].*)$")


def _split_long(paragraph,max_chars=560):
    value=paragraph.strip()
    if len(value)<=max_chars or value.startswith(("#",">","- ","* ","```","|")) or re.match(r"^\d+[.)]\s",value):return value
    sentences=re.split(r"(?<=[.!?])\s+(?=[A-ZÁÉÍÓÚÜÑ0-9¿¡])",value)
    if len(sentences)<2:return value
    chunks=[];current=""
    for sentence in sentences:
        candidate=(current+" "+sentence).strip()
        if current and len(candidate)>max_chars:chunks.append(current);current=sentence
        else:current=candidate
    if current:chunks.append(current)
    return "\n\n".join(chunks)


def _normalize_code(text):
    def replace(match):
        language=(match.group(1) or "").strip();body=(match.group(2) or "").strip()
        if "\n" not in body and len(body)<=180:return f"`{body}`"
        return f"```{language}\n{body}\n```"
    return re.sub(r"```([^\n`]*)\n(.*?)```",replace,text,flags=re.S)


def _normalize_incomplete_numbering(text):
    """Remove unmatched bold markers without damaging valid numbered structures.

    A single residual `**1. sentence` is treated as a filtered one-item heading and
    loses the meaningless number. Multiple residual markers preserve their numbers
    as a normal ordered list. Properly closed Markdown such as `**1. Title**` is not
    matched and remains governed by the existing heading normalization.
    """
    matches=list(MALFORMED_NUMBER_RE.finditer(text))
    if not matches:return text,{"found":0,"strategy":None}
    single_first=len(matches)==1 and matches[0].group(2)=="1"
    def replace(match):
        indent,number,punctuation,content=match.groups()
        if single_first:return indent+content.strip()
        return f"{indent}{number}{punctuation} {content.strip()}"
    return MALFORMED_NUMBER_RE.sub(replace,text),{"found":len(matches),"strategy":"remove_single_residual_number" if single_first else "preserve_ordered_series"}


def format_visible_answer(text,answer_mode=None,knowledge_mode=None,finish_reason=None):
    original=str(text or "").replace("\r\n","\n").replace("\r","\n").strip()
    if not original:return original,{"applied":False,"reason":"empty"}
    source=None;match=SOURCE_RE.search(original)
    if match:source=match.group(1).strip();original=original[:match.start()].rstrip()
    partial=None;match=PARTIAL_RE.search(original)
    if match:partial=match.group(1).strip();original=PARTIAL_RE.sub("",original).strip()
    internal=False
    if INTERNAL_LEGACY_RE.search(original):
        internal=True;original=INTERNAL_LEGACY_RE.sub("",original).strip()
    else:
        match=INTERNAL_RE.search(original)
        if match:internal=True;original=INTERNAL_RE.sub("",original).strip()
    original=re.sub(r"(?m)^\s*\*\*(\d+[.)]\s*[^*\n]{2,100})\*\*\s*(?=\S)",lambda m:f"### {m.group(1).strip()}\n\n",original)
    original,incomplete=_normalize_incomplete_numbering(original)
    original=re.sub(r"(?im)\*\*(Validaciones finales|Siguiente paso|Resultado|Recomendación|Acciones|Requisitos):?\*\*\s*(?=\S)",lambda m:f"\n\n### {m.group(1)}\n\n",original)
    lines=[];in_fence=False;removed=False
    for line in original.splitlines():
        if line.strip().startswith("```"):in_fence=not in_fence
        if not in_fence and (ORPHAN_RE.match(line) or re.fullmatch(r"\s*\*{1,2}\s*\*{1,2}\s*",line)):
            removed=True;continue
        lines.append(line.rstrip())
    body="\n".join(lines)
    body=re.sub(r"(?m)^\s*\*\*(Validaciones finales|Siguiente paso|Resultado|Recomendación|Acciones|Requisitos):?\*\*\s*$",lambda m:f"### {m.group(1)}",body)
    body=_normalize_code(re.sub(r"\n{3,}","\n\n",body).strip())
    body=re.sub(r"\](?=\[R\d+\])","] ",body)
    body="\n\n".join(_split_long(p) for p in re.split(r"\n\n+",body) if p.strip()).strip()
    sections=[]
    if internal:sections.append("> ⚠️ **Orientación complementaria:** se usa conocimiento general porque la documentación disponible no cubre por completo la solicitud.")
    if partial:
        partial=re.sub(r"^se\s+","Se ",partial,flags=re.I)
        sections.append(f"> ℹ️ **Cobertura parcial:** {partial}")
    if body:sections.append(body)
    if source:sections.append(f"---\n\n*Fuente documental:* {source}")
    formatted=re.sub(r"\n{3,}","\n\n","\n\n".join(sections).strip())
    diagnostic={"applied":formatted!=str(text or "").strip(),"version":"q6_visible_answer_v1_3","internal_warning_compacted":internal,"internal_warning_icon":"⚠️" if internal else None,"partial_notice_repositioned":bool(partial),"partial_notice_icon":"ℹ️" if partial else None,"partial_variant_normalized":bool(partial),"incomplete_numbering_found":incomplete["found"],"incomplete_numbering_strategy":incomplete["strategy"],"source_deemphasized":bool(source),"orphan_structure_removed":removed,"screen_pdf_same_markdown":True}
    return formatted,diagnostic
