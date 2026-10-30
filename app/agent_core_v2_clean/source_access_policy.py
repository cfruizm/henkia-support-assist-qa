from __future__ import annotations
from pathlib import Path
from urllib.parse import urlparse

_MAX_PDF_BYTES=15*1024*1024
_MAX_ACTIONS=3
_DOWNLOADABLE_VENDORS={"hp","gav"}
_INTERNAL_MARKERS=("da arus","arus_internal","/da arus/","\\da arus\\")
_LIBRARY_URL=""
_PDF_ROOT=Path("data/knowledge_base_pdfs")


def _secret_get(secrets,key,default=""):
    try:
        direct=secrets.get(key)
        if direct not in (None,""):return direct
    except Exception:pass
    try:
        group=secrets.get("source_links") or {}
        return group.get(key,default)
    except Exception:return default


def _safe_http_url(value):
    try:
        parsed=urlparse(str(value or "").strip())
        return parsed.scheme in {"http","https"} and bool(parsed.netloc)
    except Exception:return False


def configure_source_access(secrets=None,pdf_root=None):
    global _LIBRARY_URL,_PDF_ROOT
    value=str(_secret_get(secrets or {},"internal_document_library_url","") or "").strip()
    _LIBRARY_URL=value if _safe_http_url(value) else ""
    if pdf_root:_PDF_ROOT=Path(pdf_root)
    return {"internal_document_library_configured":bool(_LIBRARY_URL),"pdf_root":str(_PDF_ROOT)}


def _metadata(item):return dict((item or {}).get("metadata") or {})
def _combined(item):
    md=_metadata(item)
    return " ".join(str(x or "") for x in (item.get("source"),item.get("url"),item.get("title"),md.get("source"),md.get("canonical_url"),md.get("source_url"),md.get("vendor"),md.get("organization"))).casefold()

def is_internal(item):
    md=_metadata(item);vendor=str(md.get("vendor") or "").casefold();access=str(md.get("source_access") or md.get("access") or "").casefold()
    return vendor=="arus_internal" or access in {"internal","restricted","internal_sharepoint"} or any(x in _combined(item) for x in _INTERNAL_MARKERS)

def public_url(item):
    if is_internal(item):return ""
    md=_metadata(item)
    for value in (item.get("url"),md.get("canonical_url"),md.get("source_url"),item.get("source")):
        value=str(value or "").strip()
        if _safe_http_url(value):return value
    return ""

def display_url(item):
    if is_internal(item):return _LIBRARY_URL
    return public_url(item)

def access_kind(item):
    if is_internal(item):return "internal_sharepoint" if _LIBRARY_URL else "internal_restricted"
    return "public_url" if public_url(item) else "reference_only"

def _approved_download_vendor(item,source_value):
    md=_metadata(item);vendor=str(md.get("vendor") or "").casefold().strip()
    if vendor in _DOWNLOADABLE_VENDORS:return vendor
    normalized="/"+str(source_value or "").replace("\\","/").casefold().strip("/")
    # Fallback only from controlled provider folders. Never authorize from title text.
    if "/knowledge_base_pdfs/hp/" in normalized or "/knowledge_base_pdfs/hp sds/" in normalized:return "hp"
    if "/knowledge_base_pdfs/gav/" in normalized:return "gav"
    return ""

def _relative_pdf(item):
    if is_internal(item):return None
    md=_metadata(item)
    value=str(item.get("source") or item.get("url") or md.get("canonical_url") or md.get("source_url") or "").replace("\\","/").strip()
    if _approved_download_vendor(item,value) not in _DOWNLOADABLE_VENDORS:return None
    if not value.casefold().endswith(".pdf"):return None
    marker="knowledge_base_pdfs/";idx=value.casefold().find(marker)
    relative=Path(value[idx+len(marker):] if idx>=0 else Path(value).name)
    if relative.is_absolute() or ".." in relative.parts:return None
    return relative

def downloadable_path(item):
    relative=_relative_pdf(item)
    if relative is None:return None
    try:
        root=_PDF_ROOT.resolve();path=(root/relative).resolve();path.relative_to(root)
        if not path.is_file() or path.stat().st_size>_MAX_PDF_BYTES:return None
        return path
    except Exception:return None

def source_actions(evidence):
    rows=[];seen=set()
    for item in evidence or []:
        title=str(item.get("title") or "Fuente documental").strip();kind=access_kind(item);url=display_url(item);path=downloadable_path(item)
        key=(title,url,str(path or ""))
        if key in seen:continue
        seen.add(key);rows.append({"title":title,"kind":kind,"url":url,"download_path":str(path) if path else None})
        if len(rows)>=_MAX_ACTIONS:break
    return rows

def render_latest_source_actions(st,store):
    context=store.get("answer_context") or {};evidence=context.get("current_answer_cited_evidence") or context.get("cited_evidence") or []
    downloads=[row for row in source_actions(evidence) if row.get("download_path")]
    if not downloads:return
    # Navigable public and SharePoint links already live in the documentary footer.
    # Local provider PDFs require a Streamlit download control, shown directly.
    for index,row in enumerate(downloads,1):
        path=Path(row["download_path"])
        st.download_button(
            f"Descargar fuente documental: {row['title']}",
            data=path.read_bytes(),file_name=path.name,mime="application/pdf",
            key=f"source_pdf_{index}_{path.name}",use_container_width=True,
        )
