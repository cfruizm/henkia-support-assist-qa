from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from app.secret_contract import CORE_KEYS, PROVIDER_KEYS, REQUIRED_PROVIDER_KEYS


def audit(keys: set[str], provider: str, fallback_provider: str | None = None) -> dict:
    provider = provider.strip().casefold()
    fallback = (fallback_provider or "").strip().casefold() or None
    active_providers = {provider} | ({fallback} if fallback else set())
    recognized = set(CORE_KEYS)
    for values in PROVIDER_KEYS.values():
        recognized.update(values)
    required = set()
    for name in active_providers:
        required.update(REQUIRED_PROVIDER_KEYS.get(name, ()))
    inactive_provider_keys = sorted(
        key for name, values in PROVIDER_KEYS.items() if name not in active_providers for key in values if key in keys
    )
    return {
        "provider": provider,
        "fallback_provider": fallback,
        "keys_examined": len(keys),
        "missing_required_keys": sorted(required - keys),
        "unknown_keys": sorted(keys - recognized),
        "inactive_provider_keys_present": inactive_provider_keys,
        "removal_is_advisory": True,
        "secret_values_read": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--keys-json", help="JSON file containing an object whose property names are secret names")
    parser.add_argument("--provider", default=os.getenv("LLM_PROVIDER", "groq"))
    parser.add_argument("--fallback-provider", default=os.getenv("LLM_FALLBACK_PROVIDER"))
    args = parser.parse_args()
    if args.keys_json:
        payload = json.loads(Path(args.keys_json).read_text(encoding="utf-8"))
        keys = set(payload)
    else:
        keys = {key for key in os.environ if key in set(CORE_KEYS).union(*map(set, PROVIDER_KEYS.values()))}
    result = audit(keys, args.provider, args.fallback_provider)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if result["missing_required_keys"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
