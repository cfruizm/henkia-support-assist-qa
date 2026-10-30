#!/usr/bin/env python3
"""
Build/rebuild Arus PrintAssist Chroma vectorstore from PDFs and optional controlled web crawling.

PDF-only:
  python scripts/build_vectorstore.py --pdf-dir knowledge_base_pdfs --output-dir vectorstore/chroma --force

PDF + controlled PaperCut/HP web crawl, intended for Colab:
  python scripts/build_vectorstore.py --pdf-dir /content/knowledge_base_pdfs --output-dir /content/vectorstore/chroma --enable-crawl --force
"""
from __future__ import annotations

import argparse, hashlib, json, re, shutil, sys
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse, urldefrag

from langchain_community.document_loaders import PyPDFLoader
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_huggingface import HuggingFaceEmbeddings
try:
    from langchain_chroma import Chroma
except Exception:
    from langchain_community.vectorstores import Chroma  # type: ignore

DEFAULT_EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
DEFAULT_CHUNK_SIZE = 800
DEFAULT_CHUNK_OVERLAP = 150
DEFAULT_COLLECTION_NAME = "langchain"

PDF_COLLECTIONS = {
    "DA Arus": {"vendor":"arus_internal","product":"sanitized_support_assets","collection_name":"DA Arus","source_type":"pdf","source_group":"core_support","priority":1,"public_or_sanitized":"sanitized"},
    "GAV Tracking": {"vendor":"gav","product":"gav_tracking","collection_name":"GAV Tracking","source_type":"pdf","source_group":"core_support","priority":1,"public_or_sanitized":"public"},
    "HP AC": {"vendor":"hp","product":"hp_access_control","collection_name":"HP AC","source_type":"pdf","source_group":"core_support","priority":1,"public_or_sanitized":"public"},
    "HP SDS": {"vendor":"hp","product":"sds","collection_name":"HP SDS","source_type":"pdf","source_group":"core_support","priority":1,"public_or_sanitized":"public"},
    "HP WJA": {"vendor":"hp","product":"web_jetadmin","collection_name":"HP WJA","source_type":"pdf","source_group":"core_support","priority":1,"public_or_sanitized":"public"},
}

SEED_PLANS = {
    "core_support": {
        "seed_urls": ["https://www.papercut.com/kb/Category/Troubleshooting", "https://www.papercut.com/support/known-issues/", "https://www.papercut.com/kb/"],
        "allowed_prefixes": ["https://www.papercut.com/kb/", "https://www.papercut.com/support/known-issues/"],
        "curated_urls": [
            "https://www.papercut.com/kb/Main/MissingOrDisappearingPrintJobs/",
            "https://www.papercut.com/kb/Main/JobsStuckWithStatusOfPrinting/",
            "https://www.papercut.com/kb/Main/PrintJobsNotHeld/",
            "https://www.papercut.com/kb/Main/AttemptedToBeUnpaused/",
            "https://www.papercut.com/kb/Main/DisappearingPrintQueues/",
            "https://www.papercut.com/kb/Main/UnableToAddAPrinter/",
            "https://www.papercut.com/kb/Main/ConnectingToTheWrongIPAddress/",
            "https://www.papercut.com/kb/Main/TroubleshootingEmbeddedDevicesMF/",
            "https://www.papercut.com/kb/Main/SwipeCardIssues/",
            "https://www.papercut.com/kb/Main/HoldforAuthentication/",
            "https://www.papercut.com/kb/Main/TemporarilyHiddenMessage/",
        ],
        "target_keywords": ["print","printer","job","jobs","queue","queues","device","devices","embedded","mobility","release","hold","disappear","missing","unpaused","addaprinter","add printer","authentication","swipecard","card"],
        "max_depth": 2, "max_pages": 120, "priority": 1, "source_group": "core_support",
    },
    "manual_reference": {
        "seed_urls": ["https://www.papercut.com/help/manuals/"],
        "allowed_prefixes": ["https://www.papercut.com/help/"],
        "curated_urls": [],
        "target_keywords": ["print","printer","queue","job","device","mobility","authentication","driver","release","embedded","scan","copier"],
        "deny_subpaths": ["https://www.papercut.com/help/manuals/job-ticketing", "https://www.papercut.com/help/manuals/mobility-print", "https://www.papercut.com/help/manuals/new/", "https://www.papercut.com/help/manuals/print-deploy/"],
        "max_depth": 1, "max_pages": 50, "priority": 3, "source_group": "manual_reference",
    },
    "hp_support_curated": {
        "seed_urls": [], "allowed_prefixes": ["https://support.hp.com/"], "curated_urls": [],
        "target_keywords": ["printer","queue","spooler","stuck","offline","driver","setup","diagnose","fix","print"],
        "max_depth": 0, "max_pages": 30, "priority": 1, "source_group": "core_support",
    },
}
DENY_PATTERNS = [r"/login", r"/search", r"/contact", r"/message", r"/blog", r"/portal", r"/store", r"/learn", r"/staging", r"\?utm_", r"#"]
NON_INDEXABLE_ROOTS = {"https://www.papercut.com/kb/", "https://www.papercut.com/help/manuals/", "https://www.papercut.com/support/known-issues/"}
REQUEST_TIMEOUT = 15
HEADERS = {"User-Agent": "ArusPrintAssistAcademicCrawler/0.4"}

