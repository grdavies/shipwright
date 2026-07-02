"""Shared helpers for Shipwright guardrail hooks."""

from __future__ import annotations

import json
from pathlib import Path

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
_KNOWN_MEMORY_PROVIDERS = frozenset({"recallium", "in-repo"})


def memory_provider_marker_path(root: Path) -> Path | None:
    for rel in _MARKER_PATHS:
        path = root / rel
        if path.is_file():
            return path
    return None


def read_memory_provider_marker(root: Path) -> str | None:
    path = memory_provider_marker_path(root)
    if path is None:
        return None
    try:
        value = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if value not in _KNOWN_MEMORY_PROVIDERS:
        return None
    return value


def resolve_memory_provider(root: Path, config: dict | None = None) -> str | None:
    """Config wins; else per-repo marker; else None."""
    if config is None:
        config = load_config(root)
    memory = config.get("memory", {}) if isinstance(config, dict) else {}
    if isinstance(memory, dict) and memory.get("provider"):
        provider = str(memory["provider"])
        if provider in _KNOWN_MEMORY_PROVIDERS:
            return provider
        return None
    return read_memory_provider_marker(root)


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


def synthetic_config_from_marker(root: Path) -> dict | None:
    provider = read_memory_provider_marker(root)
    if not provider:
        return None
    return {
        "memory": {
            "provider": provider,
            "project": root.name,
            "guardrails": {
                "enforceBeforeSubmit": True,
                "requireRuleClass": False,
            },
        }
    }


def rules_script_for_provider(plugin_root: Path, provider: str) -> Path | None:
    if provider not in _KNOWN_MEMORY_PROVIDERS:
        return None
    # Python-first (R31): the rule-fetcher adapters are authored as .py. Keep a
    # .sh fallback so a partially-migrated install still resolves a runnable script.
    for suffix in (".py", ".sh"):
        script = plugin_root / "providers" / f"{provider}-rules{suffix}"
        if script.is_file():
            return script
    return None


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
