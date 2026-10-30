from __future__ import annotations

import importlib.util
import json
import shutil
import sys
from pathlib import Path

CHECKS = (
    "tests/agent_core_v2_clean/run_unit_checks.py",
    "tools/agent_core_v2_clean/validate_phase4c2_1.py",
    "tools/agent_core_v2_clean/validate_phase4c2_2.py",
    "tools/agent_core_v2_clean/validate_phase4c2_3.py",
    "tools/agent_core_v2_clean/validate_phase4c3_1.py",
    "tools/agent_core_v2_clean/validate_phase4c3_2.py",
    "tools/agent_core_v2_clean/validate_phase4c3_3.py",
)


def _load(path: Path):
    name = "check_" + path.stem
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def _remove_compiled_artifacts(root: Path) -> None:
    for directory in list(root.rglob("__pycache__")):
        if directory.is_dir():
            shutil.rmtree(directory)
    for compiled in list(root.rglob("*.pyc")):
        if compiled.exists():
            compiled.unlink()


def run() -> dict:
    root = Path(__file__).resolve().parents[1]
    sys.dont_write_bytecode = True
    _remove_compiled_artifacts(root)
    results = []
    for relative in CHECKS:
        path = root / relative
        module = _load(path)
        result = module.run()
        status = result.get("status")
        passed = status == "passed"
        results.append({"check": relative, "passed": passed, "result": result})
    failed = [item for item in results if not item["passed"]]
    _remove_compiled_artifacts(root)
    return {
        "suite": "henkia_maintenance",
        "status": "passed" if not failed else "failed",
        "passed": len(results) - len(failed),
        "failed": len(failed),
        "results": results,
        "llm_calls": 0,
        "tokens": 0,
        "vectorstore_required": False,
    }


if __name__ == "__main__":
    result = run()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["status"] == "passed" else 1)
