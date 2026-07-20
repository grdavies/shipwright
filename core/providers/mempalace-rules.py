#!/usr/bin/env python3
"""MemPalace out-of-band rule-fetcher for hooks (PRD 074 R19–R22).

Emits JSON rules to stdout for guardrail injection. Agent-session ops use MemPalace
MCP; this script is the hook transport only (catalog ``hookTransport.ruleFetch:
out-of-band-script``).

Default transport invokes the installed MemPalace Python module with a **fixed argv
template** (no free-form caller args): palace path and rules room are passed only via
validated config and ``MEMPALACE_*`` env vars set by this script.

Docker bind-mount recipe (same argv; palace read-only on the host path):

  docker run --rm -v /host/palace:/palace:ro \\
    -e SW_WORKSPACE_ROOT=/workspace \\
    -v /host/repo:/workspace:ro \\
    python:3.12 python /plugin/providers/mempalace-rules.py

Ensure ``memory.mempalace.palacePath`` points at the in-container mount (e.g.
``/palace``). ``ruleFetchCommand`` overrides require exact-executable allowlist +
fixed-argv template match (no shell / eval).
"""
from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

MAX_RULE_CHARS = 2000
MAX_RULES = 25
MAX_OUTPUT_BYTES = 64_000
DEFAULT_RULES_ROOM = "rules"
FETCH_TIMEOUT_SEC = 8

# Fixed MemPalace module invocation — argv is constant; palace/room/wing via env only.
_FETCH_SNIPPET = (
    "import json,os;"
    "from mempalace.mcp_server import TOOLS;"
    "room=os.environ['MEMPALACE_RULES_ROOM'];"
    "wing=os.environ.get('MEMPALACE_WING','').strip() or None;"
    "kwargs={'room':room,'limit':100};"
    "if wing: kwargs['wing']=wing;"
    "print(json.dumps(TOOLS['mempalace_list_drawers']['handler'](**kwargs)))"
)

_CONTROL_CHAR_RE = re.compile(r"[\000-\010\013\014\016-\037]")
_SHELL_METACHAR_RE = re.compile(r"[;|&$`<>(){}[\]*?!]")
_REMOTE_SCHEME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*://")

_ALLOWED_EXECUTABLE_BASENAMES = frozenset(
    {
        "python",
        "python3",
        "python3.10",
        "python3.11",
        "python3.12",
        "python3.13",
        "python3.14",
        "mempalace",
    }
)