@dataclass
class BuildStats:
    pdf_files_found:int=0; pdf_files_loaded:int=0; pdf_files_skipped:int=0; pages_loaded:int=0; web_pages_visited:int=0; web_docs_indexed:int=0; chunks_created:int=0

def infer_pdf_component_and_family(filename: str, folder_name: str) -> tuple[str,str]:
    text=filename.lower(); component="general"; family="general_document"
    if "dca" in text: component="dca"
    elif "sda" in text: component="sda"
    elif "jamc" in text: component="jamc"
    elif "monitor" in text: component="monitor"
    elif "portal" in text: component="portal"
    elif any(t in text for t in ["security","seguridad","protocol"]): component="security"
    elif any(t in text for t in ["requirement","requer","requisito"]): component="requirements"
    elif any(t in text for t in ["release","highlight"]): component="release_notes"
    elif any(t in text for t in ["install","instal"]): component="installation"
    elif any(t in text for t in ["admin","administrator"]): component="admin"
    elif any(t in text for t in ["troubleshoot","problema","troubleshooting"]): component="troubleshooting"
    elif "operación" in text or "operacion" in text: component="internal_support_asset"
    if any(t in text for t in ["guide","guía","guia","manual"]): family="guide"
    elif any(t in text for t in ["release","highlight"]): family="release_notes"
    elif "brochure" in text or "folleto" in text: family="brochure"
    elif any(t in text for t in ["requirement","requer","requisito"]): family="requirements"
    elif "security" in text or "seguridad" in text: family="security_document"
    elif "checklist" in text: family="checklist"
    if folder_name == "DA Arus" and component == "general": component="internal_support_asset"
    return component, family

def infer_title(pdf_path: Path) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[_]+", " ", pdf_path.stem)).strip()

def get_pdf_collection_metadata(pdf_path: Path, pdf_dir: Path, include_unknown: bool=False):
    parts=pdf_path.relative_to(pdf_dir).parts; folder=parts[0] if parts else None
    if folder in PDF_COLLECTIONS: meta=PDF_COLLECTIONS[folder]
    elif include_unknown:
        folder=folder or "Unknown"; meta={"vendor":"unknown","product":"unknown","collection_name":folder,"source_type":"pdf","source_group":"uncategorized","priority":3,"public_or_sanitized":"unknown"}
    else: return folder, None
    component,family=infer_pdf_component_and_family(pdf_path.name, folder)
    return folder,{**meta,"folder_origin":folder,"component":component,"document_family":family,"title":infer_title(pdf_path)}

def load_pdf_documents(pdf_dir: Path, include_unknown: bool=False):
    stats=BuildStats(); docs=[]; skipped=[]; pdfs=sorted(pdf_dir.rglob("*.pdf")); stats.pdf_files_found=len(pdfs)
    for pdf_path in pdfs:
        _,meta=get_pdf_collection_metadata(pdf_path,pdf_dir,include_unknown)
        if meta is None:
            skipped.append(str(pdf_path)); stats.pdf_files_skipped+=1; continue
        try: pages=PyPDFLoader(str(pdf_path)).load()
        except Exception as exc:
            skipped.append(f"{pdf_path} :: {type(exc).__name__}: {exc}"); stats.pdf_files_skipped+=1; continue
        stats.pdf_files_loaded+=1; stats.pages_loaded+=len(pages)
        for d in pages:
            d.metadata.update(meta); d.metadata["source"]=str(pdf_path); d.metadata["source_name"]=pdf_path.name; d.metadata["canonical_url"]=d.metadata.get("source"); d.metadata["domain"]="local_pdf"; d.metadata["seed_origin"]="local_pdf"
            page=d.metadata.get("page")
            if page is not None and "page_label" not in d.metadata:
                try: d.metadata["page_label"]=str(int(page)+1)
                except Exception: d.metadata["page_label"]=str(page)
            docs.append(d)
    return docs,stats,skipped

