#!/usr/bin/env python3
"""Fail-closed dispatch binding preflight for delegated Task spawns.

Advisory graduation / autoApply operator guidance: see
``docs/guides/configuration.md`` (PRD 351 phase 3 expands graduation criteria).
"""
from __future__ import annotations

import concurrent.futures
import json
import logging
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from _sw.cli import run_module_main
from dispatch_intensity_check import validate_directive_anchor
from dispatch_reader_lib import evaluate_reader_role, validate_reader_tool_log_file
from dispatch_complexity_lib import probe_complexity
from dispatch_budget_lib import resolve_token_budget
from graph.cost_telemetry import aggregate
from graph.reviewer_metrics.selection import load_harvest_record
from graph.learning_consumers import (
    get_current_advisory,
    hydrate_advisory_snapshot_from_store,
)
from model_policy_lib import ModelPolicy, ensure_mid_tier, preflight_missing_mid, tier_rank
from task_model_allowlist_lib import enforce_task_model_allowlist
from workflow_intelligence import AdvisoryRecommendation, InsufficientSampleError

SCRIPT_DIR = Path(__file__).resolve().parent
NATIVE_PANEL_AGENTS = frozenset({
    "correctness", "security", "adversarial", "data-migration", "maintainability",
    "scope-fidelity", "testing", "performance", "api-contract", "reliability",
    "ui-ux", "type-design", "comment-accuracy", "ai-native",
})

_LOG = logging.getLogger("dispatch-check")

DEFAULT_ADVISORY_LOOKUP_TIMEOUT_MS = 200
DEFAULT_MIN_SAMPLE_COUNT = 10
DEFAULT_MAX_FRESHNESS_AGE_DAYS = 30


def _advisory_routing_config(config: Mapping[str, Any] | None) -> dict[str, Any]:
    models = (config or {}).get("models") if isinstance(config, Mapping) else None
    routing = models.get("routing") if isinstance(models, Mapping) else None
    advisory = routing.get("advisoryRouting") if isinstance(routing, Mapping) else None
    if not isinstance(advisory, dict):
        return {
            "enabled": True,
            "autoApply": False,
            "minSampleCount": DEFAULT_MIN_SAMPLE_COUNT,
            "maxFreshnessAgeDays": DEFAULT_MAX_FRESHNESS_AGE_DAYS,
            "lookupTimeoutMs": DEFAULT_ADVISORY_LOOKUP_TIMEOUT_MS,
        }
    return {
        "enabled": bool(advisory.get("enabled", True)),
        "autoApply": bool(advisory.get("autoApply", False)),
        "minSampleCount": int(advisory.get("minSampleCount", DEFAULT_MIN_SAMPLE_COUNT)),
        "maxFreshnessAgeDays": int(
            advisory.get("maxFreshnessAgeDays", DEFAULT_MAX_FRESHNESS_AGE_DAYS)
        ),
        "lookupTimeoutMs": int(
            advisory.get("lookupTimeoutMs", DEFAULT_ADVISORY_LOOKUP_TIMEOUT_MS)
        ),
    }


def _model_allow_deny(config: Mapping[str, Any] | None) -> tuple[set[str] | None, set[str]]:
    models = (config or {}).get("models") if isinstance(config, Mapping) else None
    if not isinstance(models, Mapping):
        return None, set()
    allowed_raw = models.get("allowedModels")
    excluded_raw = models.get("excludedModels")
    allowed: set[str] | None
    if isinstance(allowed_raw, list) and allowed_raw:
        allowed = {str(item) for item in allowed_raw}
    else:
        allowed = None
    excluded = {str(item) for item in excluded_raw} if isinstance(excluded_raw, list) else set()
    return allowed, excluded


def _advisory_allowed(
    model: str,
    *,
    allowed: set[str] | None,
    excluded: set[str],
) -> tuple[bool, str]:
    if model in excluded:
        return False, "excludedModels"
    if allowed is not None and model not in allowed:
        return False, "not-in-allowedModels"
    return True, ""