def _emit(payload: dict[str, Any], *, exit_code: int = 0) -> int:
    text = json.dumps(payload, ensure_ascii=False)
    if len(text.encode("utf-8")) > MAX_OUTPUT_BYTES:
        payload = {
            "ok": False,
            "applicable": payload.get("applicable", True),
            "provider": payload.get("provider", "mempalace"),
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
        except json.JSONDecodeError:
            break
        memory = data.get("memory")
        return memory if isinstance(memory, dict) else {}
    return {}


def strip_control_chars(text: str) -> str:
    return _CONTROL_CHAR_RE.sub("", text)


def is_remote_palace_path(value: str) -> bool:
    stripped = value.strip()
    if not stripped:
        return False
    if _REMOTE_SCHEME_RE.match(stripped):
        return True
    parsed = urlparse(stripped)
    return bool(parsed.scheme and parsed.scheme not in {"file"})


def canonicalize_palace_path(raw: str, workspace: Path) -> Path:
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError("memory.mempalace.palacePath is required")
    candidate = raw.strip()
    if is_remote_palace_path(candidate):
        raise ValueError("memory.mempalace.palacePath must be a local filesystem path")
    path = Path(os.path.expanduser(candidate))
    if not path.is_absolute():
        path = (workspace / path).resolve()
    else:
        path = path.resolve()
    return path


def resolve_mempalace_python() -> str:
    override = os.environ.get("MEMPALACE_PYTHON", "").strip()
    if override:
        resolved = Path(override).expanduser()
        if resolved.is_file() and os.access(resolved, os.X_OK):
            return str(resolved)
    for candidate in (sys.executable, "python3", "python"):
        if not candidate:
            continue
        try:
            proc = subprocess.run(
                [candidate, "-c", "import mempalace"],
                capture_output=True,
                text=True,
                timeout=3,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        if proc.returncode == 0:
            return candidate
    return sys.executable


def default_fetch_argv(python: str) -> list[str]:
    return [python, "-c", _FETCH_SNIPPET]


def _executable_allowed(executable: str) -> bool:
    if not executable or _SHELL_METACHAR_RE.search(executable):
        return False
    path = Path(executable)
    basename = path.name.lower()
    if basename in _ALLOWED_EXECUTABLE_BASENAMES:
        return True
    if path.is_file() and os.access(path, os.X_OK):
        try:
            proc = subprocess.run(
                [str(path), "-c", "import mempalace"],
                capture_output=True,
                text=True,
                timeout=3,
                check=False,
            )
            return proc.returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            return False
    return False


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
    # Must match the fixed template exactly — not prefix-only.
    expected = default_fetch_argv(default_python)
    if argv != expected and argv != default_fetch_argv(argv[0]):
        raise ValueError(
            "ruleFetchCommand must match the fixed MemPalace argv template "
            "(python -c <fixed list_drawers snippet>); prefix-only overrides are rejected"
        )
    return argv


def fetch_drawers_raw(
    argv: list[str],
    *,
    palace_path: Path,
    rules_room: str,
    wing: str,
) -> dict[str, Any]:
    env = os.environ.copy()
    env["MEMPALACE_PALACE_PATH"] = str(palace_path)
    env["MEMPALACE_RULES_ROOM"] = rules_room
    if wing:
        env["MEMPALACE_WING"] = wing
    else:
        env.pop("MEMPALACE_WING", None)
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
        return {"error": f"mempalace rule-fetch subprocess failed: {exc}"}
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        return {"error": detail or "mempalace rule-fetch exited non-zero"}
    try:
        payload = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError:
        return {"error": "mempalace rule-fetch returned invalid JSON"}
    if not isinstance(payload, dict):
        return {"error": "mempalace rule-fetch returned non-object JSON"}
    return payload


def drawers_to_rules(drawers_payload: dict[str, Any], *, rules_room: str) -> list[dict[str, str]]:
    if drawers_payload.get("error"):
        return []
    rows = drawers_payload.get("drawers")
    if not isinstance(rows, list):
        return []
    rules: list[dict[str, str]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        room = str(row.get("room") or row.get("metadata", {}).get("room") or "").strip()
        if room and room != rules_room:
            continue
        drawer_id = str(row.get("drawer_id") or row.get("id") or "").strip()
        content = str(row.get("content") or row.get("summary") or "").strip()
        content = strip_control_chars(content)
        if not drawer_id or not content.strip():
            continue
        if len(content) > MAX_RULE_CHARS:
            continue
        rules.append({"id": drawer_id, "content": content})
        if len(rules) >= MAX_RULES:
            break
    return rules


def main() -> int:
    root = Path(os.environ.get("SW_WORKSPACE_ROOT") or Path.cwd())
    memory = load_memory_config(root)
    provider = str(memory.get("provider") or "").strip()
    if provider != "mempalace":
        return _emit(
            {
                "ok": True,
                "applicable": False,
                "provider": provider or None,
                "rules": [],
            }
        )

    mem_cfg = memory.get("mempalace")
    if not isinstance(mem_cfg, dict):
        mem_cfg = {}
    rules_room = str(mem_cfg.get("rulesRoom") or DEFAULT_RULES_ROOM).strip() or DEFAULT_RULES_ROOM
    project = str(memory.get("project") or root.name).strip()

    try:
        palace_raw = str(mem_cfg.get("palacePath") or "").strip()
        palace_path = canonicalize_palace_path(palace_raw, root)
    except ValueError as exc:
        return _emit(
            {
                "ok": False,
                "applicable": True,
                "provider": "mempalace",
                "rules": [],
                "error": str(exc),
            },
            exit_code=1,
        )

    if not palace_path.is_dir():
        return _emit(
            {
                "ok": False,
                "applicable": True,
                "provider": "mempalace",
                "rules": [],
                "error": f"palace path not found or not a directory: {palace_path}",
            },
            exit_code=1,
        )

    python = resolve_mempalace_python()
    try:
        probe = subprocess.run(
            [python, "-c", "import mempalace"],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        probe = None
    if probe is None or probe.returncode != 0:
        return _emit(
            {
                "ok": False,
                "applicable": True,
                "provider": "mempalace",
                "rules": [],
                "error": (
                    "mempalace package not installed or incompatible; "
                    "install with: uv tool install 'mempalace>=3.6.0,<4.0.0'"
                ),
            },
            exit_code=1,
        )

    override = str(mem_cfg.get("ruleFetchCommand") or "").strip()
    try:
        if override:
            argv = validate_rule_fetch_command(
                parse_rule_fetch_command(override),
                default_python=python,
            )
        else:
            argv = default_fetch_argv(python)
    except (ValueError, json.JSONDecodeError) as exc:
        return _emit(
            {
                "ok": False,
                "applicable": True,
                "provider": "mempalace",
                "rules": [],
                "error": f"invalid ruleFetchCommand: {exc}",
            },
            exit_code=1,
        )

    drawers_payload = fetch_drawers_raw(
        argv,
        palace_path=palace_path,
        rules_room=rules_room,
        wing=project,
    )
    if drawers_payload.get("error"):
        return _emit(
            {
                "ok": False,
                "applicable": True,
                "provider": "mempalace",
                "rules": [],
                "error": str(drawers_payload["error"]),
            },
            exit_code=1,
        )

    rules = drawers_to_rules(drawers_payload, rules_room=rules_room)
    return _emit(
        {
            "ok": True,
            "applicable": True,
            "provider": "mempalace",
            "rules": rules,
        }
    )


if __name__ == "__main__":
    raise SystemExit(main())
