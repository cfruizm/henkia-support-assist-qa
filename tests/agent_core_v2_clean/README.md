# Agent Core V2 Clean tests

This directory contains current deterministic behavioral tests.

- Tests must not call an external LLM.
- Tests must not require the production vectorstore unless explicitly classified as integration tests.
- Historical phase-specific scripts that no longer match the runtime are not retained as active tests.
- Architecture validators remain in `tools/agent_core_v2_clean/`.

Run the current unit set with:

```bash
python tests/agent_core_v2_clean/run_unit_checks.py
```
