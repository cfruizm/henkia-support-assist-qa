"""Option C: bring vendor web pages into the Henkia Knowledge Engine (KE).

The KE has no web connector yet. This script reads the PaperCut pages that the
local index (Chroma) already covers, extracts their main text and prepares one
Markdown document per page with KE provenance metadata (reference_url,
document_title, document_date, document_kind).

Modes (run from the repository root with the venv; deps in requirements-sync.txt):

  --dry-run   Fetch and build documents into --out (no KE request). Review them.
  --discover  List the MCP tools a write-scoped key exposes (upload/ingest/delete),
              to wire the upload to the real tool schema. Prints no credentials.
  --upload    Upload what --dry-run prepared to --base (MCP subir_documento, one
              document per call, unchanged pages skipped by content hash);
              --ingest launches ingerir_base; --prune deletes only pages this
              script uploaded (name prefix) that left the manifest.

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


NAME_MARKER = "pcweb"
MANAGED_NAME_RE = re.compile(r"\[" + NAME_MARKER + r"-[0-9a-f]{8}\]\.md$")


def document_name(url: str, title: str = "") -> str:
    """KE document name: the page title plus a code derived from the URL.

    The KE search does not return document_title, so the name is what users see as
    the source title. The URL code keeps the name unique and stable (the name is the
    update key); a renamed page title creates a new name and --prune removes the old.
    """
    digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:8]
    clean = " ".join(re.sub(r'[\/:*?"<>|\[\]#%]+', " ", str(title or "")).split())[:150].strip(" .-")
    if not clean:
        parsed = urlparse(url)
        path = unicodedata.normalize("NFKD", parsed.path).encode("ascii", "ignore").decode().casefold()
        clean = re.sub(r"[^a-z0-9]+", "-", f"{parsed.netloc}-{path}").strip("-")[:150]
    return f"{clean} [{NAME_MARKER}-{digest}].md"


def local_file_name(url: str) -> str:
    """Short, stable file name for the prepared document on disk."""
    return hashlib.sha1(url.encode("utf-8")).hexdigest()[:16] + ".md"


def is_managed_name(name: str) -> bool:
    """Documents this script owns: current names and the first-version URL slugs."""
    return bool(MANAGED_NAME_RE.search(name or "")) or str(name or "").startswith(MANAGED_PREFIX)


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
    return {"name": document_name(page["url"], title), "text": body, "metadata": {k: v for k, v in metadata.items() if v}}


def dry_run(args) -> None:
    pages = index_pages(pathlib.Path(args.index), args.collection)
    if args.match:
        needles = [m.strip().casefold() for m in args.match.split(",") if m.strip()]
        pages = [p for p in pages if any(n in p["url"].casefold() for n in needles)]
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
        # Short file name on disk: long page titles exceeded the Windows path limit.
        file_name = local_file_name(page["url"])
        (out / "documents" / file_name).write_text(document["text"], encoding="utf-8")
        manifest.append({"name": document["name"], "file": file_name, "chars": len(document["text"]),
                         "metadata": document["metadata"]})
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


MANAGED_PREFIX = "www-papercut-com-"  # first-version names; see is_managed_name (nothing else is deleted)
UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
# The only MCP tools this script calls. Base or provider administration is never used.
ALLOWED_TOOLS = {"subir_documento", "ingerir_base", "listar_documentos", "borrar_documento"}


class McpClient:
    """Minimal MCP (Streamable HTTP, stateless) client for the KE write tools."""

    def __init__(self, key: str):
        import requests
        self.session = requests.Session()
        self.session.headers.update({"Accept": "application/json, text/event-stream", "Content-Type": "application/json",
                                     "MCP-Protocol-Version": "2025-06-18", "Authorization": f"Bearer {key}"})
        self.rid = 0
        self._rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                 "clientInfo": {"name": "ke-web-sync", "version": "1"}})

    def _rpc(self, method: str, params: dict) -> dict:
        self.rid += 1
        response = self.session.post(f"{KE_ROOT}/mcp", timeout=(10, 120),
                                     json={"jsonrpc": "2.0", "id": self.rid, "method": method, "params": params})
        text = response.content.decode("utf-8", errors="replace")
        if not response.ok:
            return {"error": {"message": f"http_{response.status_code}"}}
        for line in text.splitlines():
            if line.startswith("data:"):
                return json.loads(line[5:].strip())
        return json.loads(text) if text.strip().startswith("{") else {}

    def tool(self, name: str, arguments: dict) -> tuple[bool, str]:
        if name not in ALLOWED_TOOLS:
            raise ValueError(f"tool not allowed: {name}")
        reply = self._rpc("tools/call", {"name": name, "arguments": arguments})
        if reply.get("error"):
            return False, str(reply["error"].get("message") or reply["error"])[:300]
        result = reply.get("result") or {}
        text = "\n".join(c.get("text", "") for c in result.get("content") or [] if isinstance(c, dict))
        return not result.get("isError"), text

    def close(self) -> None:
        self.session.headers.pop("Authorization", None)
        self.session.close()


def upload(args) -> None:
    """Upload the documents prepared by --dry-run to one KE base, then ingest."""
    if not UUID_RE.match(args.base or ""):
        sys.exit("--base debe ser el uuid de la base destino.")
    out = pathlib.Path(args.out)
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    documents = manifest["documents_manifest"][: args.limit or None]
    state_path = pathlib.Path(args.state) if args.state else out / "upload_state.json"
    state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}
    client = McpClient(_write_key())
    uploaded = unchanged = failed = 0
    try:
        for position, entry in enumerate(documents, 1):
            name, content_hash = entry["name"], entry["metadata"].get("content_hash")
            if state.get(name) == content_hash:
                unchanged += 1
                continue
            text = (out / "documents" / entry.get("file", name)).read_text(encoding="utf-8")
            metadata = {k: str(v) for k, v in entry["metadata"].items() if v not in (None, "")}
            ok, detail = client.tool("subir_documento", {"base": args.base, "nombre": name, "contenido": text,
                                                         "codificacion": "texto", "metadatos": metadata})
            if ok:
                uploaded += 1
                state[name] = content_hash
                state_path.write_text(json.dumps(state, indent=1), encoding="utf-8")
            else:
                failed += 1
                print(f"  ERROR {name}: {detail}")
            print(f"[{position}/{len(documents)}] {'ok' if ok else 'fallo'} {name[:90]}")
        if args.prune:
            prune(client, args.base, {e["name"] for e in manifest["documents_manifest"]}, state, state_path)
        if args.ingest and uploaded:
            ok, detail = client.tool("ingerir_base", {"base": args.base})
            print("Ingesta:", "lanzada" if ok else "no lanzada", "|", detail[:300])
            if not ok and "4006" in detail:
                print("KE tiene otro trabajo en curso; cuando termine, ejecuta este script con --ingest-only --base", args.base)
    finally:
        client.close()
    print(f"Subidos {uploaded}, sin cambios {unchanged}, fallidos {failed}. Estado: {state_path}")


def ingest_only(args) -> None:
    """Launch ingerir_base alone. KE answers 409 (HENKIA-RAG-4006) while another job
    runs, e.g. the graph update a document deletion starts; run this afterwards."""
    if not UUID_RE.match(args.base or ""):
        sys.exit("--base debe ser el uuid de la base destino.")
    client = McpClient(_write_key())
    try:
        ok, detail = client.tool("ingerir_base", {"base": args.base})
    finally:
        client.close()
    print("Ingesta:", "lanzada" if ok else "no lanzada", "|", detail[:300])


def prune(client: McpClient, base: str, current: set[str], state: dict, state_path: pathlib.Path) -> None:
    """Delete documents this script uploaded whose page is no longer in the manifest."""
    ok, listing = client.tool("listar_documentos", {"base": base})
    if not ok:
        print("No se pudo listar la base; no se borra nada.", listing[:200])
        return
    names = {d.get("name") for d in (json.loads(listing).get("documentos") or [])}
    stale = sorted(n for n in names if n and is_managed_name(n) and n not in current)
    for name in stale:
        ok, detail = client.tool("borrar_documento", {"base": base, "nombre": name})
        print(f"Borrado {'ok' if ok else 'fallido'}: {name} {'' if ok else detail[:200]}")
        if ok:
            state.pop(name, None)
    state_path.write_text(json.dumps(state, indent=1), encoding="utf-8")


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--discover", action="store_true")
    mode.add_argument("--upload", action="store_true", help="Sube lo preparado por --dry-run (requiere --base)")
    mode.add_argument("--ingest-only", action="store_true", help="Solo lanza la ingesta de --base (p. ej. tras un 409)")
    parser.add_argument("--base", default="", help="uuid de la base KE destino")
    parser.add_argument("--ingest", action="store_true", help="Lanza la ingesta al terminar la subida")
    parser.add_argument("--prune", action="store_true", help="Borra páginas propias que ya no están en el manifiesto")
    parser.add_argument("--state", default="", help="Archivo de estado de subida (por defecto en --out)")
    parser.add_argument("--index", default=str(DEFAULT_INDEX))
    parser.add_argument("--collection", default=DEFAULT_COLLECTION)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--match", default="", help="Solo URLs que contengan alguno de estos textos (coma)")
    parser.add_argument("--delay", type=float, default=1.0, help="Segundos entre peticiones al sitio")
    parser.add_argument("--out", default="ke_web_sync_out")
    args = parser.parse_args(argv)
    if args.dry_run:
        dry_run(args)
    elif args.discover:
        discover(args)
    elif args.ingest_only:
        ingest_only(args)
    else:
        upload(args)


if __name__ == "__main__":
    main()
