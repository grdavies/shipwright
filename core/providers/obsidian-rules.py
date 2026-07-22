#!/usr/bin/env python3
"""Obsidian out-of-band rule-fetcher for hooks (PRD 076 R22–R26).

Emits JSON rules to stdout for guardrail injection. Agent-session ops use Obsidian
Local REST API MCP on loopback; this script is the hook transport only (catalog
``hookTransport.ruleFetch: out-of-band-script``).

Primary path: read markdown notes from ``memory.obsidian.vaultPath`` /
``rulesDirectory`` on disk (realpath-confined). Loopback REST fallback uses the same
host + credential policy as agent ops (``OBSIDIAN_API_KEY`` / tokenEnv) when disk
read is unavailable or yields no rules.

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
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

PROVIDER_ID = "obsidian"
MAX_RULE_CHARS = 2000
MAX_RULES = 25
MAX_OUTPUT_BYTES = 64_000
DEFAULT_RULES_DIR = "rules"
DEFAULT_FAIL_CLOSED = True
DEFAULT_MCP_BASE = "http://127.0.0.1:27123"
DEFAULT_TOKEN_ENV = "OBSIDIAN_API_KEY"
FETCH_TIMEOUT_SEC = 8
LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})

_CONTROL_CHAR_RE = re.compile(r"[\000-\010\013\014\016-\037]")


def _emit(payload: dict[str, Any], *, exit_code: int = 0) -> int:
    raw = json.dumps(payload, ensure_ascii=False)
    encoded = raw.encode("utf-8")
    if len(encoded) > MAX_OUTPUT_BYTES:
        payload = {
            "ok": False,
            "applicable": payload.get("applicable", True),
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


def _workflow_config_paths(root: Path) -> list[Path]:
    return [root / ".cursor" / "workflow.config.json", root / "workflow.config.json"]


def load_memory_config(root: Path) -> dict[str, Any]:
    for path in _workflow_config_paths(root):
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            break
        memory = data.get("memory")
        return memory if isinstance(memory, dict) else {}
    return {}


def obsidian_config(memory: dict[str, Any]) -> dict[str, Any]:
    block = memory.get("obsidian")
    return block if isinstance(block, dict) else {}


def fail_closed_default(obs_cfg: dict[str, Any]) -> bool:
    value = obs_cfg.get("failClosed", DEFAULT_FAIL_CLOSED)
    return bool(value) if value is not None else DEFAULT_FAIL_CLOSED


def parse_frontmatter_category(text: str) -> str | None:
    if not text.startswith("---"):
        return None
    end = text.find("\n---", 3)
    if end == -1:
        return None
    for line in text[3:end].splitlines():
        if line.startswith("category:"):
            return line.split(":", 1)[1].strip().strip("\"'")
    return None


def body_after_frontmatter(text: str) -> str:
    if not text.startswith("---"):
        return text
    parts = text.split("---", 2)
    return parts[2].lstrip("\n") if len(parts) >= 3 else ""


def strip_control_chars(text: str) -> str:
    return _CONTROL_CHAR_RE.sub("", text)


def is_loopback_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    host = (parsed.hostname or "").lower()
    return host in LOOPBACK_HOSTS


def confine_under(root: Path, candidate: Path) -> Path | None:
    try:
        resolved = candidate.resolve()
        resolved.relative_to(root.resolve())
        return resolved
    except (OSError, ValueError):
        return None


def validate_rules_directory(rules_dir: str) -> None:
    if ".." in Path(rules_dir).parts or Path(rules_dir).is_absolute():
        raise ValueError("rulesDirectory must be a vault-relative folder")


def resolve_vault_path(obs_cfg: dict[str, Any]) -> Path:
    vault_raw = str(obs_cfg.get("vaultPath") or os.environ.get("OBSIDIAN_VAULT_PATH") or "").strip()
    if not vault_raw:
        raise ValueError("memory.obsidian.vaultPath is required for rule-fetch")
    vault = Path(vault_raw).expanduser()
    try:
        vault = vault.resolve()
    except OSError as exc:
        raise ValueError("vaultPath is not resolvable") from exc
    if not vault.is_dir():
        raise ValueError("vaultPath is not a directory")
    return vault


def resolve_rules_directory(obs_cfg: dict[str, Any]) -> str:
    rules_dir = str(obs_cfg.get("rulesDirectory") or DEFAULT_RULES_DIR).strip() or DEFAULT_RULES_DIR
    validate_rules_directory(rules_dir)
    return rules_dir


def resolve_mcp_base(obs_cfg: dict[str, Any]) -> str:
    mcp_base = str(obs_cfg.get("mcpBaseUrl") or DEFAULT_MCP_BASE).strip() or DEFAULT_MCP_BASE
    if not is_loopback_url(mcp_base):
        raise ValueError("mcpBaseUrl must be loopback-only (localhost / 127.0.0.1 / ::1)")
    return mcp_base.rstrip("/")


def resolve_api_key(obs_cfg: dict[str, Any]) -> str:
    token_env = str(obs_cfg.get("tokenEnv") or DEFAULT_TOKEN_ENV).strip() or DEFAULT_TOKEN_ENV
    api_key = os.environ.get(token_env, "").strip()
    if not api_key:
        raise ValueError(f"REST fallback requires bearer token in ${token_env}")
    return api_key


def rules_from_markdown_text(text: str, *, rule_id: str) -> dict[str, str] | None:
    category = parse_frontmatter_category(text)
    if category is not None and category != "rule":
        return None
    body = body_after_frontmatter(text)
    if len(body) > MAX_RULE_CHARS:
        return None
    summary = strip_control_chars(body).strip()
    if not summary:
        return None
    return {"id": rule_id, "summary": summary}


def rules_from_markdown_files(rules_dir: Path, *, vault: Path) -> list[dict[str, str]]:
    confined_dir = confine_under(vault, rules_dir)
    if confined_dir is None or not confined_dir.is_dir():
        return []
    rules: list[dict[str, str]] = []
    for path in sorted(confined_dir.rglob("*.md")):
        confined = confine_under(vault, path)
        if confined is None or not confined.is_file():
            continue
        try:
            text = confined.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        rel = confined.relative_to(vault).as_posix()
        row = rules_from_markdown_text(text, rule_id=rel)
        if row is None:
            continue
        rules.append(row)
        if len(rules) >= MAX_RULES:
            break
    return rules


def fetch_rules_from_disk(vault: Path, rules_dir_name: str) -> list[dict[str, str]]:
    return rules_from_markdown_files(vault / rules_dir_name, vault=vault)


def _rest_request(url: str, *, api_key: str) -> bytes:
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT_SEC) as resp:
            return resp.read()
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise ValueError(f"REST rule-fetch failed: {exc}") from exc


def _vault_rest_url(mcp_base: str, vault_relative: str) -> str:
    normalized = vault_relative.strip("/")
    if not normalized:
        return f"{mcp_base}/vault/"
    segments = [quote(part, safe="") for part in normalized.split("/")]
    return f"{mcp_base}/vault/{'/'.join(segments)}/"


def _list_vault_entries(mcp_base: str, api_key: str, vault_relative: str) -> list[str]:
    url = _vault_rest_url(mcp_base, vault_relative)
    raw = _rest_request(url, api_key=api_key)
    try:
        payload = json.loads(raw.decode("utf-8", errors="replace"))
    except json.JSONDecodeError as exc:
        raise ValueError("REST vault list returned invalid JSON") from exc
    files = payload.get("files") if isinstance(payload, dict) else None
    if not isinstance(files, list):
        return []
    return [str(item) for item in files if str(item).strip()]


def _read_vault_note(mcp_base: str, api_key: str, vault_relative: str) -> str:
    normalized = vault_relative.strip("/")
    segments = [quote(part, safe="") for part in normalized.split("/")]
    url = f"{mcp_base}/vault/{'/'.join(segments)}"
    raw = _rest_request(url, api_key=api_key)
    return raw.decode("utf-8", errors="replace")


def _collect_rest_markdown_paths(
    mcp_base: str,
    api_key: str,
    rules_dir: str,
    *,
    prefix: str = "",
) -> list[str]:
    rel_dir = f"{rules_dir}/{prefix}".strip("/") if prefix else rules_dir.strip("/")
    entries = _list_vault_entries(mcp_base, api_key, rel_dir)
    paths: list[str] = []
    for entry in sorted(entries):
        child = f"{prefix}{entry}" if prefix else entry
        if child.endswith("/"):
            sub_prefix = child
            paths.extend(
                _collect_rest_markdown_paths(
                    mcp_base,
                    api_key,
                    rules_dir,
                    prefix=sub_prefix,
                )
            )
            continue
        if child.endswith(".md"):
            paths.append(f"{rules_dir}/{child}".replace("//", "/").strip("/"))
        if len(paths) >= MAX_RULES:
            break
    return paths[:MAX_RULES]


def fetch_rules_from_rest(mcp_base: str, api_key: str, rules_dir: str) -> list[dict[str, str]]:
    markdown_paths = _collect_rest_markdown_paths(mcp_base, api_key, rules_dir)
    rules: list[dict[str, str]] = []
    for rel_path in markdown_paths:
        try:
            text = _read_vault_note(mcp_base, api_key, rel_path)
        except ValueError:
            continue
        row = rules_from_markdown_text(text, rule_id=rel_path)
        if row is None:
            continue
        rules.append(row)
        if len(rules) >= MAX_RULES:
            break
    return rules


def fetch_rules(obs_cfg: dict[str, Any]) -> tuple[list[dict[str, str]], str]:
    vault = resolve_vault_path(obs_cfg)
    rules_dir = resolve_rules_directory(obs_cfg)
    disk_error: str | None = None
    try:
        disk_rules = fetch_rules_from_disk(vault, rules_dir)
    except OSError as exc:
        disk_rules = []
        disk_error = str(exc)
    else:
        disk_error = None
    if disk_rules:
        return disk_rules, "disk"

    mcp_base = resolve_mcp_base(obs_cfg)
    try:
        api_key = resolve_api_key(obs_cfg)
    except ValueError:
        if disk_error:
            raise ValueError(f"disk rule-fetch failed: {disk_error}") from None
        return [], "disk"

    rest_rules = fetch_rules_from_rest(mcp_base, api_key, rules_dir)
    if rest_rules:
        return rest_rules, "rest"
    if disk_error:
        raise ValueError(f"disk rule-fetch failed: {disk_error}")
    return [], "rest"


def main(argv: list[str] | None = None) -> int:
    _ = argv  # fixed-argv — ignore caller args
    workspace = Path(os.environ.get("SW_WORKSPACE_ROOT") or Path.cwd()).resolve()
    memory = load_memory_config(workspace)
    provider = str(memory.get("provider") or "").strip()
    if provider != PROVIDER_ID:
        return _emit(
            {
                "ok": True,
                "applicable": False,
                "provider": PROVIDER_ID,
                "rules": [],
                "reason": f"memory.provider is {provider!r}, not {PROVIDER_ID!r}",
            }
        )

    obs_cfg = obsidian_config(memory)
    fail_closed = fail_closed_default(obs_cfg)

    try:
        rules, transport = fetch_rules(obs_cfg)
    except ValueError as exc:
        return _emit(
            {
                "ok": False,
                "applicable": True,
                "provider": PROVIDER_ID,
                "rules": [],
                "failClosed": fail_closed,
                "error": str(exc),
            },
            exit_code=1 if fail_closed else 0,
        )

    return _emit(
        {
            "ok": True,
            "applicable": True,
            "provider": PROVIDER_ID,
            "rules": rules,
            "failClosed": fail_closed,
            "transport": transport,
        }
    )


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