def format_advisory_line(
    recommendation: AdvisoryRecommendation,
    *,
    status: str,
) -> str:
    """Format the preflight ``[advisory]`` line (R16)."""
    confidence_pct = int(round(float(recommendation["confidence_score"]) * 100))
    return (
        f"[advisory] Recommended: {recommendation['recommended_model']} | "
        f"Confidence: {confidence_pct}% | "
        f"Basis: {recommendation['sample_count']} tasks "
        f"({recommendation['data_freshness_ts']}) | "
        f"Status: {status}"
    )


def run_preflight(
    *,
    task_type: str,
    dimension_record: dict[str, Any] | None = None,
    config: Mapping[str, Any] | None = None,
    selected_model: str | None = None,
    now_ts: str | None = None,
) -> dict[str, Any]:
    """Run advisory-aware dispatch preflight and return a report dict (R16–R19).

    Advisory lookup is bounded by ``advisoryRouting.lookupTimeoutMs`` (default 200ms).
    """
    dimension_record = dict(dimension_record or {})
    # PRD 352 R22/TR6 — hydrate durable advisory observations on startup.
    hydrate_advisory_snapshot_from_store(task_type)
    routing = _advisory_routing_config(config)
    allowed, excluded = _model_allow_deny(config)
    policy = ModelPolicy.from_config(config if isinstance(config, Mapping) else {})

    lines: list[str] = []
    advisory: AdvisoryRecommendation | None = None
    applied = False
    effective_model = selected_model

    if not routing["enabled"]:
        return {
            "advisory_lines": lines,
            "advisory": None,
            "selected_model": effective_model,
            "advisory_applied": False,
            "autoApply": False,
        }

    timeout_s = max(routing["lookupTimeoutMs"], 1) / 1000.0

    def _lookup() -> AdvisoryRecommendation | None:
        return get_current_advisory(task_type, dimension_record)

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(_lookup)
            try:
                advisory = future.result(timeout=timeout_s)
            except concurrent.futures.TimeoutError:
                _LOG.warning("[advisory-timeout] lookup exceeded %sms", routing["lookupTimeoutMs"])
                lines.append("[advisory-timeout]")
                advisory = None
    except InsufficientSampleError:
        lines.append("[advisory] Insufficient data — no recommendation")
        advisory = None

    if advisory is None and not any(line.startswith("[advisory-timeout]") for line in lines):
        lines.append("[advisory] Insufficient data — no recommendation")
    elif advisory is not None:
        model = str(advisory["recommended_model"])
        ok, reason = _advisory_allowed(model, allowed=allowed, excluded=excluded)
        if not ok:
            lines.append(
                f"[advisory] Insufficient data — no recommendation"
            )
            _LOG.info("advisory suppressed: model %s (%s)", model, reason)
            advisory = None
        elif not policy.evaluate_advisory(
            advisory,
            min_sample_count=routing["minSampleCount"],
            max_freshness_age_days=routing["maxFreshnessAgeDays"],
            now_ts=now_ts,
        ):
            lines.append("[advisory] Insufficient data — no recommendation")
            advisory = None
        else:
            auto_apply = bool(routing["autoApply"])
            status = "will-apply" if auto_apply else "read-only"
            # SC3: never apply without autoApply:true
            lines.append(format_advisory_line(advisory, status=status))
            if auto_apply:
                # Availability: model must not be excluded / must be allowed.
                available, why = _advisory_allowed(model, allowed=allowed, excluded=excluded)
                if not available:
                    _LOG.warning(
                        "[advisory-fallback] Recommended %s unavailable: %s",
                        model,
                        why,
                    )
                    lines.append(
                        f"[advisory-fallback] Recommended {model} unavailable: {why}"
                    )
                else:
                    effective_model = model
                    applied = True

    harvest_bounded = False
    try:
        # PRD 352 R23 — selection reads persist_harvest output when available.
        harvest = load_harvest_record(Path.cwd())
        harvest_bounded = bool(harvest and harvest.reviewers)
    except Exception:
        harvest_bounded = False

    return {
        "advisory_lines": lines,
        "advisory": advisory,
        "selected_model": effective_model,
        "advisory_applied": applied,
        "harvest_bounded": harvest_bounded,
        "autoApply": bool(routing["autoApply"]),
        "generated_at": now_ts or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


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


def _apply_spawn_model_allowlist(
    model_id: str,
    *,
    root: Path,
    agent: str,
    command_name: str | None,
    skill_name: str | None,
) -> tuple[str | None, dict | None]:
    allow = enforce_task_model_allowlist(model_id, root=root)
    if allow.get("verdict") == "fail":
        return None, {
            "verdict": "fail",
            "cause": allow.get("cause"),
            "agent": agent,
            "command": command_name,
            "skill": skill_name,
            "modelId": model_id,
            "retryable": False,
            "remediation": allow.get("remediation"),
        }
    return str(allow["modelId"]), None


def evaluate_dispatch_posture(
    *,
    dispatch_action: str | None,
    run_in_background: bool,
    override: bool,
) -> dict | None:
    if dispatch_action == "dispatch-ship" and run_in_background and not override:
        return {
            "verdict": "fail",
            "cause": "dispatch:inline-forbids-background",
            "dispatchAction": dispatch_action,
            "runInBackground": True,
            "retryable": False,
            "remediation": (
                "dispatch-ship must run inline (run_in_background: false); "
                "only dispatch-batch may use background Task spawns"
            ),
        }
    return None


def resolve_parent_tier(
    parent_model: str,
    tiers: dict,
    *,
    fallback_tier: str | None,
    policy: ModelPolicy,
) -> tuple[str | None, bool, str | None]:
    parent_tier = model_to_tier(parent_model, tiers)
    if parent_tier is not None:
        return parent_tier, False, None
    if not fallback_tier:
        return None, False, None
    if policy.tier_rank(fallback_tier) is None:
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
    policy: ModelPolicy | None = None,
) -> dict:
    tier_policy = policy or ModelPolicy.from_tiers(tiers)
    parent_tier, used_fallback, fallback_err = resolve_parent_tier(
        parent_model, tiers, fallback_tier=fallback_tier, policy=tier_policy
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
        parent_rank = tier_rank(parent_tier, tier_policy)
        builder_rank = tier_rank(builder_tier, tier_policy)
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


def _normalize_tiers(raw_tiers: dict) -> tuple[dict, ModelPolicy, dict[str, Any] | None]:
    tiers = {str(k): str(v) for k, v in raw_tiers.items()} if isinstance(raw_tiers, dict) else {}
    mid_advisory = preflight_missing_mid(tiers)
    tiers, _ = ensure_mid_tier(tiers)
    return tiers, ModelPolicy.from_tiers(tiers), mid_advisory


def _emit_mid_advisory(advisory: dict[str, Any] | None) -> None:
    if advisory:
        print(json.dumps({"action": "dispatch-check", **advisory}), file=sys.stderr)


def _run_json_cmd(cmd: list[str]) -> dict:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if not proc.stdout.strip():
        return {}
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}



