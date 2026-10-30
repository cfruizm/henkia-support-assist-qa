from __future__ import annotations

import ast
import json
from pathlib import Path


def run() -> dict:
    root = Path(__file__).resolve().parents[2]
    app_validators = sorted(str(path.relative_to(root)) for path in (root / "app").rglob("validate*.py"))
    required = (
        "tools/run_maintenance_checks.py",
        "tools/audit_secret_keys.py",
        "tools/llm_gateway/validate_openrouter_provider.py",
        "app/secret_contract.py",
        "DEPENDENCY_AND_SECRETS.md",
    )
    missing = sorted(path for path in required if not (root / path).exists())
    syntax_errors = []
    for path in root.rglob("*.py"):
        try:
            ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        except Exception as exc:
            syntax_errors.append({"path": str(path.relative_to(root)), "error": f"{type(exc).__name__}: {exc}"})
    requirements = (root / "requirements.txt").read_text(encoding="utf-8").splitlines()
    secret_contract = (root / "app/secret_contract.py").read_text(encoding="utf-8")
    required_secret_names = {
        "DEBUG_UI",
        "AGENT_CORE_EXACT_CACHE_MAX_ENTRIES",
        "AGENT_CORE_RETRIEVAL_CACHE_MAX_ENTRIES",
        "AGENT_CORE_DOCUMENTED_CACHE_MAX_ENTRIES",
        "AGENT_CORE_PROCEDURAL_CACHE_MAX_ENTRIES",
        "AGENT_CORE_INTERNAL_CACHE_MAX_ENTRIES",
        "OPENROUTER_BASE_URL",
        "OPENROUTER_HTTP_REFERER",
        "OPENROUTER_APP_TITLE",
        "OPENROUTER_ALLOW_FORMAT_FALLBACK",
        "OPENROUTER_EXCLUDE_REASONING",
    }
    missing_secret_names = sorted(name for name in required_secret_names if f'"{name}"' not in secret_contract)
    deprecated_secret_names = sorted(name for name in (
        "OPENROUTER_SITE_URL", "OPENROUTER_APP_NAME", "OPENROUTER_REASONING_MODE", "OPENROUTER_REASONING_EXCLUDE"
    ) if f'"{name}"' in secret_contract)
    gitignore = (root / ".gitignore").read_text(encoding="utf-8") if (root / ".gitignore").exists() else ""
    duplicate_requirements = sorted({line for line in requirements if line and not line.startswith("#") and requirements.count(line) > 1})
    checks = {
        "all_validators_outside_app": not app_validators,
        "maintenance_entrypoint_present": (root / "tools/run_maintenance_checks.py").exists(),
        "secret_contract_present": (root / "app/secret_contract.py").exists(),
        "secret_auditor_present": (root / "tools/audit_secret_keys.py").exists(),
        "ownership_documentation_present": (root / "DEPENDENCY_AND_SECRETS.md").exists(),
        "required_files_present": not missing,
        "python_syntax_valid": not syntax_errors,
        "requirements_have_no_exact_duplicates": not duplicate_requirements,
        "secret_contract_matches_runtime": not missing_secret_names and not deprecated_secret_names,
        "generated_and_secret_files_ignored": all(value in gitignore for value in ("__pycache__/", "*.py[cod]", ".streamlit/secrets.toml")),
    }
    failed = [name for name, passed in checks.items() if not passed]
    return {
        "phase": "4C.3.2",
        "status": "passed" if not failed else "failed",
        "checks": checks,
        "failed_checks": failed,
        "validators_remaining_in_app": app_validators,
        "missing_required_paths": missing,
        "syntax_errors": syntax_errors,
        "duplicate_requirements": duplicate_requirements,
        "missing_secret_names": missing_secret_names,
        "deprecated_secret_names": deprecated_secret_names,
        "llm_calls": 0,
        "tokens": 0,
        "vectorstore_required": False,
        "behavior_changed": False,
    }


if __name__ == "__main__":
    result = run()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["status"] == "passed" else 1)
