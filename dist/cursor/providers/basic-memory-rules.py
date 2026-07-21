#!/usr/bin/env python3
"""Basic Memory out-of-band rule-fetcher for hooks (PRD 075 R22–R25).

Emits JSON rules to stdout for guardrail injection. Agent-session ops use Basic Memory
MCP; this script is the hook transport only (catalog ``hookTransport.ruleFetch:
out-of-band-script``).

Dual-mode:
  * ``local`` — read the configured rules folder from ``projectPath`` on disk only
    (never opens cloud hosts).
  * ``cloud`` — HTTPS GET against the allowlisted API base with bearer credentials from
    the environment / secret store (default ``BASIC_MEMORY_API_KEY``).

Fixed-argv contract: no free-form caller args; optional ``ruleFetchCommand`` override
must match the allowlisted executable + exact argv template (no shell / eval).

Mode-partitioned TTL cache (R26) is owned by the following phase; this script always
re-fetches under the transport contracts above.
"""
from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

PROVIDER_ID = "basic-memory"
MAX_RULE_CHARS = 2000
MAX_RULES = 25
MAX_OUTPUT_BYTES = 64_000
DEFAULT_RULES_DIR = "rules"
DEFAULT_FAIL_CLOSED = True
DEFAULT_MODE = "local"
DEFAULT_API_BASE = "https://cloud.basicmemory.com"
DEFAULT_TOKEN_ENV = "BASIC_MEMORY_API_KEY"
DEFAULT_CLOUD_HOSTS = frozenset({"cloud.basicmemory.com"})
FETCH_TIMEOUT_SEC = 8

_CONTROL_CHAR_RE = re.compile(r"[\000-\010\013\014\016-\037]")
_SHELL_METACHAR_RE = re.compile(r"[;|&$`<>(){}[\]*?!]")

_ALLOWED_EXECUTABLE_BASENAMES = frozenset(
    {
        "python",
        "python3",
        "python3.10",
        "python3.11",
        "python3.12",
        "python3.13",
        "python3.14",
        "bm",
        "basic-memory",
    }
)

# Fixed cloud fetch snippet — argv constant; base/token/project via env only.
_CLOUD_FETCH_SNIPPET = (
    "import json,os,urllib.request;"
    "base=os.environ['BASIC_MEMORY_API_BASE'].rstrip('/');"
    "token=os.environ['BASIC_MEMORY_API_KEY'];"
    "proj=os.environ.get('BASIC_MEMORY_PROJECT','').strip();"
    "rules_dir=os.environ.get('BASIC_MEMORY_RULES_DIR','rules').strip() or 'rules';"
    "path=f'{base}/api/v1/projects/{proj}/directories/{rules_dir}/notes' if proj else "
    "f'{base}/api/v1/directories/{rules_dir}/notes';"
    "req=urllib.request.Request(path,headers={'Authorization':f'Bearer {api_key}',"
    "'Accept':'application/json'});"
    "print(urllib.request.urlopen(req,timeout=8).read().decode())"
)


def _emit(payload: dict[str, Any], *, exit_code: int = 0) -> int:
    text = json.dumps(payload, ensure_ascii=False)
    if len(text.encode("utf-8")) > MAX_OUTPUT_BYTES:
        payload = {
            "ok": False,
            "applicable": payload.get("applicable", True),
            "provider": PROVIDER_ID,
            "rules": [],
            "error": "rules payload exceeds size cap",
        }
        text = json.dumps(payload, ensure_ascii=False)
    print(text)
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


def strip_control_chars(text: str) -> str:
    return _CONTROL_CHAR_RE.sub("", text)


def fail_closed_default(bm_cfg: dict[str, Any]) -> bool:
    value = bm_cfg.get("failClosed", DEFAULT_FAIL_CLOSED)
    return bool(value) if value is not None else DEFAULT_FAIL_CLOSED


def resolve_mode(bm_cfg: dict[str, Any]) -> str:
    mode = str(bm_cfg.get("mode") or DEFAULT_MODE).strip().lower()
    if mode not in {"local", "cloud"}:
        raise ValueError(f"memory.basicMemory.mode must be local|cloud, got {mode!r}")
    return mode


def resolve_rules_directory(bm_cfg: dict[str, Any]) -> str:
    raw = str(bm_cfg.get("rulesDirectory") or DEFAULT_RULES_DIR).strip() or DEFAULT_RULES_DIR
    if ".." in Path(raw).parts or raw.startswith(("/", "\\")):
        raise ValueError("memory.basicMemory.rulesDirectory must be a relative directory name")
    return raw


def parse_frontmatter_field(text: str, field: str) -> str | None:
    if not text.startswith("---"):
        return None
    end = text.find("\n---", 3)
    if end == -1:
        return None
    block = text[3:end]
    prefix = f"{field}:"
    for line in block.splitlines():
        if line.startswith(prefix):
            return line.split(":", 1)[1].strip().strip("\"'")
    return None


