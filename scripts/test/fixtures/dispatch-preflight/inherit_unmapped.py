#!/usr/bin/env python3
"""Dispatch-preflight inherit+unmapped-agent fixture (PRD 057 R18 / gap-047).

Proves the R18 disposition: `wave_preflight.py cmd_dispatch` (and its
`resolve-model-tier.py` fallback) no longer dead-ends on the generic
`binding:no-model` failure when an `inherit` orchestrator (e.g. `sw-doc`)
dispatches an agent absent from `models.routing.agents` (e.g. `explore`).
Resolution order: agent map -> `models.roles` fallback -> actionable
remediation — never a bare `binding:no-model`, and never forcing the caller
into inline authoring.

ZOMBIES: Zero (unmapped agent, e.g. `explore`) · Interfaces (agent map ->
`models.roles` -> remediation) · Exceptions (no-model remediation, distinct
cause) · State (no forced inline authoring — dispatch either succeeds with a
concrete model or halts with an actionable remediation).

Runs fully offline in disposable git-initialized sandboxes with synthetic
`workflow.config.json` overrides, plus one direct check against the literal
PRD example (`--agent explore --command sw-doc`) using this repo's own
shipped config to prove the concrete end-to-end fix.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parents[3]
WAVE_PREFLIGHT = ROOT / "scripts" / "wave_preflight.py"
RESOLVE_MODEL_TIER = ROOT / "scripts" / "resolve-model-tier.py"


def _git_init(root: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=str(root), check=True)


def _write_config(root: Path, name: str, config: dict[str, Any]) -> Path:
    path = root / name
    path.write_text(json.dumps(config), encoding="utf-8")
    return path


def _sandbox_config(*, roles: dict[str, str] | None, agents: dict[str, str] | None) -> dict[str, Any]:
    return {
        "models": {
            "tiers": {"cheap": "cheap-m", "build": "build-m", "mid": "mid-m", "deep": "deep-m"},
            "roles": roles or {},
            "routing": {
                "commands": {"sw-doc": "inherit"},
                "agents": agents or {},
            },
        }
    }


def _run_resolve_model_tier(config_path: Path, *, agent: str, command: str) -> tuple[int, dict[str, Any]]:
    proc = subprocess.run(
        [
            sys.executable, str(RESOLVE_MODEL_TIER),
            "--agent", agent, "--command", command, "--config", str(config_path),
        ],
        capture_output=True, text=True, check=False,
    )
    try:
        data = json.loads(proc.stdout.strip() or "{}")
    except json.JSONDecodeError:
        data = {}
    return proc.returncode, data


def _run_dispatch_preflight(
    sandbox_root: Path, config_path: Path, *, dispatch_id: str, agent: str, command: str
) -> tuple[int, dict[str, Any]]:
    proc = subprocess.run(
        [
            sys.executable, str(WAVE_PREFLIGHT), str(sandbox_root), "dispatch", "preflight",
            "--dispatch-id", dispatch_id, "--agent", agent, "--command", command,
            "--config", str(config_path),
        ],
        capture_output=True, text=True, check=False,
    )
    try:
        data = json.loads(proc.stdout.strip() or "{}")
    except json.JSONDecodeError:
        data = {}
    return proc.returncode, data


def check_resolves_via_agent_map(sandbox_root: Path) -> dict[str, Any]:
    """Unmapped-for-command, but agent IS in models.routing.agents -> agent map wins."""
    cfg = _write_config(
        sandbox_root, "cfg-agent-map.json",
        _sandbox_config(roles={"builder": "build"}, agents={"explore": "deep"}),
    )
    ec, data = _run_resolve_model_tier(cfg, agent="explore", command="sw-doc")
    ok = (
        ec == 0
        and data.get("modelId") == "deep-m"
        and data.get("tier") == "deep"
        and "agent-map" in str(data.get("source") or "")
    )
    return {"name": "resolves-via-agent-map", "ok": ok, "detail": {"exitCode": ec, "payload": data}}


def check_resolves_via_roles_fallback(sandbox_root: Path) -> dict[str, Any]:
    """Agent absent from models.routing.agents -> falls back to models.roles.builder."""
    cfg = _write_config(
        sandbox_root, "cfg-roles-fallback.json",
        _sandbox_config(roles={"builder": "build"}, agents={}),
    )
    ec, data = _run_resolve_model_tier(cfg, agent="explore", command="sw-doc")
    ok = (
        ec == 0
        and data.get("modelId") == "build-m"
        and data.get("tier") == "build"
        and "roles.builder-fallback" in str(data.get("source") or "")
    )
    return {"name": "resolves-via-roles-fallback", "ok": ok, "detail": {"exitCode": ec, "payload": data}}


def check_exhausted_yields_remediation_not_binding_no_model(sandbox_root: Path) -> dict[str, Any]:
    """No agent map entry and no models.roles.builder -> actionable remediation, never binding:no-model."""
    cfg = _write_config(
        sandbox_root, "cfg-no-fallback.json",
        _sandbox_config(roles={}, agents={}),
    )
    ec, data = _run_resolve_model_tier(cfg, agent="explore", command="sw-doc")
    ok = (
        ec == 20
        and data.get("verdict") == "fail"
        and data.get("cause") != "binding:no-model"
        and bool(data.get("remediation"))
    )
    return {
        "name": "exhausted-yields-remediation-not-binding-no-model",
        "ok": ok,
        "detail": {"exitCode": ec, "payload": data},
    }


def check_dispatch_preflight_end_to_end_pass(sandbox_root: Path) -> dict[str, Any]:
    """wave_preflight cmd_dispatch: unmapped agent under inherit resolves a concrete model."""
    cfg = _write_config(
        sandbox_root, "cfg-dispatch-pass.json",
        _sandbox_config(roles={"builder": "build"}, agents={}),
    )
    ec, data = _run_dispatch_preflight(
        sandbox_root, cfg, dispatch_id=f"fixture-{uuid.uuid4().hex[:8]}", agent="explore", command="sw-doc",
    )
    ok = ec == 0 and data.get("verdict") == "pass" and bool(data.get("modelId"))
    return {"name": "dispatch-preflight-end-to-end-pass", "ok": ok, "detail": {"exitCode": ec, "payload": data}}


def check_dispatch_preflight_end_to_end_remediation(sandbox_root: Path) -> dict[str, Any]:
    """wave_preflight cmd_dispatch: exhausted fallback surfaces remediation, not binding:no-model."""
    cfg = _write_config(
        sandbox_root, "cfg-dispatch-remediation.json",
        _sandbox_config(roles={}, agents={}),
    )
    ec, data = _run_dispatch_preflight(
        sandbox_root, cfg, dispatch_id=f"fixture-{uuid.uuid4().hex[:8]}", agent="explore", command="sw-doc",
    )
    ok = (
        ec == 20
        and data.get("verdict") == "fail"
        and data.get("cause") != "binding:no-model"
        and bool(data.get("remediation"))
    )
    return {
        "name": "dispatch-preflight-end-to-end-remediation",
        "ok": ok,
        "detail": {"exitCode": ec, "payload": data},
    }


def check_bound_reviewer_agent_map_unaffected(sandbox_root: Path) -> dict[str, Any]:
    """R39b precedence for a bound agent (native-panel/reviewer) is unchanged by the R18 fallback."""
    cfg = _write_config(
        sandbox_root, "cfg-bound-agent.json",
        _sandbox_config(roles={"builder": "build"}, agents={"correctness": "deep"}),
    )
    ec, data = _run_resolve_model_tier(cfg, agent="correctness", command="sw-doc")
    ok = (
        ec == 0
        and data.get("modelId") == "deep-m"
        and data.get("source") == "routing.agents"
    )
    return {"name": "bound-reviewer-agent-map-unaffected", "ok": ok, "detail": {"exitCode": ec, "payload": data}}


def check_top_level_inherit_without_agent_unaffected(sandbox_root: Path) -> dict[str, Any]:
    """No --agent (pure orchestrator dispatch, e.g. sw-ship) keeps the intentional inherit/null pass-through."""
    cfg = _write_config(
        sandbox_root, "cfg-top-level.json",
        _sandbox_config(roles={"builder": "build"}, agents={}),
    )
    proc = subprocess.run(
        [sys.executable, str(RESOLVE_MODEL_TIER), "--command", "sw-doc", "--config", str(cfg)],
        capture_output=True, text=True, check=False,
    )
    try:
        data = json.loads(proc.stdout.strip() or "{}")
    except json.JSONDecodeError:
        data = {}
    ok = proc.returncode == 0 and data.get("tier") == "inherit" and data.get("modelId") is None
    return {
        "name": "top-level-inherit-without-agent-unaffected",
        "ok": ok,
        "detail": {"exitCode": proc.returncode, "payload": data},
    }


def check_literal_prd_example_against_shipped_config() -> dict[str, Any]:
    """The literal R18 example (`--agent explore --command sw-doc`) against this repo's own
    shipped `.cursor/workflow.config.json` resolves a concrete model or an actionable
    remediation — never `binding:no-model` — proving the concrete production fix end-to-end."""
    ec, data = _run_dispatch_preflight(
        ROOT, ROOT / ".cursor" / "workflow.config.json",
        dispatch_id=f"fixture-r18-{uuid.uuid4().hex[:8]}", agent="explore", command="sw-doc",
    )
    resolved = ec == 0 and data.get("verdict") == "pass" and bool(data.get("modelId"))
    remediated = ec == 20 and data.get("verdict") == "fail" and data.get("cause") != "binding:no-model"
    ok = resolved or remediated
    return {
        "name": "literal-prd-example-against-shipped-config",
        "ok": ok,
        "detail": {"exitCode": ec, "payload": data},
    }


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="sw-dispatch-preflight-r18-") as tmp:
        sandbox_root = Path(tmp)
        _git_init(sandbox_root)
        checks = [
            check_resolves_via_agent_map(sandbox_root),
            check_resolves_via_roles_fallback(sandbox_root),
            check_exhausted_yields_remediation_not_binding_no_model(sandbox_root),
            check_dispatch_preflight_end_to_end_pass(sandbox_root),
            check_dispatch_preflight_end_to_end_remediation(sandbox_root),
            check_bound_reviewer_agent_map_unaffected(sandbox_root),
            check_top_level_inherit_without_agent_unaffected(sandbox_root),
            check_literal_prd_example_against_shipped_config(),
        ]
    failures = [c for c in checks if not c["ok"]]
    verdict = "pass" if not failures else "fail"
    report = {
        "fixture": "dispatch-preflight-inherit-unmapped",
        "rid": "R18",
        "verdict": verdict,
        "checks": checks,
        "failures": failures,
    }
    print(json.dumps(report, ensure_ascii=False))
    return 0 if verdict == "pass" else 20


if __name__ == "__main__":
    raise SystemExit(main())
