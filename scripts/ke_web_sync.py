"""Option C: bring vendor web pages into the Henkia Knowledge Engine (KE).

The KE has no web connector yet. This script reads the PaperCut pages that the
local index (Chroma) already covers, extracts their main text and prepares one
Markdown document per page with KE provenance metadata (reference_url,
document_title, document_date, document_kind).

Modes (run from the repository root with the venv; deps in requirements-sync.txt):

  --dry-run   Fetch and build documents into --out (no KE request). Review them.
  --discover  List the MCP tools a write-scoped key exposes (upload/ingest/delete),
              to wire the upload to the real tool schema. Prints no credentials.

The write key is never stored: it is read from HENKIA_KE_WRITE_KEY or typed
hidden. It must be a separate M2M key with kb:write and ingest on the target
base only; the app keeps its read-only key.
"""
from __future__ import annotations

import argparse
import getpass
import hashlib
import json
import os
import pathlib
import re
import sqlite3
import sys
import time
import unicodedata
from urllib import robotparser
from urllib.parse import urldefrag, urlparse

USER_AGENT = "HenkiaSupportAssistKESync/1.0"
DEFAULT_INDEX = pathlib.Path("data/vectorstore/chroma.sqlite3")
DEFAULT_COLLECTION = "Papercut Web"
KE_ROOT = "https://api-ke.lab.henkia.com"
MIN_TEXT_CHARS = 200
MAX_TEXT_CHARS = 900_000  # KE accepts up to 1,000,000 per document


def index_pages(index_path: pathlib.Path, collection: str) -> list[dict]:
    """Distinct web pages of one collection in the local index (read-only)."""
    uri = f"file:{index_path.resolve().as_posix()}?mode=ro&immutable=1"
    con = sqlite3.connect(uri, uri=True)
    try:
        rows = con.execute(
            "select id, key, string_value from embedding_metadata "
            "where key in ('canonical_url','source','title','source_type','collection_name','product')"
        ).fetchall()
    finally:
        con.close()
    by_id: dict[int, dict] = {}
    for row_id, key, value in rows:
        by_id.setdefault(row_id, {})[key] = value
    pages: dict[str, dict] = {}
    for meta in by_id.values():
        if meta.get("collection_name") != collection:
            continue
        url = urldefrag(str(meta.get("canonical_url") or meta.get("source") or ""))[0]
        if not url.startswith(("http://", "https://")):
            continue
        pages.setdefault(url, {"url": url, "title": meta.get("title") or "", "source_type": meta.get("source_type") or "",
                               "product": meta.get("product") or ""})
    return sorted(pages.values(), key=lambda p: p["url"])


def document_name(url: str) -> str:
    """Stable KE document name from the URL (the name is the update key)."""
    parsed = urlparse(url)
    path = unicodedata.normalize("NFKD", parsed.path).encode("ascii", "ignore").decode().casefold()
    slug = re.sub(r"[^a-z0-9]+", "-", f"{parsed.netloc}-{path}").strip("-")
    digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:8]
    return f"{slug[:180]}-{digest}.md"


def _date(value) -> str | None:
    text = str(value or "")
    match = re.match(r"(\d{4}-\d{2}-\d{2})", text)
    return match.group(1) if match else None


class Fetcher:
    """Polite fetcher: robots.txt per host, fixed delay between requests."""

    def __init__(self, delay: float):
        import requests
        self.session = requests.Session()
        self.session.headers["User-Agent"] = USER_AGENT
        self.delay = delay
        self.robots: dict[str, robotparser.RobotFileParser] = {}
        self.last = 0.0

    def allowed(self, url: str) -> bool:
        host = urlparse(url)
        key = f"{host.scheme}://{host.netloc}"
        if key not in self.robots:
            parser = robotparser.RobotFileParser(f"{key}/robots.txt")
            try:
                parser.read()
            except Exception:
                parser = None
            self.robots[key] = parser
        parser = self.robots[key]
        return True if parser is None else parser.can_fetch(USER_AGENT, url)

    def get(self, url: str) -> tuple[int | None, str]:
        wait = self.delay - (time.monotonic() - self.last)
        if wait > 0:
            time.sleep(wait)
        self.last = time.monotonic()
        try:
            response = self.session.get(url, timeout=(10, 30))
        except Exception as exc:
            return None, type(exc).__name__
        return response.status_code, response.text if response.ok else ""


