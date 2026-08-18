#!/usr/bin/env python3
"""Work-start memory preflight: resolve provider, rules-load, and write-binding assert (PRD 277/279)."""

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
    load_revoked_ids,
    needs_reconcile_path,
)
from memory_write_binding import (
    MemoryWriteBinding,
    MemoryWriteBindingError,
    assert_memory_write_binding,
)
from sw_resolve_plugin_root import resolve_plugin_root

RulesLoader = Callable[[Path, str], dict[str, Any]]
MutatingWriter = Callable[[MemoryWriteBinding], dict[str, Any]]


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
    if needs_reconcile_path(root).is_file():
        raise PreflightError(
            "rules-load refused while needs-reconcile is set",
            cause="needs-reconcile",
        )
    resolved = resolve_active_provider(root)
    provider = resolved["provider"]
    payload = (loader or default_rules_loader)(root, provider)
    raw_rules = payload.get("rules") if isinstance(payload, dict) else []
    if not isinstance(raw_rules, list):
        raw_rules = []
    allowlist = load_allowlist(root)
    revoked = load_revoked_ids(root)
    rules = [
        entry
        for entry in filter_allowlisted(raw_rules, allowlist)
        if _rule_id(entry) not in revoked
    ]
    return {
        "verdict": "ok",
        "op": "rules-load",
        "provider": provider,
        "rules": rules,
        "allowlist": sorted(allowlist),
        "revoked": sorted(revoked),
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


def assert_write_binding(
    root: Path,
    operation: str,
    category: str | None = None,
    *,
    cfg: dict[str, Any] | None = None,
    project_override: str | None = None,
) -> MemoryWriteBinding:
    """Fail-closed write-binding chokepoint before provider dispatch (PRD 279 R9).

    Mutating callers (including ``/sw-memory-sync`` store) must invoke this
    immediately before adapter dispatch. Unbound writes raise
    ``MemoryWriteBindingError`` after audit emission.
    """
    return assert_memory_write_binding(
        root,
        operation,
        category,
        cfg=cfg,
        project_override=project_override,
    )


def dispatch_mutating_store(
    root: Path,
    *,
    operation: str,
    category: str | None,
    writer: MutatingWriter,
    cfg: dict[str, Any] | None = None,
    project_override: str | None = None,
) -> dict[str, Any]:
    """Assert write binding, then invoke ``writer(binding)`` (no silent unbound fallback)."""
    binding = assert_write_binding(
        root,
        operation,
        category,
        cfg=cfg,
        project_override=project_override,
    )
    result = writer(binding)
    if not isinstance(result, dict):
        return {
            "verdict": "ok",
            "action": operation,
            "provider": binding.provider,
            "project": binding.project,
            "source": binding.source,
            "category": category,
            "writerResult": result,
        }
    out = dict(result)
    out.setdefault("verdict", "ok")
    out.setdefault("action", operation)
    out["provider"] = binding.provider
    out["project"] = binding.project
    out["source"] = binding.source
    if category is not None:
        out.setdefault("category", category)
    return out


def memory_sync_store_path(
    root: Path,
    *,
    category: str,
    writer: MutatingWriter | None = None,
    cfg: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """``/sw-memory-sync`` mutating store entry — assert then dispatch (R9 / D4)."""

    def _default_writer(binding: MemoryWriteBinding) -> dict[str, Any]:
        return {
            "verdict": "ok",
            "action": "memory-sync",
            "category": category,
            "bindingSource": binding.source,
        }

    return dispatch_mutating_store(
        root,
        operation="memory-sync",
        category=category,
        writer=writer or _default_writer,
        cfg=cfg,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Resolve provider, load allowlisted rules, and assert write bindings"
    )
    parser.add_argument("--root", default=".")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("rules-load", help="Resolve provider and load allowlisted rules (default)")
    sync_p = sub.add_parser(
        "assert-sync-store",
        help="Assert write binding for /sw-memory-sync store (no provider dispatch)",
    )
    sync_p.add_argument("--category", default="learning")
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    command = args.command or "rules-load"
    try:
        if command == "assert-sync-store":
            result = memory_sync_store_path(root, category=str(args.category))
        else:
            result = preflight(root)
    except MemoryWriteBindingError as exc:
        refuse = exc.refuse
        print(
            json.dumps(
                {
                    "verdict": "fail",
                    "error": refuse.reason,
                    "cause": refuse.cause,
                    "operation": refuse.operation,
                    "category": refuse.category,
                },
                indent=2,
            )
        )
        return 20
    except (PreflightError, RegistrationError) as exc:
        cause = getattr(exc, "cause", "preflight-failed")
        print(json.dumps({"verdict": "fail", "error": str(exc), "cause": cause}, indent=2))
        return 20
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
