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
    CAUSE_UNBOUND,
    IN_REPO_PROVIDER,
    MemoryWriteBinding,
    MemoryWriteBindingError,
    assert_memory_write_binding,
    resolve_write_binding,
)
from sw_resolve_plugin_root import resolve_plugin_root
import shipwright_paths

RulesLoader = Callable[[Path, str], dict[str, Any]]
MutatingWriter = Callable[[MemoryWriteBinding], dict[str, Any]]

# Display-only alignment when unbound (PRD 279 D2 / R10). Never authorizes writes
# and MUST NOT ambient-default to Recallium.
UNBOUND_DISPLAY_GUIDANCE = IN_REPO_PROVIDER


class PreflightError(Exception):
    def __init__(self, message: str, *, cause: str, path: str | None = None) -> None:
        super().__init__(message)
        self.cause = cause
        self.path = path


class RulesLoadRequiredError(PreflightError):
    """Raised when search/store is used as a stand-in for rules-load."""

    def __init__(self, op: str) -> None:
        super().__init__(
            f"{op} is not a substitute for rules-load",
            cause="rules-load-required",
        )
        self.op = op


def load_allowlist(root: Path) -> set[str]:
    """Fail closed when the allowlist is absent, unreadable, or unparseable (PRD 342 R53)."""
    path = shipwright_paths.memory_rule_allowlist_path(root)
    if not path.is_file():
        # Resolver returns preferred path when neither layout exists.
        raise PreflightError(
            f"rule allowlist absent at {path}",
            cause="allowlist-missing",
            path=str(path),
        )
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise PreflightError(
            f"rule allowlist unreadable at {path}: {exc}",
            cause="allowlist-unreadable",
            path=str(path),
        ) from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise PreflightError(
            f"rule allowlist unparseable at {path}: {exc}",
            cause="allowlist-unparseable",
            path=str(path),
        ) from exc
    if not isinstance(data, list):
        raise PreflightError(
            f"rule allowlist must be a JSON array at {path}",
            cause="allowlist-unparseable",
            path=str(path),
        )
    return {str(item) for item in data}


def resolve_active_provider(root: Path) -> dict[str, Any]:
    """Resolve configured provider for rules-load / read preflight.

    Requires an explicit ``memory.provider`` (no ambient Recallium default).
    Does **not** authorize mutating writes — use ``resolve_provider(..., for_write=True)``
    or ``assert_write_binding`` before provider dispatch.
    """
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
        "writeAuthorized": False,
    }