def normalize_url(url:str)->str:
    url,_=urldefrag(url); return url

def is_allowed_url_for_plan(url:str, plan:dict)->bool:
    if not any(url.startswith(p) for p in plan["allowed_prefixes"]): return False
    if any(re.search(p,url,flags=re.I) for p in DENY_PATTERNS): return False
    if any(url.startswith(p) for p in plan.get("deny_subpaths",[])): return False
    return True

def text_matches_target_keywords(text:str, keywords:list[str])->bool:
    t=(text or "").lower(); return any(k.lower() in t for k in keywords)

def url_matches_target_keywords(url:str, keywords:list[str])->bool:
    u=(url or "").lower().replace("-","").replace("_",""); return any(k.lower().replace(" ","") in u for k in keywords)

def is_target_relevant_document(url,title,text,plan):
    if url in [normalize_url(u) for u in plan.get("curated_urls",[])]: return True
    return text_matches_target_keywords(title or "",plan["target_keywords"]) or url_matches_target_keywords(url,plan["target_keywords"]) or text_matches_target_keywords(text or "",plan["target_keywords"])

def should_follow_child_url(child_url, plan, parent_depth):
    if any(child_url.startswith(p) for p in plan.get("deny_subpaths",[])): return False
    if child_url in [normalize_url(u) for u in plan.get("curated_urls",[])]: return True
    if url_matches_target_keywords(child_url,plan["target_keywords"]): return True
    return parent_depth == 0

def import_crawl_dependencies():
    try:
        import requests, trafilatura
        from bs4 import BeautifulSoup
        return requests,trafilatura,BeautifulSoup
    except Exception as exc:
        raise RuntimeError("Install crawling extras: requests beautifulsoup4 lxml trafilatura") from exc

def fetch_html(url, requests_module):
    try:
        r=requests_module.get(url,headers=HEADERS,timeout=REQUEST_TIMEOUT)
        return r.text if r.status_code == 200 else None
    except Exception: return None

def extract_child_links(base_url, html, plan, BeautifulSoup):
    soup=BeautifulSoup(html,"lxml"); links=set()
    for tag in soup.find_all("a",href=True):
        u=normalize_url(urljoin(base_url,tag["href"].strip()))
        if is_allowed_url_for_plan(u,plan): links.add(u)
    return sorted(links)

def extract_main_content(html,trafilatura_module):
    txt=trafilatura_module.extract(html,output_format="txt",with_metadata=False)
    md=trafilatura_module.extract_metadata(html); title=getattr(md,"title",None) if md is not None else None
    return txt,title

def compute_content_hash(text): return hashlib.sha256(text.encode("utf-8")).hexdigest()

def is_hub_like_page(url,title,text):
    title_l=(title or "").strip().lower(); text_l=(text or "").strip().lower()
    if title_l in {"knowledge base","help center","product manuals","troubleshooting articles","end user articles","known issues"}: return True
    if text_l.startswith("contents") or "this is a collection of articles" in text_l or "featured articles" in text_l: return True
    if "choose your language" in text_l and len(text_l)<2500: return True
    if text and text.count("- ")>=25 and len(text_l)<6000: return True
    return url in NON_INDEXABLE_ROOTS

def infer_web_product(url,vendor,title,text):
    joined=f"{url} {title or ''} {(text or '')[:1200]}".lower()
    if vendor=="papercut":
        if "hive" in joined: return "papercut_hive"
        if "papercut ng" in joined or " ng" in joined: return "papercut_ng"
        return "papercut_mf"
    if vendor=="hp": return "hp_printers"
    return "unknown"

def infer_web_document_family(source_type):
    return {"kb_article":"kb_article","known_issue":"known_issue","troubleshooting":"troubleshooting","manual":"guide","hp_support":"support_article"}.get(source_type,"web_document")