def _validate_prompt_surface(
    prompt_path: Path,
    *,
    intensity: str,
    intensity_source: str,
    agent: str,
    command_name: str | None,
    skill_name: str | None,
) -> dict | None:
    """Validate a constructed prompt via the shared intensity-directive helper (R15)."""
    if not prompt_path.is_file():
        return {
            "verdict": "fail",
            "cause": "binding:prompt-missing",
            "agent": agent,
            "command": command_name,
            "skill": skill_name,
            "promptPath": str(prompt_path),
            "retryable": False,
            "remediation": f"write the constructed Task prompt to {prompt_path} before dispatch-check",
        }
    try:
        prompt_text = prompt_path.read_text(encoding="utf-8")
        anchor = validate_directive_anchor(
            prompt_text,
            expected_intensity=intensity,
            expected_source=intensity_source,
        )
    except Exception:
        return {
            "verdict": "fail",
            "cause": "binding:prompt-validation-error",
            "agent": agent,
            "command": command_name,
            "skill": skill_name,
            "promptPath": str(prompt_path),
            "retryable": False,
            "remediation": "fix prompt construction and re-run dispatch-check with --prompt",
        }
    if anchor.verdict != "pass":
        return {
            "verdict": "fail",
            "cause": anchor.cause,
            "agent": agent,
            "command": command_name,
            "skill": skill_name,
            "intensity": intensity,
            "intensitySource": intensity_source,
            "promptPath": str(prompt_path),
            "retryable": False,
            "remediation": anchor.remediation,
        }
    return None


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

    config_path = Path(config) if config else Path(root) / ("." + "cursor") / "workflow.config.json"
    if not config_path.is_file():
        config_path = Path(root) / "workflow.config.json"
    models = {}
    dispatch_cfg = {}
    if config_path.is_file():
        cfg = json.loads(config_path.read_text(encoding="utf-8"))
        models = cfg.get("models", {}) if isinstance(cfg, dict) else {}
        dispatch_cfg = cfg.get("dispatch", {}) if isinstance(cfg, dict) else {}

    tiers = models.get("tiers", {}) if isinstance(models, dict) else {}
    tiers, policy, mid_advisory = _normalize_tiers(tiers)
    _emit_mid_advisory(mid_advisory)
    roles = models.get("roles", {}) if isinstance(models, dict) else {}
    builder_tier = roles.get("builder", "build")
    fallback_tier = None
    if isinstance(dispatch_cfg, dict):
        raw = dispatch_cfg.get("unregisteredParentModelTier")
        if isinstance(raw, str) and raw.strip():
            fallback_tier = raw.strip()

    model_id, allow_fail = _apply_spawn_model_allowlist(
        model_id,
        root=SCRIPT_DIR.parent,
        agent=agent,
        command_name=command_name or None,
        skill_name=skill_name or None,
    )
    if allow_fail:
        print(json.dumps(allow_fail))
        return 20

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
        policy=policy,
    )
    print(json.dumps(result))
    if result.get("verdict") == "fail":
        return 20
    return 0


