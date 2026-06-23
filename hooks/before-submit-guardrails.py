#!/usr/bin/env python3
"""phase-flow v2 beforeSubmitPrompt hook — fail-closed rule-class guardrail enforcement (A1)."""

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
    guardrails_allow_empty,
    load_allowlist,
    load_config,
    read_stdin_json,
    workspace_root,
)

_DEFAULT_RULES_SCRIPT = _PLUGIN_ROOT / "providers" / "recallium-rules.sh"


def _rules_script() -> Path:
    override = os.environ.get("PF_RULES_SCRIPT", "").strip()
    if override:
        return Path(override)
    return _DEFAULT_RULES_SCRIPT


def _fetch_rules(root: Path) -> tuple[bool, list[dict]]:
    script = _rules_script()
    if not script.is_file():
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


def main() -> None:
    payload = read_stdin_json()
    root = workspace_root(payload)
    config = load_config(root)
    ok, rules = _fetch_rules(root)
    if not ok:
        _block(
            "phase-flow v2: cannot reach memory provider to load rule-class guardrails. "
            "Fix Recallium connectivity or set memory.connection.restBaseUrl (localhost only), then retry. "
            "(Credentials are env-sourced — never committed config.)"
        )
        return

    allowlist_status, allowlist = load_allowlist(root)
    if allowlist_status == "corrupt":
        _block(
            "phase-flow v2: pf-memory-rule-allowlist.json is corrupt. "
            "Fix or remove the file, then retry."
        )
        return

    rules = filter_rules_by_allowlist(rules, allowlist_status, allowlist)

    if not rules and not guardrails_allow_empty(config):
        _block(
            "phase-flow v2: no rule-class guardrails confirmed for this repo "
            "(provider reachable but zero allowlisted rules). "
            "Promote rules via /pf-memory-audit, update the allowlist, or set "
            "memory.guardrails.allowEmptyRules for bootstrap only."
        )
        return

    print(json.dumps({"continue": True}))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001
        _block(f"phase-flow v2 guardrail hook error: {exc}")