def crawl_documents(plan_name, plan):
    requests_module,trafilatura_module,BeautifulSoup=import_crawl_dependencies(); visited=set(); docs=[]
    queue=[(normalize_url(u),0,normalize_url(u)) for u in list(plan["seed_urls"])+list(plan.get("curated_urls",[]))]
    while queue and len(visited)<plan["max_pages"]:
        url,depth,seed=queue.pop(0)
        if url in visited or depth>plan["max_depth"] or not is_allowed_url_for_plan(url,plan): continue
        print(f"[{plan_name.upper()}] Visiting {len(visited)+1}/{plan['max_pages']} | depth={depth} | {url}"); visited.add(url)
        html=fetch_html(url,requests_module)
        if html is None: print("  -> skipped download failed"); continue
        text,title=extract_main_content(html,trafilatura_module)
        if text and len(text.strip())>=300:
            domain=urlparse(url).netloc; vendor="papercut" if "papercut" in domain else "hp" if "hp.com" in domain else "unknown"
            if "/support/known-issues/" in url: source_type="known_issue"
            elif "/Category/Troubleshooting" in url or "/Troubleshooting" in url: source_type="troubleshooting"
            elif "/help/manuals/" in url: source_type="manual"
            elif "/kb/" in url: source_type="kb_article"
            elif "support.hp.com" in url: source_type="hp_support"
            else: source_type="web_doc"
            if not is_hub_like_page(url,title,text) and is_target_relevant_document(url,title,text,plan):
                product=infer_web_product(url,vendor,title,text)
                docs.append({"source_url":url,"canonical_url":url,"domain":domain,"vendor":vendor,"product":product,"component":"web_support","document_family":infer_web_document_family(source_type),"collection_name":"PaperCut Web" if vendor=="papercut" else "HP Support Web" if vendor=="hp" else "Web","folder_origin":"web_crawl","source_type":source_type,"source_group":plan["source_group"],"priority":plan["priority"],"title":title,"seed_origin":seed,"crawl_depth":depth,"retrieved_at":datetime.now().isoformat(),"content_hash":compute_content_hash(text),"page_content":text})
                print(f"  -> indexed chars={len(text)} type={source_type} product={product}")
            else: print("  -> discovery/skipped")
        else: print("  -> skipped no useful text")
        for child in extract_child_links(url,html,plan,BeautifulSoup):
            if child not in visited and all(child!=q[0] for q in queue) and should_follow_child_url(child,plan,depth): queue.append((child,depth+1,seed))
    print(f"[{plan_name.upper()}] finished visited={len(visited)} indexed={len(docs)}")
    return docs,len(visited)

def convert_web_docs_to_langchain(web_docs):
    return [Document(page_content=d["page_content"], metadata={**{k:v for k,v in d.items() if k!="page_content"}, "source":d["source_url"]}) for d in web_docs]

def run_crawl(plans, outdir):
    all_docs=[]; stats={}; outdir.mkdir(parents=True,exist_ok=True)
    for name in plans:
        docs,visited=crawl_documents(name,SEED_PLANS[name]); all_docs.extend(docs); stats[name]={"visited":visited,"indexed":len(docs)}
        (outdir/f"{name}_docs.json").write_text(json.dumps(docs,ensure_ascii=False,indent=2),encoding="utf-8")
    summary={"vendor_counts":dict(Counter(d.get("vendor") for d in all_docs)),"product_counts":dict(Counter(d.get("product") for d in all_docs)),"source_type_counts":dict(Counter(d.get("source_type") for d in all_docs)),"source_group_counts":dict(Counter(d.get("source_group") for d in all_docs)),"plan_stats":stats}
    (outdir/"active_web_docs.json").write_text(json.dumps(all_docs,ensure_ascii=False,indent=2),encoding="utf-8")
    (outdir/"crawl_summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding="utf-8")
    return convert_web_docs_to_langchain(all_docs),summary

def build_vectorstore(docs, output_dir, embedding_model_name, chunk_size, chunk_overlap, collection_name):
    chunks=RecursiveCharacterTextSplitter(chunk_size=chunk_size,chunk_overlap=chunk_overlap).split_documents(docs)
    emb=HuggingFaceEmbeddings(model_name=embedding_model_name)
    vs=Chroma.from_documents(documents=chunks,embedding=emb,collection_name=collection_name,persist_directory=str(output_dir))
    if hasattr(vs,"persist"):
        try: vs.persist()
        except Exception: pass
    return chunks

def write_manifest(output_dir,args,stats,chunks_count,skipped,crawl_summary):
    manifest={"created_at":datetime.now().isoformat(),"pdf_dir":str(Path(args.pdf_dir).resolve()),"output_dir":str(output_dir.resolve()),"collection_name":args.collection_name,"embedding_model_name":args.embedding_model,"chunk_size":args.chunk_size,"chunk_overlap":args.chunk_overlap,"include_unknown":args.include_unknown,"enable_crawl":args.enable_crawl,"crawl_plans":args.crawl_plans,"stats":stats.__dict__|{"chunks_created":chunks_count},"skipped":skipped,"crawl_summary":crawl_summary,"known_pdf_collections":PDF_COLLECTIONS}
    output_dir.mkdir(parents=True,exist_ok=True); path=output_dir/"build_manifest.json"; path.write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding="utf-8"); return path