def main(argv: list[str] | None = None) -> int:
    # PRD 352 R22/TR6 — hydrate advisory snapshot before preflight work.
    hydrate_advisory_snapshot_from_store()
    raw = list(argv if argv is not None else sys.argv[1:])
    # PRD 351 R23 — named consumer for cost_telemetry aggregate --split-verified.
    if "--split-verified" in raw and "--agent" not in raw:
        print(json.dumps(aggregate(split_verified=True), indent=2, ensure_ascii=False))
        return 0
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
    parser.add_argument(
        "--split-verified",
        action="store_true",
        help="emit cost_telemetry aggregate --split-verified JSON (PRD 351 R23)",
    )
    parser.add_argument(
        "--prompt",
        default="",
        metavar="PATH",
        help="validate a constructed Task prompt via the shared intensity-directive helper (R15)",
    )
    parser.add_argument(
        "--dispatch-action",
        default="",
        help="conductor dispatch action (dispatch-ship|dispatch-batch)",
    )
    parser.add_argument(
        "--run-in-background",
        action="store_true",
        help="Task spawn requested run_in_background=true",
    )
    parser.add_argument(
        "--role",
        default="",
        help="declared Task role (reader for untrusted-signal intake)",
    )
    parser.add_argument(
        "--boundary",
        default="",
        help="dispatch boundary (feedback-intake|debug-sentry-expansion)",
    )
    parser.add_argument(
        "--tool-log",
        default="",
        metavar="PATH",
        help="reader Task tool-call log for post-spawn mutating-call validation",
    )
    parser.add_argument(
        "--signal-context",
        default="",
        help="JSON signal_context for complexity probe inputs",
    )
    args = parser.parse_args(argv)

    script_dir = SCRIPT_DIR
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
    intensity_source = str(intensity_payload.get("source") or "")

    if not model_id or model_tier == "inherit":
        if model_payload.get("cause") == "binding:model-not-allowlisted":
            print(json.dumps({
                "verdict": "fail",
                "cause": model_payload.get("cause"),
                "agent": agent,
                "command": command_name,
                "skill": skill_name,
                "modelId": model_payload.get("modelId"),
                "retryable": False,
                "remediation": model_payload.get("error") or model_payload.get("remediation"),
            }))
            return 20
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

    posture_fail = evaluate_dispatch_posture(
        dispatch_action=(args.dispatch_action or None),
        run_in_background=bool(args.run_in_background),
        override=override,
    )
    if posture_fail:
        print(json.dumps(posture_fail))
        return 20

    if args.prompt:
        prompt_fail = _validate_prompt_surface(
            Path(args.prompt),
            intensity=intensity,
            intensity_source=intensity_source,
            agent=agent,
            command_name=command_name,
            skill_name=skill_name,
        )
        if prompt_fail:
            print(json.dumps(prompt_fail))
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

    config_path = Path(args.config) if args.config else root / ("." + "cursor") / "workflow.config.json"
    if not config_path.is_file():
        config_path = root / "workflow.config.json"
    models = {}
    dispatch_cfg = {}
    if config_path.is_file():
        cfg = json.loads(config_path.read_text(encoding="utf-8"))
        models = cfg.get("models", {}) if isinstance(cfg, dict) else {}
        dispatch_cfg = cfg.get("dispatch", {}) if isinstance(cfg, dict) else {}

    tiers = models.get("tiers", {}) if isinstance(models, dict) else {}
    tiers, policy, mid_advisory = _normalize_tiers(tiers)
    _emit_mid_advisory(mid_advisory)
    roles = models.get("roles", {}) if isinstance(models, dict) else {}
    builder_tier = roles.get("builder", "build")
    fallback_tier = None
    if isinstance(dispatch_cfg, dict):
        raw = dispatch_cfg.get("unregisteredParentModelTier")
        if isinstance(raw, str) and raw.strip():
            fallback_tier = raw.strip()

    cfg_doc: dict = {}
    if config_path.is_file():
        try:
            loaded = json.loads(config_path.read_text(encoding="utf-8"))
            cfg_doc = loaded if isinstance(loaded, dict) else {}
        except json.JSONDecodeError:
            cfg_doc = {}

    role = (args.role or "").strip() or None
    boundary = (args.boundary or "").strip() or None
    reader_fail = evaluate_reader_role(role=role, boundary=boundary, override=override)
    if reader_fail:
        print(json.dumps(reader_fail))
        return 20
    if role == "reader" and args.tool_log:
        tool_fail = validate_reader_tool_log_file(Path(args.tool_log))
        if tool_fail:
            print(json.dumps(tool_fail))
            return 20

    signal_context = None
    if args.signal_context:
        try:
            signal_context = json.loads(args.signal_context)
        except json.JSONDecodeError:
            print(json.dumps({
                "verdict": "fail",
                "cause": "binding:invalid-signal-context",
                "retryable": False,
                "remediation": "pass valid JSON to --signal-context",
            }))
            return 20

    complexity = probe_complexity(
        static_tier=model_tier,
        signal_context=signal_context if isinstance(signal_context, dict) else None,
        config=cfg_doc,
    )
    if complexity.get("enabled") and complexity.get("chosenTier"):
        model_tier = str(complexity["chosenTier"])
        tier_model = tiers.get(model_tier)
        if isinstance(tier_model, str) and tier_model.strip():
            model_id = tier_model.strip()

    model_id, allow_fail = _apply_spawn_model_allowlist(
        model_id,
        root=root,
        agent=agent,
        command_name=command_name,
        skill_name=skill_name,
    )
    if allow_fail:
        print(json.dumps(allow_fail))
        return 20

    token_budget = resolve_token_budget(cfg_doc)

    # PRD 351 R16–R19 — advisory preflight before final model binding.
    task_type = command_name or skill_name or agent
    preflight = run_preflight(
        task_type=str(task_type or "unknown"),
        dimension_record={},
        config=cfg_doc,
        selected_model=model_id,
    )
    if preflight.get("advisory_applied") and preflight.get("selected_model"):
        model_id = str(preflight["selected_model"])
        resolved_tier = model_to_tier(model_id, tiers)
        if resolved_tier:
            model_tier = resolved_tier

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
        policy=policy,
    )
    if args.prompt:
        result["intensity"] = intensity
        result["intensitySource"] = intensity_source
        result["promptValidation"] = "pass"
        result["promptPath"] = str(Path(args.prompt))
    if role:
        result["role"] = role
    if boundary:
        result["boundary"] = boundary
    result["tokenBudget"] = token_budget
    result["complexityProbe"] = complexity
    result["advisoryLines"] = preflight.get("advisory_lines") or []
    result["advisoryApplied"] = bool(preflight.get("advisory_applied"))
    print(json.dumps(result))
    if result.get("verdict") == "fail":
        return 20
    return 0



if __name__ == "__main__":
    run_module_main(main)
