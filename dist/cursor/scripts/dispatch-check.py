#!/usr/bin/env python3
"""Fail-closed dispatch binding preflight for delegated Task spawns."""
from __future__ import annotations

import sys

from _sw.cli import run_module_main


def main(argv: list[str] | None = None) -> int:
    import json
    import sys
    from pathlib import Path

    root, agent, parent_model, model_id, tier, override_s, dispatch_id, command_name, skill_name, *tail = sys.argv[1:]
    override = override_s == "1"
    config = ""
    for i, arg in enumerate(tail):
        if arg == "--config" and i + 1 < len(tail):
            config = tail[i + 1]
            break

    config_path = Path(config) if config else Path(root) / ".cursor" / "workflow.config.json"
    if not config_path.is_file():
        config_path = Path(root) / "workflow.config.json"
    models = {}
    if config_path.is_file():
        models = json.loads(config_path.read_text(encoding="utf-8")).get("models", {})

    tiers = models.get("tiers", {}) if isinstance(models, dict) else {}
    roles = models.get("roles", {}) if isinstance(models, dict) else {}
    builder_tier = roles.get("builder", "build")
    order = ["cheap", "build", "mid", "deep"]

    def tier_rank(name: str):
        if name not in order:
            return None
        return order.index(name)

    def model_to_tier(concrete: str):
        for tier_name, model in tiers.items():
            if model == concrete:
                return tier_name
        return None

    parent_tier = model_to_tier(parent_model)
    builder_rank = tier_rank(builder_tier)
    parent_rank = tier_rank(parent_tier) if parent_tier else None

    if parent_rank is None or builder_rank is None:
        print(json.dumps({
            "verdict": "fail",
            "cause": "binding:no-model",
            "agent": agent,
            "parentModel": parent_model,
            "retryable": False,
            "remediation": "resolve parent session to a concrete models.tiers id before dispatch",
        }))
        sys.exit(20)

    reviewer_bound = agent.startswith("sw-") and agent.endswith("-reviewer")
    native_panel_bound = agent in {
        "correctness", "security", "adversarial", "data-migration", "maintainability",
        "scope-fidelity", "testing", "performance", "api-contract", "reliability",
        "ui-ux", "type-design", "comment-accuracy", "ai-native",
    }

    if (reviewer_bound or native_panel_bound) and parent_rank < builder_rank and not override:
        print(json.dumps({
            "verdict": "fail",
            "cause": "binding:no-model",
            "agent": agent,
            "parentModel": parent_model,
            "parentTier": parent_tier,
            "builderTier": builder_tier,
            "retryable": False,
            "remediation": "raise parent session to builder tier or use --override with a recorded durable audit entry",
        }))
        sys.exit(20)

    print(json.dumps({
        "verdict": "pass",
        "agent": agent,
        "command": command_name or None,
        "skill": skill_name or None,
        "tier": tier,
        "modelId": model_id,
        "parentModel": parent_model,
        "parentTier": parent_tier,
        "builderTier": builder_tier,
        "dispatchId": dispatch_id or None,
        "override": override,
    }))
    return 0


if __name__ == "__main__":
    run_module_main(main)