def parse_args(argv):
    ap=argparse.ArgumentParser(description="Build Arus PrintAssist vectorstore from PDFs and optional controlled web crawl.")
    ap.add_argument("--pdf-dir",default="knowledge_base_pdfs"); ap.add_argument("--output-dir",default="vectorstore/chroma")
    ap.add_argument("--embedding-model",default=DEFAULT_EMBEDDING_MODEL); ap.add_argument("--chunk-size",type=int,default=DEFAULT_CHUNK_SIZE); ap.add_argument("--chunk-overlap",type=int,default=DEFAULT_CHUNK_OVERLAP); ap.add_argument("--collection-name",default=DEFAULT_COLLECTION_NAME)
    ap.add_argument("--include-unknown",action="store_true"); ap.add_argument("--force",action="store_true"); ap.add_argument("--dry-run",action="store_true")
    ap.add_argument("--enable-crawl",action="store_true"); ap.add_argument("--crawl-plans",nargs="+",default=["core_support","manual_reference","hp_support_curated"],choices=sorted(SEED_PLANS.keys())); ap.add_argument("--crawl-output-dir",default="crawl_output")
    return ap.parse_args(argv)

def main(argv=None):
    args=parse_args(argv or sys.argv[1:]); pdf_dir=Path(args.pdf_dir).expanduser().resolve(); output_dir=Path(args.output_dir).expanduser().resolve(); crawl_out=Path(args.crawl_output_dir).expanduser().resolve()
    if not pdf_dir.exists(): print(f"[ERROR] PDF directory not found: {pdf_dir}",file=sys.stderr); return 2
    if output_dir.exists() and args.force and not args.dry_run: shutil.rmtree(output_dir)
    if output_dir.exists() and any(output_dir.iterdir()) and not args.force and not args.dry_run: print(f"[ERROR] Output exists: {output_dir}. Use --force",file=sys.stderr); return 2
    print("[INFO] PDF directory:",pdf_dir); print("[INFO] Output directory:",output_dir); print("[INFO] Crawling enabled:",args.enable_crawl)
    pdf_docs,stats,skipped=load_pdf_documents(pdf_dir,args.include_unknown)
    print("[INFO] PDFs found/loaded/skipped/pages:",stats.pdf_files_found,stats.pdf_files_loaded,stats.pdf_files_skipped,stats.pages_loaded)
    web_docs=[]; crawl_summary=None
    if args.enable_crawl:
        web_docs,crawl_summary=run_crawl(args.crawl_plans,crawl_out); stats.web_docs_indexed=len(web_docs); stats.web_pages_visited=sum(v.get("visited",0) for v in (crawl_summary or {}).get("plan_stats",{}).values())
        print("[INFO] Web docs indexed/pages visited:",stats.web_docs_indexed,stats.web_pages_visited)
    raw_docs=pdf_docs+web_docs
    if skipped: print("[WARN] skipped PDFs sample:", skipped[:10])
    if not raw_docs: print("[ERROR] No documents loaded",file=sys.stderr); return 2
    if args.dry_run: print("[INFO] Dry-run raw docs:",len(raw_docs)); return 0
    chunks=build_vectorstore(raw_docs,output_dir,args.embedding_model,args.chunk_size,args.chunk_overlap,args.collection_name); stats.chunks_created=len(chunks)
    manifest=write_manifest(output_dir,args,stats,len(chunks),skipped,crawl_summary)
    print("[OK] Vectorstore built:",output_dir); print("[OK] Raw docs/chunks:",len(raw_docs),len(chunks)); print("[OK] Manifest:",manifest); return 0

if __name__ == "__main__":
    raise SystemExit(main())
