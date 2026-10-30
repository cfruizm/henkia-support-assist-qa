from __future__ import annotations

import ast
import json
from pathlib import Path

STALE_PATHS = (
    "tools/agent_core_v2_clean/behavior_check.py",
    "tools/agent_core_v2_clean/test_canonical_frame.py",
    "tools/agent_core_v2_clean/test_core.py",
    "tools/agent_core_v2_clean/test_phase3c11.py",
    "app/agent_core_v2_clean/validate_phase3d3.py",
    "tools/agent_core_lab",
    "tools/benchmark_cases.json",
    "tools/benchmark_states.json",
)


def run() -> dict:
    root = Path(__file__).resolve().parents[2]
    syntax_errors = []
    for path in root.rglob("*.py"):
        try:
            ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        except Exception as exc:
            syntax_errors.append({"path": str(path.relative_to(root)), "error": f"{type(exc).__name__}: {exc}"})
    pycache = sorted(str(path.relative_to(root)) for path in root.rglob("__pycache__"))
    gitignore = (root / ".gitignore").read_text(encoding="utf-8") if (root / ".gitignore").exists() else ""
    compiled_artifacts_ignored = "__pycache__/" in gitignore and "*.py[cod]" in gitignore
    stale_present = sorted(path for path in STALE_PATHS if (root / path).exists())
    required = (
        "tests/agent_core_v2_clean/test_canonical_frame_continuity.py",
        "tests/agent_core_v2_clean/run_unit_checks.py",
        "tests/agent_core_v2_clean/README.md",
        "tools/agent_core_v2_clean/validate_phase4c2_1.py",
        "tools/agent_core_v2_clean/validate_phase4c2_2.py",
        "tools/agent_core_v2_clean/validate_phase4c2_3.py",
    )
    missing_required = sorted(path for path in required if not (root / path).exists())
    checks = {
        "python_syntax_valid": not syntax_errors,
        "stale_checks_absent": not stale_present,
        "compiled_artifacts_absent": not pycache,
        "compiled_artifacts_ignored": compiled_artifacts_ignored,
        "canonical_test_structure_present": not missing_required,
    }
    failed = [name for name, passed in checks.items() if not passed]
    return {
        "phase": "4C.3.1",
        "status": "passed" if not failed else "failed",
        "checks": checks,
        "failed_checks": failed,
        "syntax_errors": syntax_errors,
        "stale_paths_present": stale_present,
        "pycache_directories": pycache,
        "missing_required_paths": missing_required,
        "llm_calls": 0,
        "tokens": 0,
        "vectorstore_required": False,
        "behavior_changed": False,
    }


if __name__ == "__main__":
    result = run()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["status"] == "passed" else 1)
