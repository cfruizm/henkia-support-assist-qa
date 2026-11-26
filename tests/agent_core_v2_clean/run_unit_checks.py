from __future__ import annotations

import importlib
import inspect
import json

MODULES = (
    "tests.agent_core_v2_clean.test_canonical_frame_continuity",
    "tests.agent_core_v2_clean.test_runtime_memory_audit",
    "tests.agent_core_v2_clean.test_ke_shadow_isolation",
    "tests.agent_core_v2_clean.test_turn_recovery",
    "tests.agent_core_v2_clean.test_understanding_contract",
    "tests.agent_core_v2_clean.test_cross_language_authority",
    "tests.agent_core_v2_clean.test_strict_schema",
    "tests.agent_core_v2_clean.test_partial_publication",
    "tests.agent_core_v2_clean.test_ke_multi_base",
    "tests.agent_core_v2_clean.test_text_stems",
    "tests.agent_core_v2_clean.test_output_caps",
    "tests.agent_core_v2_clean.test_ke_publication",
)


def run() -> dict:
    results = []
    for module_name in MODULES:
        module = importlib.import_module(module_name)
        for name, function in inspect.getmembers(module, inspect.isfunction):
            if not name.startswith("test_"):
                continue
            try:
                function()
                results.append({"module": module_name, "test": name, "passed": True})
            except Exception as exc:
                results.append({"module": module_name, "test": name, "passed": False, "error": f"{type(exc).__name__}: {exc}"})
    failed = [item for item in results if not item["passed"]]
    return {
        "suite": "agent_core_v2_clean_unit",
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
