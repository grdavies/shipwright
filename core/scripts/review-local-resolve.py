#!/usr/bin/env python3
"""Resolve review.local config with schema defaults (R14–R16, R61). """
from __future__ import annotations
import sys
from pathlib import Path
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
from _sw.cli import run_module_main

def main(argv: list[str] | None = None) -> int:
    import json, sys

    config_path = sys.argv[1]
    try:
        with open(config_path, encoding="utf-8") as f:
            cfg = json.load(f)
    except (OSError, json.JSONDecodeError):
        cfg = {}

    review = cfg.get("review") or {}
    local = review.get("local") or {}

    enabled = local.get("enabled", True)
    provider = local.get("provider", "native")
    apply = local.get("apply", "auto")
    ui_enrich = (local.get("ui") or {}).get("enrich", "off")

    fire = bool(enabled) and provider != "none"
    skip_reason = None
    if not enabled:
        skip_reason = "review.local.enabled is false"
    elif provider == "none":
        skip_reason = 'review.local.provider is "none"'

    out = {
        "fire": fire,
        "skip": not fire,
        "skip_reason": skip_reason,
        "resolved": {
            "enabled": enabled,
            "provider": provider,
            "apply": apply,
            "ui": {"enrich": ui_enrich},
        },
        "review_provider": review.get("provider", "none"),
        "independent_of_review_provider": True,
    }
    print(json.dumps(out, separators=(",", ":")))
    return 0

if __name__ == "__main__":
    run_module_main(main)