def body_after_frontmatter(text: str) -> str:
    if not text.startswith("---"):
        return text
    parts = text.split("---", 2)
    return parts[2].lstrip("\n") if len(parts) >= 3 else ""


def note_is_rule(text: str, *, path: Path | None = None) -> bool:
    note_type = parse_frontmatter_field(text, "note_type") or parse_frontmatter_field(text, "type")
    category = parse_frontmatter_field(text, "category")
    if note_type == "rule" or category == "rule":
        return True
    # Rules-directory notes without frontmatter still qualify when path is under rules/.
    return path is not None and path.suffix.lower() in {".md", ".markdown"}


def normalize_rule(rule_id: str, body: str) -> dict[str, str] | None:
    summary = strip_control_chars(body)
    if not summary.strip():
        return None
    if len(summary) > MAX_RULE_CHARS:
        summary = summary[:MAX_RULE_CHARS]
    return {"id": rule_id, "summary": summary}


def rules_from_markdown_files(rules_dir: Path) -> list[dict[str, str]]:
    rules: list[dict[str, str]] = []
    if not rules_dir.is_dir():
        return rules
    for path in sorted(rules_dir.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in {".md", ".markdown"}:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if not note_is_rule(text, path=path):
            continue
        body = body_after_frontmatter(text)
        item = normalize_rule(path.stem, body)
        if item is None:
            continue
        rules.append(item)
        if len(rules) >= MAX_RULES:
            break
    return rules


def rules_from_cloud_payload(payload: Any) -> list[dict[str, str]]:
    rows: list[Any]
    if isinstance(payload, dict):
        for key in ("notes", "items", "results", "data"):
            candidate = payload.get(key)
            if isinstance(candidate, list):
                rows = candidate
                break
        else:
            rows = [payload]
    elif isinstance(payload, list):
        rows = payload
    else:
        return []

    rules: list[dict[str, str]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        note_type = str(row.get("note_type") or row.get("type") or "").strip()
        folder = str(row.get("directory") or row.get("folder") or row.get("path") or "").strip()
        if note_type and note_type != "rule" and "rules" not in folder.replace("\\", "/").split("/"):
            continue
        body = str(row.get("content") or row.get("body") or row.get("text") or "").strip()
        if not body and isinstance(row.get("summary"), str):
            body = row["summary"]
        rule_id = str(row.get("permalink") or row.get("id") or row.get("title") or f"rule-{len(rules)+1}")
        item = normalize_rule(rule_id, body)
        if item is None:
            continue
        rules.append(item)
        if len(rules) >= MAX_RULES:
            break
    return rules


def canonicalize_project_path(raw: str, workspace: Path) -> Path:
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError("memory.basicMemory.projectPath is required in local mode")
    candidate = raw.strip()
    parsed = urlparse(candidate)
    if parsed.scheme and parsed.scheme not in {"file"}:
        raise ValueError("local mode projectPath must be a filesystem path (no remote URL)")
    path = Path(os.path.expanduser(candidate))
    if not path.is_absolute():
        path = (workspace / path).resolve()
    else:
        path = path.resolve()
    return path


def assert_local_no_cloud(bm_cfg: dict[str, Any]) -> None:
    """Local mode must not be configured to open cloud hosts (R25)."""
    api_base = str(bm_cfg.get("apiBase") or "").strip()
    if not api_base:
        return
    host = (urlparse(api_base).hostname or "").lower()
    if host and host not in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError(
            "local mode must not open cloud hosts; clear memory.basicMemory.apiBase "
            "or switch mode to cloud explicitly"
        )


def resolve_api_base(bm_cfg: dict[str, Any]) -> str:
    raw = str(bm_cfg.get("apiBase") or DEFAULT_API_BASE).strip() or DEFAULT_API_BASE
    parsed = urlparse(raw)
    if parsed.scheme != "https":
        raise ValueError("cloud apiBase must use https")
    host = (parsed.hostname or "").lower()
    if host not in DEFAULT_CLOUD_HOSTS:
        raise ValueError(f"cloud apiBase host not allowlisted: {host!r}")
    return f"{parsed.scheme}://{parsed.netloc}"


def resolve_api_key(bm_cfg: dict[str, Any]) -> str:
    env_name = str(bm_cfg.get("tokenEnv") or DEFAULT_TOKEN_ENV).strip() or DEFAULT_TOKEN_ENV
    api_key = os.environ.get(env_name, "").strip()
    if not api_key:
        raise ValueError(f"cloud mode requires bearer token in ${env_name}")
    return api_key


def default_cloud_fetch_argv(python: str) -> list[str]:
    return [python, "-c", _CLOUD_FETCH_SNIPPET]


def _executable_allowed(executable: str) -> bool:
    if not executable or _SHELL_METACHAR_RE.search(executable):
        return False
    path = Path(executable)
    basename = path.name.lower()
    if basename in _ALLOWED_EXECUTABLE_BASENAMES:
        return True
    return path.is_file() and os.access(path, os.X_OK)


def parse_rule_fetch_command(raw: str) -> list[str]:
    text = raw.strip()
    if not text:
        raise ValueError("ruleFetchCommand must be non-empty")
    if _SHELL_METACHAR_RE.search(text):
        raise ValueError("ruleFetchCommand must not contain shell metacharacters")
    if text.startswith("["):
        parsed = json.loads(text)
        if not isinstance(parsed, list) or not parsed:
            raise ValueError("ruleFetchCommand JSON must be a non-empty argv array")
        return [str(part) for part in parsed]
    return shlex.split(text)


def validate_rule_fetch_command(argv: list[str], *, default_python: str) -> list[str]:
    if len(argv) < 2:
        raise ValueError("ruleFetchCommand argv too short")
    if not _executable_allowed(argv[0]):
        raise ValueError("ruleFetchCommand executable is not allowlisted")
    expected = default_cloud_fetch_argv(default_python)
    if argv != expected and argv != default_cloud_fetch_argv(argv[0]):
        raise ValueError(
            "ruleFetchCommand must match the fixed basic-memory cloud argv template "
            "(python -c <fixed urllib notes snippet>); prefix-only overrides are rejected"
        )
    return argv


def fetch_local_rules(bm_cfg: dict[str, Any], workspace: Path) -> list[dict[str, str]]:
    assert_local_no_cloud(bm_cfg)
    project = canonicalize_project_path(str(bm_cfg.get("projectPath") or ""), workspace)
    rules_dir_name = resolve_rules_directory(bm_cfg)
    rules_dir = (project / rules_dir_name).resolve()
    try:
        rules_dir.relative_to(project)
    except ValueError as exc:
        raise ValueError("rules directory escapes projectPath") from exc
    return rules_from_markdown_files(rules_dir)


def _cloud_notes_url(api_base: str, bm_cfg: dict[str, Any], rules_dir: str) -> str:
    project = str(bm_cfg.get("projectId") or bm_cfg.get("project") or "").strip()
    base = api_base.rstrip("/")
    if project:
        return f"{base}/api/v1/projects/{project}/directories/{rules_dir}/notes"
    return f"{base}/api/v1/directories/{rules_dir}/notes"


def fetch_cloud_rules_http(bm_cfg: dict[str, Any]) -> list[dict[str, str]]:
    api_base = resolve_api_base(bm_cfg)
    api_key = resolve_api_key(bm_cfg)
    rules_dir = resolve_rules_directory(bm_cfg)
    url = _cloud_notes_url(api_base, bm_cfg, rules_dir)
    host = (urlparse(url).hostname or "").lower()
    if host not in DEFAULT_CLOUD_HOSTS:
        raise ValueError(f"refusing non-allowlisted cloud host: {host!r}")
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
            raw = resp.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise ValueError(f"cloud rule-fetch failed: {exc}") from exc
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("cloud rule-fetch returned invalid JSON") from exc
    return rules_from_cloud_payload(payload)


def fetch_cloud_rules_subprocess(
    bm_cfg: dict[str, Any],
    *,
    argv: list[str],
) -> list[dict[str, str]]:
    api_base = resolve_api_base(bm_cfg)
    api_key = resolve_api_key(bm_cfg)
    rules_dir = resolve_rules_directory(bm_cfg)
    env = os.environ.copy()
    env["BASIC_MEMORY_API_BASE"] = api_base
    env["BASIC_MEMORY_API_KEY"] = api_key
    env["BASIC_MEMORY_RULES_DIR"] = rules_dir
    project = str(bm_cfg.get("projectId") or bm_cfg.get("project") or "").strip()
    if project:
        env["BASIC_MEMORY_PROJECT"] = project
    else:
        env.pop("BASIC_MEMORY_PROJECT", None)
    try:
        proc = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=FETCH_TIMEOUT_SEC,
            env=env,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ValueError(f"cloud rule-fetch subprocess failed: {exc}") from exc
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        raise ValueError(detail or "cloud rule-fetch exited non-zero")
    try:
        payload = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise ValueError("cloud rule-fetch returned invalid JSON") from exc
    return rules_from_cloud_payload(payload)


def fetch_cloud_rules(bm_cfg: dict[str, Any]) -> list[dict[str, str]]:
    override = str(bm_cfg.get("ruleFetchCommand") or "").strip()
    if override:
        argv = validate_rule_fetch_command(
            parse_rule_fetch_command(override),
            default_python=sys.executable,
        )
        return fetch_cloud_rules_subprocess(bm_cfg, argv=argv)
    # Default: in-process HTTPS against allowlisted host (no eval, no free-form args).
    return fetch_cloud_rules_http(bm_cfg)


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

    bm_cfg = memory.get("basicMemory")
    bm_cfg = bm_cfg if isinstance(bm_cfg, dict) else {}
    fail_closed = fail_closed_default(bm_cfg)

    try:
        mode = resolve_mode(bm_cfg)
        if mode == "local":
            rules = fetch_local_rules(bm_cfg, workspace)
        else:
            rules = fetch_cloud_rules(bm_cfg)
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
            "mode": mode,
            "rules": rules,
            "failClosed": fail_closed,
        }
    )


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
