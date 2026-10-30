from __future__ import annotations

import ast
import json
from pathlib import Path


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
    imports = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)
    return imports


def run() -> dict:
    root = Path(__file__).resolve().parents[2]
    py_files = [p for p in root.rglob("*.py") if "__pycache__" not in p.parts]
    import_map = {str(p.relative_to(root)): _imports(p) for p in py_files}
    legacy_consumers = sorted(
        path for path, imports in import_map.items()
        if any(name == "app.domain_registry_v1" or name.startswith("app.domain_registry_v1.") for name in imports)
    )
    productive_registry_consumers = sorted(
        path for path, imports in import_map.items()
        if any(name == "app.domain_registry" or name.startswith("app.domain_registry.") for name in imports)
    )
    productive_config_consumers = sorted(
        path for path, imports in import_map.items()
        if any(name == "app.config" or name.startswith("app.config.") for name in imports)
    )
    registry = (root / "app/domain_registry.py").read_text(encoding="utf-8")
    config = (root / "app/config.py").read_text(encoding="utf-8")
    retrieval = (root / "app/retrieval_runtime.py").read_text(encoding="utf-8")
    vectorstore = (root / "app/vectorstore_runtime.py").read_text(encoding="utf-8")
    checks = {
        "legacy_registry_absent": not (root / "app/domain_registry_v1.py").exists(),
        "legacy_registry_has_no_consumers": not legacy_consumers,
        "canonical_registry_declares_ownership": "Canonical product and process registry for Henkia Support Assist" in registry,
        "canonical_config_declares_ownership": "Canonical runtime configuration for productive retrieval resources" in config,
        "retrieval_uses_canonical_registry": "from app.domain_registry import" in retrieval,
        "retrieval_uses_canonical_config": "from app.config import CONFIG" in retrieval,
        "vectorstore_uses_canonical_config": "from app.config import CONFIG" in vectorstore,
        "runtime_has_no_legacy_registry_reference": "domain_registry_v1" not in retrieval and "domain_registry_v1" not in vectorstore,
    }
    failed = [name for name, passed in checks.items() if not passed]
    return {
        "phase": "4C.2.2",
        "status": "passed" if not failed else "failed",
        "checks": checks,
        "failed_checks": failed,
        "legacy_registry_consumers": legacy_consumers,
        "canonical_registry_consumers": productive_registry_consumers,
        "canonical_config_consumers": productive_config_consumers,
        "llm_calls": 0,
        "tokens": 0,
        "vectorstore_required": False,
        "behavior_changed": False,
    }


if __name__ == "__main__":
    result = run()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["status"] == "passed" else 1)
