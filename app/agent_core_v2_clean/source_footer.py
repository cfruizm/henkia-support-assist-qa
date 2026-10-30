from __future__ import annotations
from collections import OrderedDict
import re
from .source_access_policy import display_url, access_kind

# Remove only trailing source sections. The response body and inline [R#] citations remain intact.
_SOURCE_FOOTER = re.compile(
    r"(?is)\n\s*(?:#{1,6}\s*)?(?:\*\*)?Fuentes?\s+documental(?:es)?(?:\*\*)?\s*:?.*\Z"
)

def strip_generated_source_footer(text):
    value=str(text or "").rstrip()
    previous=None
    while previous!=value:
        previous=value
        value=_SOURCE_FOOTER.sub("",value).rstrip()
    return value

def _page(value):
    value=str(value or "").strip()
    return int(value) if value.isdigit() else value

def _list(values):
    numeric=sorted({x for x in values if isinstance(x,int)})
    other=sorted({str(x) for x in values if x not in (None,"") and not isinstance(x,int)})
    parts=[str(x) for x in numeric]+other
    if len(parts)==1:return "pág. "+parts[0]
    if len(parts)==2:return "págs. "+parts[0]+" y "+parts[1]
    return "págs. "+", ".join(parts[:-1])+" y "+parts[-1]

def _url(item):
    return display_url(item)

def compact_sources(evidence,cited_ids):
    by_id={str(x.get("id")):x for x in evidence or []};docs=OrderedDict()
    for rid in cited_ids or []:
        item=by_id.get(str(rid))
        if not item:continue
        url=_url(item)
        identity=url or str(item.get("source") or item.get("title") or rid)
        row=docs.setdefault(identity,{"title":str(item.get("title") or "Fuente sin título"),"pages":[],"url":url,"access_kind":access_kind(item)})
        raw=item.get("page") or (item.get("metadata") or {}).get("page_label") or (item.get("metadata") or {}).get("page")
        page=_page(raw)
        if page not in (None,"") and page not in row["pages"]:row["pages"].append(page)
    rows=[]
    for row in docs.values():
        title=row["title"]
        label=f"{title}, {_list(row['pages'])}" if row["pages"] else title
        if row["url"]:
            suffix=" (biblioteca interna)" if row.get("access_kind")=="internal_sharepoint" else ""
            rows.append(f"[{label}]({row['url']}){suffix}")
        elif row.get("access_kind")=="internal_restricted":
            rows.append(label+". Acceso interno restringido; biblioteca no configurada.")
        else:
            rows.append(label+".")
    if not rows:return ""
    if len(rows)==1:return "**Fuente documental:** "+rows[0]
    return "**Fuentes documentales**\n"+"\n".join("- "+x for x in rows)
