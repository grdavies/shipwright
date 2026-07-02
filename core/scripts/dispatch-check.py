#!/usr/bin/env python3
"""Fail-closed dispatch binding preflight for delegated Task spawns."""
from __future__ import annotations

import json
import sys
from pathlib import Path

from _sw.cli import run_module_main

TIER_ORDER = ["cheap", "build", "mid", "deep"]
NATIVE_PANEL_AGENTS = frozenset({
    "correctness", "security", "adversarial", "data-migration", "maintainability",
    "scope-fidelity", "testing", "performance", "api-contract", "reliability",
    "ui-ux", "type-design", "comment-accuracy", "ai-native",
})


def tier_rank(name: str | None) -> int | None:
    if not name or name not in TIER_ORDER:
        return None
    return TIER_ORDER.index(name)


def model_to_tier(concrete: str, tiers: dict) -> str | None:
    for tier_name, model in tiers.items():
        if model == concrete:
            return tier_name
    return None


def is_reviewer_bound(agent: str) -> bool:
    return agent.startswith("sw-") and agent.endswith("-reviewer")


def is_native_panel_bound(agent: str) -> bool:
    return agent in NATIVE_PANEL_AGENTS


def requires_parent_tier(agent: str) -> bool:
    return is_reviewer_bound(agent) or is_native_panel_bound(agent)


def resolve_parent_tier(
    parent_model: str,
    tiers: dict,
    *,
    fallback_tier: str | None,
) -> tuple[str | None, bool, str | None]:
    parent_tier = model_to_tier(parent_model, tiers)
    if parent_tier is not None:
        return parent_tier, False, None
    if not fallback_tier:
        return None, False, None
    if fallback_tier not in TIER_ORDER:
        return None, False, "binding:invalid-fallback-tier"
    return fallback_tier, True, None


def evaluate_dispatch(
    *,
    agent: str,
    parent_model: str,
    model_id: str,
    tier: str,
    override: bool,
    builder_tier: str,
    tiers: dict,
    fallback_tier: str | None,
    dispatch_id: str | None,
    command_name: str | None,
    skill_name: str | None,
) -> dict:
    parent_tier, used_fallback, fallback_err = resolve_parent_tier(
        parent_model, tiers, fallback_tier=fallback_tier
    )
    if fallback_err:
        return {
            "verdict": "fail",
            "cause": fallback_err,
            "agent": agent,
            "parentModel": parent_model,
            "retryable": False,
            "remediation": "set dispatch.unregisteredParentModelTier to cheap|build|mid|deep",
        }

    if requires_parent_tier(agent):
        parent_rank = tier_rank(parent_tier)
        builder_rank = tier_rank(builder_tier)
        if parent_rank is None or builder_rank is None:
            return {
                "verdict": "fail",
                "cause": "binding:no-model",
                "agent": agent,
                "parentModel": parent_model,
                "retryable": False,
                "remediation": (
                    "resolve parent session to a concrete models.tiers id or set "
                    "dispatch.unregisteredParentModelTier"
                ),
            }
        if parent_rank < builder_rank and not override:
            return {
                "verdict": "fail",
                "cause": "binding:no-model",
                "agent": agent,
                "parentModel": parent_model,
                "parentTier": parent_tier,
                "builderTier": builder_tier,
                "retryable": False,
                "remediation": (
                    "raise parent session to builder tier or use --override with a recorded durable audit entry"
                ),
            }
    elif parent_tier is None:
        print(
            json.dumps(
                {
                    "action": "dispatch-check",
                    "advisory": "binding:unregistered-parent-advisory",
                    "parentModel": parent_model,
                    "agent": agent,
                }
            ),
            file=sys.stderr,
        )

    return {
        "verdict": "pass",
        "agent": agent,
        "command": command_name or None,
        "skill": skill_name or None,
        "tier": tier,
        "modelId": model_id,
        "parentModel": parent_model,
        "parentTier": parent_tier,
        "parentTierFallbackUsed": used_fallback,
        "builderTier": builder_tier,
        "dispatchId": dispatch_id or None,
        "override": override,
    }


def main(argv: list[str] | None = None) -> int:
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
    dispatch_cfg = {}
    if config_path.is_file():
        cfg = json.loads(config_path.read_text(encoding="utf-8"))
        models = cfg.get("models", {}) if isinstance(cfg, dict) else {}
        dispatch_cfg = cfg.get("dispatch", {}) if isinstance(cfg, dict) else {}

    tiers = models.get("tiers", {}) if isinstance(models, dict) else {}
    roles = models.get("roles", {}) if isinstance(models, dict) else {}
    builder_tier = roles.get("builder", "build")
    fallback_tier = None
    if isinstance(dispatch_cfg, dict):
        raw = dispatch_cfg.get("unregisteredParentModelTier")
        if isinstance(raw, str) and raw.strip():
            fallback_tier = raw.strip()

    result = evaluate_dispatch(
        agent=agent,
        parent_model=parent_model,
        model_id=model_id,
        tier=tier,
        override=override,
        builder_tier=builder_tier,
        tiers=tiers,
        fallback_tier=fallback_tier,
        dispatch_id=dispatch_id or None,
        command_name=command_name or None,
        skill_name=skill_name or None,
    )
    print(json.dumps(result))
    if result.get("verdict") == "fail":
        return 20
    return 0


if __name__ == "__main__":
    run_module_main(main)
