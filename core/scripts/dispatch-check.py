#!/usr/bin/env python3
"""Fail-closed dispatch binding preflight for delegated Task spawns."""
from __future__ import annotations

import json
import subprocess
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


def _run_json_cmd(cmd: list[str]) -> dict:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0 or not proc.stdout.strip():
        return {}
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _has_override_audit(start: Path, dispatch_id: str) -> bool:
    import shipwright_state_lib as ssl

    state_path = ssl.resolve_state_path(start)
    if not state_path.is_file():
        return False
    state = json.loads(state_path.read_text(encoding="utf-8"))
    records = state.get("dispatchOverrides")
    if not isinstance(records, list):
        return False
    for rec in records:
        if not isinstance(rec, dict):
            continue
        if rec.get("dispatchId") != dispatch_id:
            continue
        skipped = rec.get("skippedFields")
        if rec.get("actor") and rec.get("timestamp") and isinstance(skipped, list) and skipped:
            return True
    return False


def _main_legacy_positional(argv: list[str]) -> int:
    root, agent, parent_model, model_id, tier, override_s, dispatch_id, command_name, skill_name, *tail = argv
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


def main(argv: list[str] | None = None) -> int:
    raw = list(argv if argv is not None else sys.argv[1:])
    if raw and not raw[0].startswith("-"):
        return _main_legacy_positional(raw)

    import argparse

    parser = argparse.ArgumentParser(description="Fail-closed dispatch binding preflight for delegated Task spawns")
    parser.add_argument("--agent", required=True)
    parser.add_argument("--command", default="")
    parser.add_argument("--skill", default="")
    parser.add_argument("--parent-model", required=True)
    parser.add_argument("--dispatch-id", default="")
    parser.add_argument("--override", action="store_true")
    parser.add_argument("--config", default="")
    parser.add_argument("--simulate-capacity", action="store_true")
    args = parser.parse_args(argv)

    script_dir = Path(__file__).resolve().parent
    root = script_dir.parent
    agent = args.agent
    command_name = args.command or None
    skill_name = args.skill or None
    parent_model = args.parent_model
    dispatch_id = args.dispatch_id or None
    override = args.override

    if args.simulate_capacity:
        print(json.dumps({
            "verdict": "fail",
            "cause": "harness:capacity",
            "agent": agent,
            "retryable": True,
            "remediation": "retry with bounded parallelism respecting worktree.parallelCeiling and harness limits",
        }))
        return 20

    model_cmd = [sys.executable, str(script_dir / "resolve-model-tier.py"), "--agent", agent]
    intensity_cmd = [sys.executable, str(script_dir / "resolve-intensity.py"), "--agent", agent]
    if command_name:
        model_cmd.extend(["--command", command_name])
        intensity_cmd.extend(["--command", command_name])
    if skill_name:
        model_cmd.extend(["--skill", skill_name])
        intensity_cmd.extend(["--skill", skill_name])
    if args.config:
        model_cmd.extend(["--config", args.config])
        intensity_cmd.extend(["--config", args.config])

    model_payload = _run_json_cmd(model_cmd)
    intensity_payload = _run_json_cmd(intensity_cmd)
    model_id = str(model_payload.get("modelId") or "")
    model_tier = str(model_payload.get("tier") or "")
    intensity = str(intensity_payload.get("intensity") or "")

    if not model_id or model_tier == "inherit":
        print(json.dumps({
            "verdict": "fail",
            "cause": "binding:no-model",
            "agent": agent,
            "command": command_name,
            "skill": skill_name,
            "retryable": False,
            "remediation": f"resolve and stamp a concrete model before Task dispatch: python3 scripts/resolve-model-tier.py --agent {agent}",
        }))
        return 20

    if intensity not in {"normal", "lite", "full", "ultra"}:
        print(json.dumps({
            "verdict": "fail",
            "cause": "binding:no-intensity",
            "agent": agent,
            "command": command_name,
            "skill": skill_name,
            "retryable": False,
            "remediation": "set communication.routing (command/skill/agent) or communication.defaultIntensity to normal|lite|full|ultra",
        }))
        return 20

    if override:
        if not dispatch_id:
            print(json.dumps({
                "verdict": "fail",
                "cause": "binding:no-override-audit",
                "retryable": False,
                "remediation": "--override requires --dispatch-id and a prior shipwright-state dispatch-override-add record",
            }))
            return 20
        if not _has_override_audit(Path.cwd(), dispatch_id):
            print(json.dumps({
                "verdict": "fail",
                "cause": "binding:no-override-audit",
                "retryable": False,
                "remediation": "record durable override first: python3 scripts/shipwright-state.py dispatch-override-add ...",
            }))
            return 20

    config_path = Path(args.config) if args.config else root / ".cursor" / "workflow.config.json"
    if not config_path.is_file():
        config_path = root / "workflow.config.json"
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
        tier=model_tier,
        override=override,
        builder_tier=builder_tier,
        tiers=tiers,
        fallback_tier=fallback_tier,
        dispatch_id=dispatch_id,
        command_name=command_name,
        skill_name=skill_name,
    )
    print(json.dumps(result))
    if result.get("verdict") == "fail":
        return 20
    return 0



if __name__ == "__main__":
    run_module_main(main)