def resolve_provider(
    root: Path,
    *,
    for_write: bool = False,
    operation: str = "memory-sync",
    category: str | None = None,
    cfg: dict[str, Any] | None = None,
    project_override: str | None = None,
) -> dict[str, Any]:
    """Resolve provider with an explicit read vs write posture (PRD 279 R10 / D2).

    - ``for_write=True``: hard-cut assert — unbound refuses with typed cause; never
      ambient-defaults to Recallium; no soft-warn write window.
    - ``for_write=False``: display/read resolution only. Unbound returns
      ``source=unbound`` with ``displayGuidance=in-repo`` (aligns with configuration
      guidance) and ``writeAuthorized=False``. Never returns ambient ``recallium``.
    """
    if for_write:
        binding = assert_write_binding(
            root,
            operation,
            category,
            cfg=cfg,
            project_override=project_override,
        )
        return {
            "verdict": "ok",
            "op": "resolve-provider",
            "purpose": "write",
            "provider": binding.provider,
            "project": binding.project,
            "source": binding.source,
            "writeAuthorized": True,
            "operation": operation,
            "category": category,
        }

    config = cfg if cfg is not None else load_workflow_config(root)
    binding = resolve_write_binding(root, config)
    if binding is not None:
        return {
            "verdict": "ok",
            "op": "resolve-provider",
            "purpose": "read",
            "provider": binding.provider,
            "project": binding.project,
            "source": binding.source,
            "writeAuthorized": False,
            "displayGuidance": binding.provider
            if binding.provider == IN_REPO_PROVIDER
            else None,
        }

    # Unbound read/display — align with in-repo guidance; do not ambient-default Recallium.
    return {
        "verdict": "ok",
        "op": "resolve-provider",
        "purpose": "read",
        "provider": None,
        "project": None,
        "source": "unbound",
        "writeAuthorized": False,
        "displayGuidance": UNBOUND_DISPLAY_GUIDANCE,
        "cause": CAUSE_UNBOUND,
        "reason": (
            "repository has no explicit memory binding; reads may continue for display, "
            "but writes require memory.provider + memory.project or "
            f".cursor/sw-memory.provider={IN_REPO_PROVIDER!r}"
        ),
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
    result = {
        "verdict": "ok",
        "op": "rules-load",
        "provider": provider,
        "rules": rules,
        "allowlist": sorted(allowlist),
        "revoked": sorted(revoked),
        "source": "rules-load",
    }
    if os.environ.get("SW_RULE_EFFECTIVENESS_DISABLED") != "1":
        try:
            from rule_effectiveness import emit_memory_preflight_rules_load

            telemetry = emit_memory_preflight_rules_load(
                root,
                provider=provider,
                rules=rules,
                allowlist_count=len(rules),
            )
            if telemetry.get("verdict") == "halt":
                raise PreflightError(
                    str(telemetry.get("errors")),
                    cause="rule-effectiveness-redaction",
                )
            result["ruleEffectiveness"] = telemetry
        except PreflightError:
            raise
        except Exception:
            pass
    return result


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


def exploration_query(
    root: Path,
    query: str,
    *,
    preflight_loader: Callable[[Path], dict[str, Any]] | None = None,
    query_fn: Callable[[Path, str, dict[str, Any]], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Exploration query mode — redacted historical context or non-blocking degraded result (R19, R42)."""
    cleaned = str(query or "").strip()
    if not cleaned:
        return {
            "verdict": "degraded",
            "source": "memory",
            "status": "absent",
            "blocking": False,
            "nonBlocking": True,
            "cause": "empty-query",
            "results": [],
            "redacted": True,
        }
    try:
        from exploration_security import lookup_historical_context

        result = lookup_historical_context(
            root,
            cleaned,
            preflight=preflight_loader or preflight,
            query_fn=query_fn,
        )
    except PreflightError as exc:
        return {
            "verdict": "degraded",
            "source": "memory",
            "status": "degraded",
            "blocking": False,
            "nonBlocking": True,
            "cause": exc.cause,
            "results": [],
            "redacted": True,
        }
    except Exception as exc:  # noqa: BLE001 — exploration must not block on provider faults
        return {
            "verdict": "degraded",
            "source": "memory",
            "status": "degraded",
            "blocking": False,
            "nonBlocking": True,
            "cause": "memory-provider-failure",
            "results": [],
            "redacted": True,
            "error": str(exc),
        }
    status = "available" if result.get("verdict") == "ok" else "degraded"
    return {
        **result,
        "source": "memory",
        "status": status,
        "blocking": False,
        "nonBlocking": True,
        "mode": "exploration-query",
        "redacted": bool(result.get("redacted", True)),
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


HistoricalSearchFn = Callable[[Path, str, dict[str, Any]], dict[str, Any]]


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
    resolve_p = sub.add_parser(
        "resolve-provider",
        help="Resolve provider for read (display) or write (hard-cut assert; no ambient Recallium)",
    )
    resolve_p.add_argument(
        "--for-write",
        action="store_true",
        help="Hard-cut write resolve — refuse unbound; never ambient-default Recallium",
    )
    resolve_p.add_argument("--operation", default="memory-sync")
    resolve_p.add_argument("--category", default=None)
    query_p = sub.add_parser(
        "exploration-query",
        help="Exploration historical query — redacted context or non-blocking degrade",
    )
    query_p.add_argument("--query", default="")
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    command = args.command or "rules-load"
    try:
        if command == "assert-sync-store":
            result = memory_sync_store_path(root, category=str(args.category))
        elif command == "resolve-provider":
            result = resolve_provider(
                root,
                for_write=bool(args.for_write),
                operation=str(args.operation),
                category=args.category,
            )
        elif command == "exploration-query":
            result = exploration_query(root, str(args.query))
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
                    "writeAuthorized": False,
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