def build_document(page: dict, html: str) -> dict | None:
    import trafilatura
    text = trafilatura.extract(html, output_format="markdown", include_tables=True, with_metadata=False) or ""
    if len(text.strip()) < MIN_TEXT_CHARS:
        return None
    meta = trafilatura.extract_metadata(html)
    title = (getattr(meta, "title", None) or page.get("title") or "").strip()
    body = f"# {title}\n\nFuente: {page['url']}\n\n{text.strip()}"[:MAX_TEXT_CHARS] if title else text.strip()[:MAX_TEXT_CHARS]
    metadata = {
        "reference_url": page["url"],
        "document_title": title or None,
        "document_kind": page.get("source_type") or "web_page",
        "vendor": "papercut",
        "product": page.get("product") or None,
        "content_hash": hashlib.sha256(body.encode("utf-8")).hexdigest(),
    }
    document_date = _date(getattr(meta, "date", None))
    if document_date:
        metadata["document_date"] = document_date
    return {"name": document_name(page["url"]), "text": body, "metadata": {k: v for k, v in metadata.items() if v}}


def dry_run(args) -> None:
    pages = index_pages(pathlib.Path(args.index), args.collection)
    if args.limit:
        pages = pages[: args.limit]
    out = pathlib.Path(args.out)
    (out / "documents").mkdir(parents=True, exist_ok=True)
    fetcher = Fetcher(args.delay)
    manifest, skipped = [], []
    for position, page in enumerate(pages, 1):
        if not fetcher.allowed(page["url"]):
            skipped.append({"url": page["url"], "reason": "robots_disallow"})
            continue
        status, html = fetcher.get(page["url"])
        document = build_document(page, html) if status == 200 else None
        if document is None:
            skipped.append({"url": page["url"], "reason": f"http_{status}" if status != 200 else "too_little_text"})
            continue
        (out / "documents" / document["name"]).write_text(document["text"], encoding="utf-8")
        manifest.append({"name": document["name"], "chars": len(document["text"]), "metadata": document["metadata"]})
        print(f"[{position}/{len(pages)}] ok {document['name'][:80]} ({len(document['text'])} chars)")
    summary = {"pages": len(pages), "documents": len(manifest), "skipped": skipped, "documents_manifest": manifest}
    (out / "manifest.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"Documentos: {len(manifest)} de {len(pages)} páginas; omitidas: {len(skipped)}. Manifiesto: {out / 'manifest.json'}")


def _write_key() -> str:
    key = os.environ.get("HENKIA_KE_WRITE_KEY") or getpass.getpass("Key de escritura de KE (no se mostrará): ")
    key = key.strip()
    if not key:
        sys.exit("Sin key de escritura.")
    return key


def discover(args) -> None:
    import requests
    key = _write_key()
    headers = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json",
               "MCP-Protocol-Version": "2025-06-18", "Authorization": f"Bearer {key}"}

    def call(method, params, rid):
        response = requests.post(f"{KE_ROOT}/mcp", headers=headers, timeout=(10, 60),
                                 json={"jsonrpc": "2.0", "id": rid, "method": method, "params": params})
        text = response.content.decode("utf-8", errors="replace")
        for line in text.splitlines():
            if line.startswith("data:"):
                return response.status_code, json.loads(line[5:].strip())
        return response.status_code, (json.loads(text) if text.strip().startswith("{") else {})

    status, _ = call("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                    "clientInfo": {"name": "ke-web-sync", "version": "1"}}, 1)
    print("initialize:", status)
    status, listing = call("tools/list", {}, 2)
    tools = ((listing.get("result") or {}).get("tools") or [])
    key = None
    headers.pop("Authorization", None)
    words = ("subir", "upload", "ingest", "inger", "borrar", "eliminar", "delete", "documento", "crear_base")
    write_tools = {t["name"]: t.get("inputSchema") for t in tools if any(w in t.get("name", "") for w in words)}
    pathlib.Path(args.out).mkdir(parents=True, exist_ok=True)
    target = pathlib.Path(args.out) / "ke_write_tools.json"
    target.write_text(json.dumps({"all_tools": [t.get("name") for t in tools], "write_tools": write_tools},
                                 ensure_ascii=False, indent=1), encoding="utf-8")
    print("Herramientas:", ", ".join(t.get("name", "") for t in tools))
    print("Esquemas de subida/ingesta guardados en", target)


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--discover", action="store_true")
    parser.add_argument("--index", default=str(DEFAULT_INDEX))
    parser.add_argument("--collection", default=DEFAULT_COLLECTION)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--delay", type=float, default=1.0, help="Segundos entre peticiones al sitio")
    parser.add_argument("--out", default="ke_web_sync_out")
    args = parser.parse_args(argv)
    dry_run(args) if args.dry_run else discover(args)


if __name__ == "__main__":
    main()
