from __future__ import annotations

import ast
import importlib.util
import json
from pathlib import Path


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
    return found


def _load_manifest(path: Path):
    spec = importlib.util.spec_from_file_location("runtime_ownership", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def run() -> dict:
    root = Path(__file__).resolve().parents[2]
    ownership = _load_manifest(root / "app/runtime_ownership.py")
    productive_roots = [
        root / "streamlit_app.py",
        root / "pages/Agent_Core_V2_Clean_Lab.py",
        root / "pages/Agent_Core_V2_Robustness_Gate.py",
        root / "app/agent_core_v2_clean",
        root / "app/integration",
        root / "app/retrieval_runtime.py",
        root / "app/vectorstore_runtime.py",
        root / "app/llm_gateway",
    ]
    productive_files = []
    for item in productive_roots:
        productive_files.extend([item] if item.is_file() else item.rglob("*.py"))
    import_map = {str(p.relative_to(root)): _imports(p) for p in productive_files}
    forbidden_hits = {}
    for path, imports in import_map.items():
        hits = sorted(
            name for name in imports
            if any(name == forbidden or name.startswith(forbidden + ".") for forbidden in ownership.FORBIDDEN_PRODUCTIVE_IMPORTS)
        )
        if hits:
            forbidden_hits[path] = hits
    adapter = (root / "app/integration/lab_retrieval_adapter.py").read_text(encoding="utf-8")
    retrieval = (root / "app/retrieval_runtime.py").read_text(encoding="utf-8")
    registry = (root / "app/domain_registry.py").read_text(encoding="utf-8")
    checks = {
        "ownership_manifest_version": ownership.RUNTIME_OWNERSHIP_VERSION == "4C.2.3",
        "productive_boundaries_complete": set(ownership.PRODUCTIVE_BOUNDARIES) == {"conversation", "retrieval", "vectorstore", "domain_registry", "runtime_config", "llm_gateway"},
        "backend_is_reference_only": ownership.REFERENCE_ONLY_MODULES == ("app.backend",),
        "productive_surfaces_have_no_forbidden_imports": not forbidden_hits,
        "legacy_adapter_alias_removed": "retrieve_from_existing_backend" not in adapter,
        "productive_adapter_name_present": "def retrieve_from_productive_runtime" in adapter,
        "retrieval_ownership_preserved": 'RUNTIME_OWNERSHIP = "productive_retrieval_boundary"' in retrieval,
        "canonical_registry_preserved": "Canonical product and process registry for Henkia Support Assist" in registry,
        "legacy_registry_absent": not (root / "app/domain_registry_v1.py").exists(),
        "old_core_folders_absent": not (root / "app/agent_core").exists() and not (root / "app/agent_core_v2").exists(),
    }
    failed = [name for name, passed in checks.items() if not passed]
    return {
        "phase": "4C.2.3",
        "phase_4C2_status": "approved" if not failed else "not_approved",
        "status": "passed" if not failed else "failed",
        "checks": checks,
        "failed_checks": failed,
        "forbidden_import_hits": forbidden_hits,
        "productive_files_scanned": len(import_map),
        "llm_calls": 0,
        "tokens": 0,
        "vectorstore_required": False,
        "behavior_changed": False,
        "next_phase": "4C.3" if not failed else None,
    }


if __name__ == "__main__":
    result = run()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["status"] == "passed" else 1)
