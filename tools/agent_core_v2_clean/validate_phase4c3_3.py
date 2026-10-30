from __future__ import annotations

import ast
import json
from pathlib import Path


def _requirement_names(path: Path) -> list[str]:
    names = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        for marker in ("==", ">=", "<=", "~=", "!=", ">", "<"):
            line = line.split(marker, 1)[0]
        names.append(line.strip().casefold().replace("_", "-"))
    return names


def _absolute_imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found.add(node.module)
    return found


def run() -> dict:
    root = Path(__file__).resolve().parents[2]
    requirements = _requirement_names(root / "requirements.txt")
    all_imports = {}
    for path in root.rglob("*.py"):
        all_imports[str(path.relative_to(root))] = sorted(_absolute_imports(path))
    legacy_groq_consumers = sorted(
        path for path, imports in all_imports.items()
        if "app.llm_gateway.groq_provider" in imports
    )
    productive_groq_consumers = sorted(
        path for path, imports in all_imports.items()
        if "app.llm_gateway.providers.groq_provider" in imports
    )
    crawler = (root / "scripts/build_vectorstore.py").read_text(encoding="utf-8")
    ownership = json.loads((root / "DEPENDENCY_OWNERSHIP.json").read_text(encoding="utf-8"))
    checks = {
        "dependency_manifest_present": ownership.get("version") == "4C.3.3",
        "starlette_removed": "starlette" not in requirements,
        "trafilatura_declared": "trafilatura" in requirements,
        "crawler_directly_uses_trafilatura": "import requests, trafilatura" in crawler,
        "legacy_groq_provider_absent": not (root / "app/llm_gateway/groq_provider.py").exists(),
        "legacy_groq_provider_has_no_consumers": not legacy_groq_consumers,
        "productive_groq_provider_present": (root / "app/llm_gateway/providers/groq_provider.py").exists(),
        "gateway_uses_productive_groq_provider": productive_groq_consumers == ["app/llm_gateway/gateway.py"],
        "requirements_have_no_duplicates": len(requirements) == len(set(requirements)),
        "deferred_dependencies_not_removed_blindly": all(name in requirements for name in ("pandas", "torchvision")),
    }
    failed = [name for name, passed in checks.items() if not passed]
    return {
        "phase": "4C.3.3",
        "status": "passed" if not failed else "failed",
        "checks": checks,
        "failed_checks": failed,
        "legacy_groq_consumers": legacy_groq_consumers,
        "productive_groq_consumers": productive_groq_consumers,
        "requirements": requirements,
        "llm_calls": 0,
        "tokens": 0,
        "vectorstore_required": False,
        "behavior_changed": False,
    }


if __name__ == "__main__":
    result = run()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["status"] == "passed" else 1)
