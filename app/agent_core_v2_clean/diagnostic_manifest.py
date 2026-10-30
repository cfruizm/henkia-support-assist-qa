from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path


def _sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _source_fingerprint():
    root = Path(__file__).resolve().parents[2]
    rows = []
    for path in sorted(root.rglob("*.py")):
        if any(part in {".git", "__pycache__", ".venv", "venv"} for part in path.parts):
            continue
        try:
            rows.append({"path": str(path.relative_to(root)), "sha256": _sha256(path)})
        except OSError:
            continue
    encoded = json.dumps(rows, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest(), len(rows)


def build_diagnostic_manifest(store, payload=None):
    fingerprint, file_count = _source_fingerprint()
    budget = dict((store or {}).get("budget") or {})
    configuration = dict((store or {}).get("budget_configuration") or {})
    return {
        "schema_version": 1,
        "baseline_id": os.getenv("HENKIA_BASELINE_ID", "unlabeled-baseline"),
        "release_id": os.getenv("HENKIA_RELEASE_ID"),
        "git_commit": os.getenv("GIT_COMMIT") or os.getenv("COMMIT_SHA") or os.getenv("SOURCE_VERSION"),
        "source_fingerprint_sha256": fingerprint,
        "python_source_file_count": file_count,
        "decision_trace_schema_version": 2,
        "publication_ledger_schema_version": 1,
        "session_format": (payload or {}).get("format"),
        "budget_effective": budget,
        "budget_configuration_sources": configuration.get("sources"),
        "environment_labels": {
            "deployment": os.getenv("HENKIA_DEPLOYMENT_ENV"),
            "provider": os.getenv("HF_PROVIDER") or os.getenv("LLM_PROVIDER"),
            "model": os.getenv("HF_MODEL") or os.getenv("LLM_MODEL"),
        },
        "secrets_included": False,
    }
