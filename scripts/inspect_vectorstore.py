#!/usr/bin/env python3
"""
Inspect an Arus PrintAssist Chroma vectorstore without calling the LLM.

Typical usage:

    python scripts/inspect_vectorstore.py --vectorstore-dir vectorstore/chroma

Run a retrieval smoke test:

    python scripts/inspect_vectorstore.py \
      --vectorstore-dir vectorstore/chroma \
      --query "¿Qué es HP Access Control?"
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

from langchain_huggingface import HuggingFaceEmbeddings

try:
    from langchain_chroma import Chroma
except Exception:  # pragma: no cover - compatibility fallback
    from langchain_community.vectorstores import Chroma  # type: ignore


DEFAULT_EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
DEFAULT_COLLECTION_NAME = "langchain"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Inspect Chroma vectorstore metadata and optional retrieval.")
    parser.add_argument("--vectorstore-dir", required=True, help="Chroma persistence directory.")
    parser.add_argument("--embedding-model", default=DEFAULT_EMBEDDING_MODEL, help="Embedding model used by the vectorstore.")
    parser.add_argument("--collection-name", default=DEFAULT_COLLECTION_NAME, help="Chroma collection name.")
    parser.add_argument("--query", default=None, help="Optional natural-language query for retrieval smoke test.")
    parser.add_argument("--top-k", type=int, default=5, help="Number of retrieval results for --query.")
    return parser.parse_args()


def summarize_metadata(metadatas: list[dict]) -> dict:
    fields = ["vendor", "product", "component", "document_family", "collection_name", "folder_origin", "source_group"]
    summary = {}
    for field in fields:
        counter = Counter(str(md.get(field, "<missing>")) for md in metadatas if md is not None)
        summary[field] = dict(counter.most_common(20))
    return summary


def main() -> int:
    args = parse_args()
    vectorstore_dir = Path(args.vectorstore_dir).expanduser().resolve()

    if not vectorstore_dir.exists():
        print(f"[ERROR] Vectorstore directory not found: {vectorstore_dir}")
        return 2

    embedding = HuggingFaceEmbeddings(model_name=args.embedding_model)
    vectorstore = Chroma(
        collection_name=args.collection_name,
        persist_directory=str(vectorstore_dir),
        embedding_function=embedding,
    )

    collection = vectorstore._collection
    count = collection.count()
    print("[INFO] Vectorstore:", vectorstore_dir)
    print("[INFO] Collection:", collection.name)
    print("[INFO] Document/chunk count:", count)

    sample = collection.peek(5)
    metadatas = sample.get("metadatas", []) or []
    documents = sample.get("documents", []) or []

    print("\n[INFO] Metadata sample:")
    print(json.dumps(metadatas, ensure_ascii=False, indent=2)[:5000])

    print("\n[INFO] Document preview sample:")
    for idx, doc in enumerate(documents, start=1):
        print(f"--- sample {idx} ---")
        print((doc or "")[:700])

    # Pull more metadata for summary. Avoid documents to keep memory reasonable.
    try:
        data = collection.get(include=["metadatas"], limit=min(count, 20000))
        all_metadatas = data.get("metadatas", []) or []
        print("\n[INFO] Metadata summary:")
        print(json.dumps(summarize_metadata(all_metadatas), ensure_ascii=False, indent=2)[:10000])
    except Exception as exc:
        print("[WARN] Could not build metadata summary:", exc)

    if args.query:
        print("\n[INFO] Retrieval smoke test:", args.query)
        docs = vectorstore.as_retriever(search_kwargs={"k": args.top_k}).invoke(args.query)
        for idx, doc in enumerate(docs, start=1):
            md = doc.metadata or {}
            print(f"\n--- result {idx} ---")
            print("title:", md.get("title"))
            print("source:", md.get("source"))
            print("vendor/product/component:", md.get("vendor"), md.get("product"), md.get("component"))
            print("page/page_label:", md.get("page"), md.get("page_label"))
            print("preview:", doc.page_content[:700])

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
