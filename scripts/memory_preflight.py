#!/usr/bin/env python3
"""Work-start memory preflight: resolve provider, then rules-load only (PRD 277)."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

from host_lib import load_workflow_config
from memory_lib import memory_section
from memory_provider_catalog import get_provider, load_catalog
from memory_provider_register import RegistrationError, resolve_rules_script, validate_registration
from memory_rules_promote import (
    SUPPORTED_PROVIDERS,
    RuleWriteRefused,
    configured_provider,
)
from sw_resolve_plugin_root import resolve_plugin_root

RulesLoader = Callable[[Path, str], dict[str, Any]]


class PreflightError(Exception):
    def __init__(self, message: str, *, cause: str) -> None:
        super().__init__(message)
        self.cause = cause


class RulesLoadRequiredError(PreflightError):
    """Raised when search/store is used as a stand-in for rules-load."""

    def __init__(self, op: str) -> None:
        super().__init__(
            f"{op} is not a substitute for rules-load",
            cause="rules-load-required",
        )
        self.op = op


def load_allowlist(root: Path) -> set[str]:
    path = root / ".cursor" / "sw-memory-rule-allowlist.json"
    if not path.is_file():
        return set()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raise PreflightError("rule allowlist unreadable", cause="allowlist-corrupt")
    if not isinstance(data, list):
        raise PreflightError("rule allowlist must be a JSON array", cause="allowlist-corrupt")
    return {str(item) for item in data}


def resolve_active_provider(root: Path) -> dict[str, Any]:
    try:
        provider = configured_provider(root)
    except RuleWriteRefused as exc:
        raise PreflightError(str(exc), cause=exc.cause) from exc
    if provider not in SUPPORTED_PROVIDERS:
        raise PreflightError(
            f"memory.provider {provider!r} is not a supported rules provider",
            cause="provider-unsupported",
        )
    try:
        registration = validate_registration(root, provider)
    except RegistrationError as exc:
        raise PreflightError(str(exc), cause=exc.cause) from exc
    cfg = load_workflow_config(root)
    return {
        "provider": provider,
        "project": str(memory_section(cfg).get("project") or ""),
        "registration": registration,
    }


def _catalog_rules_script(root: Path, provider: str) -> Path:
    catalog = load_catalog(root)
    row = get_provider(catalog, provider)
    rules_rel = str(row.get("rulesScript") or "").strip()
    if not rules_rel:
        raise PreflightError("catalog row missing rulesScript", cause="rules-script-missing")
    plugin_root = resolve_plugin_root(root / "scripts") if (root / "scripts").is_dir() else root
    resolved = resolve_rules_script(root, plugin_root, rules_rel)
    if resolved is None or not Path(resolved).is_file():
        raise PreflightError(f"rules-load script missing: {rules_rel}", cause="rules-script-missing")
    return Path(resolved)


def default_rules_loader(root: Path, provider: str) -> dict[str, Any]:
    script = _catalog_rules_script(root, provider)
    env = os.environ.copy()
    env["SW_WORKSPACE_ROOT"] = str(root)
    proc = subprocess.run(
        [sys.executable, str(script)],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    try:
        payload = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise PreflightError("rules-load returned non-JSON", cause="rules-load-invalid") from exc
    if proc.returncode != 0 and not payload.get("ok", True):
        raise PreflightError(
            str(payload.get("error") or "rules-load failed"),
            cause="rules-load-failed",
        )
    return payload if isinstance(payload, dict) else {"rules": []}


def _rule_id(entry: Any) -> str:
    if isinstance(entry, dict):
        return str(entry.get("id") or entry.get("ruleId") or entry.get("name") or "").strip()
    return str(entry).strip()


def filter_allowlisted(rules: list[Any], allowlist: set[str]) -> list[Any]:
    if not allowlist:
        return []
    kept: list[Any] = []
    for entry in rules:
        rid = _rule_id(entry)
        if rid and rid in allowlist:
            kept.append(entry)
    return kept


def rules_load(
    root: Path,
    *,
    loader: RulesLoader | None = None,
) -> dict[str, Any]:
    resolved = resolve_active_provider(root)
    provider = resolved["provider"]
    payload = (loader or default_rules_loader)(root, provider)
    raw_rules = payload.get("rules") if isinstance(payload, dict) else []
    if not isinstance(raw_rules, list):
        raw_rules = []
    allowlist = load_allowlist(root)
    rules = filter_allowlisted(raw_rules, allowlist)
    return {
        "verdict": "ok",
        "op": "rules-load",
        "provider": provider,
        "rules": rules,
        "allowlist": sorted(allowlist),
        "source": "rules-load",
    }


def search_cannot_load_rules() -> None:
    raise RulesLoadRequiredError("search")


def store_cannot_load_rules() -> None:
    raise RulesLoadRequiredError("store")


def preflight(root: Path, *, loader: RulesLoader | None = None) -> dict[str, Any]:
    resolved = resolve_active_provider(root)
    loaded = rules_load(root, loader=loader)
    return {
        "verdict": "ok",
        "action": "memory-preflight",
        "provider": resolved["provider"],
        "project": resolved["project"],
        "rulesLoad": loaded,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Resolve provider and load allowlisted rules")
    parser.add_argument("--root", default=".")
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    try:
        result = preflight(root)
    except (PreflightError, RegistrationError) as exc:
        cause = getattr(exc, "cause", "preflight-failed")
        print(json.dumps({"verdict": "fail", "error": str(exc), "cause": cause}, indent=2))
        return 20
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
