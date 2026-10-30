from __future__ import annotations

import ast
import json
from pathlib import Path


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
    return found


def run() -> dict:
    root = Path(__file__).resolve().parents[2]
    py_files = [p for p in root.rglob("*.py") if "__pycache__" not in p.parts]
    import_map = {str(p.relative_to(root)): _imports(p) for p in py_files}
    backend_consumers = sorted(
        path for path, imports in import_map.items()
        if any(name == "app.backend" or name.startswith("app.backend.") for name in imports)
    )
    official = {
        "streamlit_app.py",
        "pages/Agent_Core_V2_Clean_Lab.py",
        "pages/Agent_Core_V2_Robustness_Gate.py",
    }
    runtime = (root / "app/retrieval_runtime.py").read_text(encoding="utf-8")
    adapter = (root / "app/integration/lab_retrieval_adapter.py").read_text(encoding="utf-8")
    clean_retrieval = (root / "app/agent_core_v2_clean/retrieval.py").read_text(encoding="utf-8")
    backend = (root / "app/backend.py").read_text(encoding="utf-8")
    checks = {
        "backend_retained_as_reference_only": "Legacy reference-only module retained" in backend,
        "backend_has_no_consumers": not backend_consumers,
        "official_surfaces_do_not_import_backend": all("app.backend" not in import_map.get(path, set()) for path in official),
        "productive_runtime_declares_ownership": 'RUNTIME_OWNERSHIP = "productive_retrieval_boundary"' in runtime,
        "productive_runtime_has_no_backend_dependency": "app.backend" not in runtime,
        "adapter_uses_productive_runtime": "from app.retrieval_runtime import retrieve_context" in adapter,
        "adapter_exposes_productive_name": "def retrieve_from_productive_runtime" in adapter,
        "v2_clean_uses_productive_adapter_name": "retrieve_from_productive_runtime" in clean_retrieval and "retrieve_from_existing_backend" not in clean_retrieval,
        "vectorstore_boundary_preserved": "from app.vectorstore_runtime import get_vectorstore" in runtime,
        "stale_4c1_3_validator_absent": not (root / "app/agent_core_v2_clean/validate_phase4c1_3.py").exists(),
    }
    failed = [name for name, passed in checks.items() if not passed]
    return {
        "phase": "4C.2.1",
        "status": "passed" if not failed else "failed",
        "checks": checks,
        "failed_checks": failed,
        "backend_consumers": backend_consumers,
        "llm_calls": 0,
        "tokens": 0,
        "vectorstore_required": False,
        "behavior_changed": False,
    }


if __name__ == "__main__":
    result = run()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["status"] == "passed" else 1)
