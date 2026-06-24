#!/usr/bin/env python3
"""before-submit-guardrails.py — extended for provider dispatch + marker (plan 002 U3/U4)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_PLUGIN_ROOT = _HERE.parent
sys.path.insert(0, str(_HERE))

from pf_hook_util import (  # noqa: E402
    filter_rules_by_allowlist,
    guardrails_enforce_before_submit,
    guardrails_require_rule_class,
    load_allowlist,
    load_config,
    read_stdin_json,
    resolve_memory_provider,
    rules_script_for_provider,
    synthetic_config_from_marker,
    workflow_config_path,
    workspace_root,
)

_DEFAULT_RULES_SCRIPT = _PLUGIN_ROOT / "providers" / "recallium-rules.sh"


def _rules_script(root: Path, config: dict) -> Path | None:
    override = os.environ.get("PF_RULES_SCRIPT", "").strip()
    if override:
        return Path(override)
    provider = resolve_memory_provider(root, config)
    if not provider:
        return None
    return rules_script_for_provider(_PLUGIN_ROOT, provider)


def _fetch_rules(root: Path, config: dict) -> tuple[bool, list[dict]]:
    script = _rules_script(root, config)
    if script is None or not script.is_file():
        return False, []
    env = os.environ.copy()
    env["PF_WORKSPACE_ROOT"] = str(root)
    env["PYTHONPATH"] = os.pathsep.join(
        [str(_PLUGIN_ROOT), env.get("PYTHONPATH", "")]
    ).strip(os.pathsep)
    try:
        proc = subprocess.run(
            ["bash", str(script)],
            capture_output=True,
            text=True,
            timeout=5,
            env=env,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False, []
    if proc.returncode != 0:
        return False, []
    try:
        payload = json.loads(proc.stdout or "{}")
    except ValueError:
        return False, []
    if not payload.get("ok", False):
        return False, []
    rules = payload.get("rules", [])
    if not isinstance(rules, list):
        return False, []
    return True, [r for r in rules if isinstance(r, dict)]


def _block(message: str) -> None:
    print(json.dumps({"continue": False, "user_message": message}))


def _provider_unreachable_message(provider: str | None) -> str:
    name = provider or "memory"
    if provider == "recallium":
        return (
            "phase-flow v2: cannot reach Recallium to load rule-class guardrails. "
            "Fix Recallium connectivity or set memory.connection.restBaseUrl (localhost only), then retry. "
            "(Credentials are env-sourced — never committed config.)"
        )
    if provider == "in-repo":
        return (
            "phase-flow v2: in-repo rules adapter failed to load rule-class guardrails from disk. "
            "Check .cursor/pf-memory/rules/ and run /pf-setup to validate the store."
        )
    return (
        f"phase-flow v2: cannot load rule-class guardrails for provider '{name}'. "
        "Fix memory provider configuration or run /pf-setup, then retry."
    )


def main() -> None:
    payload = read_stdin_json()
    root = workspace_root(payload)
    config_path = workflow_config_path(root)

    if config_path is None:
        synthetic = synthetic_config_from_marker(root)
        if synthetic is None:
            print(json.dumps({"continue": True}))
            return
        config = synthetic
    else:
        config = load_config(root)

    if not guardrails_enforce_before_submit(config):
        print(json.dumps({"continue": True}))
        return

    provider = resolve_memory_provider(root, config)
    ok, rules = _fetch_rules(root, config)
    if not ok:
        _block(_provider_unreachable_message(provider))
        return

    allowlist_status, allowlist = load_allowlist(root)
    if allowlist_status == "corrupt":
        _block(
            "phase-flow v2: pf-memory-rule-allowlist.json is corrupt. "
            "Fix or remove the file, then retry."
        )
        return

    rules = filter_rules_by_allowlist(rules, allowlist_status, allowlist)

    if not rules and guardrails_require_rule_class(config):
        _block(
            "phase-flow v2: this repo requires at least one allowlisted rule-class guardrail "
            "(memory.guardrails.requireRuleClass is true) but none are confirmed. "
            "Promote rules via /pf-memory-audit and update .cursor/pf-memory-rule-allowlist.json, "
            "or set requireRuleClass to false for greenfield/bootstrap repos."
        )
        return

    print(json.dumps({"continue": True}))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001
        _block(f"phase-flow v2 guardrail hook error: {exc}")
