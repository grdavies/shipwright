#!/usr/bin/env python3
"""phase-flow v2 sessionStart hook — best-effort context + rule injection (fail-open)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_PLUGIN_ROOT = _HERE.parent
_CONTEXT_TEMPLATE = _HERE / "session-context.md"
_DEFAULT_RULES_SCRIPT = _PLUGIN_ROOT / "providers" / "recallium-rules.sh"

sys.path.insert(0, str(_HERE))
from pf_hook_util import (  # noqa: E402
    filter_rules_by_allowlist,
    load_allowlist,
    load_config,
    read_stdin_json,
    workspace_root,
)


def memory_binding(config: dict, root: Path) -> dict:
    memory = config.get("memory", {}) if isinstance(config, dict) else {}
    if not isinstance(memory, dict):
        return {}
    resolved = dict(memory)
    if resolved.get("provider", "recallium") == "recallium" and not resolved.get("project"):
        resolved["project"] = root.name
        resolved["_projectInferredFromWorkspace"] = True
    return resolved


def _memory_line(memory: dict) -> str:
    provider = memory.get("provider", "recallium")
    project = memory.get("project", "(unset — set memory.project in workflow.config.json)")
    scope = memory.get("defaultScope", "project")
    source = " (inferred from workspace root)" if memory.get("_projectInferredFromWorkspace") else ""
    return (
        f"- Memory provider: **{provider}**, project: **{project}**{source}, default scope: **{scope}**.\n"
        f"- Run a memory-preflight `load-context` for project `{project}` now, then targeted "
        f"`search` per command. Route every memory op through the `{provider}` adapter "
        f"(`providers/{provider}.md`) — never call a provider tool directly."
    )


def _fetch_rules(root: Path) -> list[str]:
    script = Path(os.environ.get("PF_RULES_SCRIPT", str(_DEFAULT_RULES_SCRIPT)))
    if not script.is_file():
        return []
    env = os.environ.copy()
    env["PF_WORKSPACE_ROOT"] = str(root)
    env["PYTHONPATH"] = os.pathsep.join([str(_PLUGIN_ROOT), env.get("PYTHONPATH", "")]).strip(os.pathsep)
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
        return []
    if proc.returncode != 0:
        return []
    try:
        payload = json.loads(proc.stdout or "{}")
    except ValueError:
        return []
    if not payload.get("ok", False):
        return []
    rules = payload.get("rules", [])
    if not isinstance(rules, list):
        return []

    allowlist_status, allowlist = load_allowlist(root)
    rules = filter_rules_by_allowlist(
        [r for r in rules if isinstance(r, dict)], allowlist_status, allowlist
    )
    lines: list[str] = []
    for item in rules:
        text = (item.get("summary") or "").strip()
        if text:
            lines.append(text)
    return lines


def main() -> None:
    payload = read_stdin_json()
    root = workspace_root(payload)

    parts: list[str] = []
    try:
        parts.append(_CONTEXT_TEMPLATE.read_text(encoding="utf-8").strip())
    except OSError:
        parts.append("This repo uses the phase-flow v2 workflow plugin.")

    memory = memory_binding(load_config(root), root)
    parts.append("\n## Resolved memory binding\n\n" + _memory_line(memory))

    rules = _fetch_rules(root)
    if rules:
        block = "\n\n".join(rules)
        parts.append(
            "\n## Standing memory rules (auto-injected)\n\n"
            "Provider-sourced guardrails (allowlist-filtered). Git state and frozen specs outrank memory.\n\n"
            "<pf-guardrails provider=\"recallium\">\n"
            + block
            + "\n</pf-guardrails>"
        )

    print(json.dumps({"additional_context": "\n".join(parts)}, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"additional_context": f"(phase-flow v2 hook degraded: {exc})"}))
        sys.exit(0)
