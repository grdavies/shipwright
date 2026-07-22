#!/usr/bin/env python3
"""Obsidian out-of-band rule-fetcher for hooks (PRD 076 R22–R26).

Emits JSON rules to stdout for guardrail injection. Agent-session ops use Obsidian
Local REST API MCP on loopback; this script is the hook transport only (catalog
``hookTransport.ruleFetch: out-of-band-script``).

Primary path: read markdown notes from ``memory.obsidian.vaultPath`` /
``rulesDirectory`` on disk (realpath-confined). Optional loopback REST fetch uses
the same host + credential policy as agent ops (``OBSIDIAN_API_KEY`` / tokenEnv).

Fixed-argv contract: no free-form caller args; optional ``ruleFetchCommand`` override
must match the allowlisted executable + exact argv template (no shell / eval).

Hooks MUST NOT open an MCP handshake. When ``memory.obsidian.failClosed`` is true
(default), rule-fetch failures block hook injection.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

PROVIDER_ID = "obsidian"
MAX_RULE_CHARS = 2000
MAX_RULES = 25
MAX_OUTPUT_BYTES = 64_000
DEFAULT_RULES_DIR = "rules"
DEFAULT_FAIL_CLOSED = True
DEFAULT_MCP_BASE = "http://127.0.0.1:27123"
DEFAULT_TOKEN_ENV = "OBSIDIAN_API_KEY"
LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})

_CONTROL_CHAR_RE = re.compile(r"[\000-\010\013\014\016-\037]")


def _emit(payload: dict[str, Any], *, exit_code: int) -> int:
    raw = json.dumps(payload, ensure_ascii=False)
    encoded = raw.encode("utf-8")
    if len(encoded) > MAX_OUTPUT_BYTES:
        payload = {
            "ok": False,
            "error": "rules output exceeds size cap",
            "provider": PROVIDER_ID,
            "rules": [],
        }
        raw = json.dumps(payload, ensure_ascii=False)
        exit_code = 1
    sys.stdout.write(raw)
    if not raw.endswith("\n"):
        sys.stdout.write("\n")
    return exit_code


def _load_workflow_config(root: Path) -> dict[str, Any]:
    for rel in (".cursor/workflow.config.json", "workflow.config.json"):
        path = root / rel
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(data, dict):
            return data
    return {}


def _obsidian_config(cfg: dict[str, Any]) -> dict[str, Any]:
    memory = cfg.get("memory") if isinstance(cfg.get("memory"), dict) else {}
    block = memory.get("obsidian") if isinstance(memory.get("obsidian"), dict) else {}
    return block


def _parse_frontmatter_category(text: str) -> str | None:
    if not text.startswith("---"):
        return None
    end = text.find("\n---", 3)
    if end == -1:
        return None
    for line in text[3:end].splitlines():
        if line.startswith("category:"):
            return line.split(":", 1)[1].strip().strip("\"'")
    return None


def _body_after_frontmatter(text: str) -> str:
    if not text.startswith("---"):
        return text
    parts = text.split("---", 2)
    return parts[2].lstrip("\n") if len(parts) >= 3 else ""


def _is_loopback_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    host = (parsed.hostname or "").lower()
    return host in LOOPBACK_HOSTS


def _confine_under(root: Path, candidate: Path) -> Path | None:
    try:
        resolved = candidate.resolve()
        resolved.relative_to(root.resolve())
        return resolved
    except (OSError, ValueError):
        return None


def _read_rules_from_disk(vault: Path, rules_dir_name: str) -> list[dict[str, str]]:
    rules_dir = _confine_under(vault, vault / rules_dir_name)
    if rules_dir is None or not rules_dir.is_dir():
        return []
    rules: list[dict[str, str]] = []
    for path in sorted(rules_dir.rglob("*.md")):
        confined = _confine_under(vault, path)
        if confined is None or not confined.is_file():
            continue
        try:
            text = confined.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        category = _parse_frontmatter_category(text)
        # Prefer explicit rule category; allow uncategorized markdown in rules dir.
        if category is not None and category != "rule":
            continue
        body = _body_after_frontmatter(text)
        if len(body) > MAX_RULE_CHARS:
            continue
        summary = _CONTROL_CHAR_RE.sub("", body).strip()
        if not summary:
            continue
        rel = confined.relative_to(vault).as_posix()
        rules.append({"id": rel, "summary": summary})
        if len(rules) >= MAX_RULES:
            break
    return rules


def main() -> int:
    root = Path(os.environ.get("SW_WORKSPACE_ROOT") or Path.cwd()).resolve()
    cfg = _load_workflow_config(root)
    memory = cfg.get("memory") if isinstance(cfg.get("memory"), dict) else {}
    provider = str(memory.get("provider") or "").strip()
    obs = _obsidian_config(cfg)
    fail_closed = bool(obs.get("failClosed", DEFAULT_FAIL_CLOSED))

    if provider and provider != PROVIDER_ID:
        return _emit(
            {
                "ok": False,
                "error": f"unsupported provider for obsidian rules adapter: {provider}",
                "provider": provider,
                "rules": [],
            },
            exit_code=1 if fail_closed else 0,
        )

    vault_raw = str(obs.get("vaultPath") or os.environ.get("OBSIDIAN_VAULT_PATH") or "").strip()
    if not vault_raw:
        return _emit(
            {
                "ok": False,
                "error": "memory.obsidian.vaultPath is required for rule-fetch",
                "provider": PROVIDER_ID,
                "rules": [],
            },
            exit_code=1 if fail_closed else 0,
        )

    vault = Path(vault_raw).expanduser()
    try:
        vault = vault.resolve()
    except OSError:
        return _emit(
            {
                "ok": False,
                "error": "vaultPath is not resolvable",
                "provider": PROVIDER_ID,
                "rules": [],
            },
            exit_code=1 if fail_closed else 0,
        )
    if not vault.is_dir():
        return _emit(
            {
                "ok": False,
                "error": "vaultPath is not a directory",
                "provider": PROVIDER_ID,
                "rules": [],
            },
            exit_code=1 if fail_closed else 0,
        )

    rules_dir = str(obs.get("rulesDirectory") or DEFAULT_RULES_DIR).strip() or DEFAULT_RULES_DIR
    if ".." in Path(rules_dir).parts or Path(rules_dir).is_absolute():
        return _emit(
            {
                "ok": False,
                "error": "rulesDirectory must be a vault-relative folder",
                "provider": PROVIDER_ID,
                "rules": [],
            },
            exit_code=1 if fail_closed else 0,
        )

    # Optional REST base — policy check only in this phase (disk is primary).
    mcp_base = str(obs.get("mcpBaseUrl") or DEFAULT_MCP_BASE).strip() or DEFAULT_MCP_BASE
    if not _is_loopback_url(mcp_base):
        return _emit(
            {
                "ok": False,
                "error": "mcpBaseUrl must be loopback-only (localhost / 127.0.0.1 / ::1)",
                "provider": PROVIDER_ID,
                "rules": [],
            },
            exit_code=1 if fail_closed else 0,
        )

    token_env = str(obs.get("tokenEnv") or DEFAULT_TOKEN_ENV).strip() or DEFAULT_TOKEN_ENV
    # Credential presence is not required for disk-only fetch; document env name for REST.
    _ = token_env

    try:
        rules = _read_rules_from_disk(vault, rules_dir)
    except OSError as exc:
        return _emit(
            {
                "ok": False,
                "error": f"rule-fetch failed: {exc}",
                "provider": PROVIDER_ID,
                "rules": [],
            },
            exit_code=1 if fail_closed else 0,
        )

    return _emit({"ok": True, "provider": PROVIDER_ID, "rules": rules}, exit_code=0)


if __name__ == "__main__":
    raise SystemExit(main())
