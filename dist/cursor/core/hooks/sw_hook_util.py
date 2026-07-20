"""Shared helpers for Shipwright guardrail hooks."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

_ALLOWLIST_REL = (".cursor/sw-memory-rule-allowlist.json", "sw-memory-rule-allowlist.json")


def read_stdin_json() -> dict:
    import sys

    try:
        text = sys.stdin.read()
        return json.loads(text) if text.strip() else {}
    except (OSError, ValueError):
        return {}


def workspace_root(payload: dict) -> Path:
    roots = payload.get("workspace_roots")
    primary: Path | None = None
    if isinstance(roots, list):
        for root in roots:
            if isinstance(root, str) and root.strip():
                candidate = Path(root)
                if candidate.is_dir():
                    primary = candidate
                    break

    cwd_raw = payload.get("cwd")
    if isinstance(cwd_raw, str) and cwd_raw.strip():
        cwd = Path(cwd_raw)
        if cwd.is_dir():
            try:
                import subprocess
                import sys

                scripts = primary / "scripts" if primary else Path.cwd() / "scripts"
                if str(scripts) not in sys.path and scripts.is_dir():
                    sys.path.insert(0, str(scripts))
                from worktree_root import git_toplevel, is_shipwright_worktree
                from primary_checkout_guard import primary_worktree_path, canonical_repo_root

                cwd_top = git_toplevel(cwd)
                primary_top = primary_worktree_path(canonical_repo_root(primary or cwd_top))
                if cwd_top != primary_top and is_shipwright_worktree(cwd_top, primary_top):
                    return cwd_top
            except (ValueError, OSError, ImportError):
                pass

    if primary is not None:
        return primary
    if isinstance(cwd_raw, str) and cwd_raw.strip():
        candidate = Path(cwd_raw)
        if candidate.is_dir():
            return candidate
    return Path.cwd()


_CONFIG_PATHS = (".cursor/workflow.config.json", "workflow.config.json")
_MARKER_PATHS = (".cursor/sw-memory.provider", "sw-memory.provider")
_DEFAULT_IN_REPO_STORE = ".cursor/sw-memory"


def _ensure_scripts_importable(plugin_root: Path) -> None:
    scripts = plugin_root / "scripts"
    if scripts.is_dir():
        entry = str(scripts)
        if entry not in sys.path:
            sys.path.insert(0, entry)


def validate_hook_provider(plugin_root: Path, provider_id: str) -> bool:
    """Catalog + adapter integrity validation for hook trust (PRD 071 R3)."""
    value = str(provider_id or "").strip()
    if not value:
        return False
    _ensure_scripts_importable(plugin_root)
    from memory_provider_register import RegistrationError, validate_registration

    try:
        validate_registration(plugin_root, value)
        return True
    except RegistrationError:
        return False


def memory_provider_marker_path(root: Path) -> Path | None:
    for rel in _MARKER_PATHS:
        path = root / rel
        if path.is_file():
            return path
    return None


def read_memory_provider_marker(workspace: Path, *, plugin_root: Path) -> str | None:
    path = memory_provider_marker_path(workspace)
    if path is None:
        return None
    try:
        value = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not validate_hook_provider(plugin_root, value):
        return None
    return value


def resolve_memory_provider(
    workspace: Path,
    config: dict | None = None,
    *,
    plugin_root: Path,
) -> str | None:
    """Config wins; else per-repo marker; else None."""
    if config is None:
        config = load_config(workspace)
    memory = config.get("memory", {}) if isinstance(config, dict) else {}
    if isinstance(memory, dict) and memory.get("provider"):
        provider = str(memory["provider"]).strip()
        if validate_hook_provider(plugin_root, provider):
            return provider
        return None
    return read_memory_provider_marker(workspace, plugin_root=plugin_root)


def in_repo_store_dir(config: dict, root: Path) -> Path:
    memory = config.get("memory", {}) if isinstance(config, dict) else {}
    in_repo = memory.get("inRepo", {}) if isinstance(memory, dict) else {}
    rel = ".cursor/sw-memory"
    if isinstance(in_repo, dict) and in_repo.get("storeDir"):
        rel = str(in_repo["storeDir"])
    return root / rel


def in_repo_commit_mode(config: dict) -> str:
    memory = config.get("memory", {}) if isinstance(config, dict) else {}
    in_repo = memory.get("inRepo", {}) if isinstance(memory, dict) else {}
    if isinstance(in_repo, dict) and in_repo.get("commitMode"):
        return str(in_repo["commitMode"])
    return "committed"


def synthetic_config_from_marker(workspace: Path, *, plugin_root: Path) -> dict | None:
    provider = read_memory_provider_marker(workspace, plugin_root=plugin_root)
    if not provider:
        return None
    return {
        "memory": {
            "provider": provider,
            "project": workspace.name,
            "guardrails": {
                "enforceBeforeSubmit": True,
                "requireRuleClass": False,
            },
        }
    }


def _prefer_py_script(path: Path) -> Path | None:
    if path.suffix == ".py" and path.is_file():
        return path
    py_path = path.with_suffix(".py")
    if py_path.is_file():
        return py_path
    if path.suffix == ".sh" and path.is_file():
        return path
    return None


def _resolve_config_value(config: dict[str, Any], dotted_key: str) -> Any:
    current: Any = config
    for part in dotted_key.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def _is_configured(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return value.strip().lower() not in {"", "none", "off", "unconfigured", "null"}
    return True


def rules_script_for_provider(
    plugin_root: Path,
    provider: str,
    *,
    config: dict | None = None,
) -> Path | None:
    """Resolve catalog-registered rules script after validator gate (PRD 071 R3/R4)."""
    if not validate_hook_provider(plugin_root, provider):
        return None
    _ensure_scripts_importable(plugin_root)
    from capability_trust import authorize_memory_rules_script
    from memory_provider_catalog import get_provider, load_catalog
    from memory_provider_register import resolve_rules_script

    try:
        catalog = load_catalog(plugin_root)
        row = get_provider(catalog, provider)
        rules_rel = str(row.get("rulesScript") or "").strip()
        if not rules_rel:
            return None
        scripts_root = plugin_root / "scripts"
        resolved_plugin = plugin_root
        if scripts_root.is_dir():
            from sw_resolve_plugin_root import resolve_plugin_root

            resolved_plugin = resolve_plugin_root(scripts_root)
        path = resolve_rules_script(plugin_root, resolved_plugin, rules_rel)
    except Exception:
        return None
    resolved = _prefer_py_script(path)
    if resolved is None:
        return None

    memory_config = config if isinstance(config, dict) else {}
    if not memory_config.get("memory"):
        memory_config = {"memory": {"provider": provider}}
    auth = authorize_memory_rules_script(
        provider,
        resolved,
        {"config": memory_config},
        resolve_config_value=_resolve_config_value,
        is_configured=_is_configured,
    )
    if not auth.get("authorized"):
        return None
    return resolved


def workflow_config_path(root: Path) -> Path | None:
    for rel in _CONFIG_PATHS:
        path = root / rel
        if path.is_file():
            return path
    return None


def load_config(root: Path) -> dict:
    path = workflow_config_path(root)
    if path is None:
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def load_allowlist(root: Path) -> tuple[str, set[str] | None]:
    """Returns (status, allowlist). status: absent | ok | corrupt."""
    for rel in _ALLOWLIST_REL:
        path = root / rel
        if path.is_file():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    return "ok", {str(x) for x in data}
            except (OSError, ValueError):
                return "corrupt", None
    return "absent", None


def filter_rules_by_allowlist(rules: list[dict], allowlist_status: str, allowlist: set[str] | None) -> list[dict]:
    if allowlist_status != "ok" or allowlist is None:
        return rules
    return [
        r
        for r in rules
        if str(r.get("id", "")) in allowlist or r.get("summary", "") in allowlist
    ]


def guardrails_require_rule_class(config: dict) -> bool:
    """When true, block until at least one allowlisted rule-class memory exists (mature repos)."""
    memory = config.get("memory", {}) if isinstance(config, dict) else {}
    guardrails = memory.get("guardrails", {}) if isinstance(memory, dict) else {}
    if "requireRuleClass" in guardrails:
        return bool(guardrails["requireRuleClass"])
    if guardrails.get("allowEmptyRules") is False:
        return True
    return False


def guardrails_allow_empty(config: dict) -> bool:
    """Deprecated alias — prefer requireRuleClass:false (default)."""
    return not guardrails_require_rule_class(config)


def guardrails_enforce_before_submit(config: dict) -> bool:
    """When false, beforeSubmitPrompt guardrail hook is a no-op (continue always)."""
    memory = config.get("memory", {}) if isinstance(config, dict) else {}
    guardrails = memory.get("guardrails", {}) if isinstance(memory, dict) else {}
    return guardrails.get("enforceBeforeSubmit", True)
