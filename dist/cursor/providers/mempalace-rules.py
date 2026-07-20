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

R23 TTL cache lives under ``.cursor/hooks/state/mempalace-rules-cache.json``, bound to
``provider`` + canonical ``palacePath`` with a checksum over the rule payload.
Tampered, foreign, or unbound entries are cache misses and re-fetched. When
``memory.mempalace.failClosed`` is true (default), palace / rule-fetch failures
block hook injection. Break-glass: set ``failClosed: false`` or switch
``memory.provider`` temporarily when the local palace is stopped.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

MAX_RULE_CHARS = 2000
MAX_RULES = 25
MAX_OUTPUT_BYTES = 64_000
DEFAULT_RULES_ROOM = "rules"
DEFAULT_SEARCH_EXCLUDE_ROOMS = ("transcripts",)
DEFAULT_CACHE_TTL_SEC = 300
DEFAULT_FAIL_CLOSED = True
FETCH_TIMEOUT_SEC = 8
CACHE_VERSION = 1
CACHE_REL = Path(".cursor") / "hooks" / "state" / "mempalace-rules-cache.json"
PROVIDER_ID = "mempalace"

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


def resolve_rules_room(mem_cfg: dict[str, Any]) -> str:
    return str(mem_cfg.get("rulesRoom") or DEFAULT_RULES_ROOM).strip() or DEFAULT_RULES_ROOM


def resolve_search_exclude_rooms(mem_cfg: dict[str, Any]) -> frozenset[str]:
    """Rooms excluded from ordinary search / memory-preflight (always includes rulesRoom)."""
    rules_room = resolve_rules_room(mem_cfg)
    raw = mem_cfg.get("searchExcludeRooms", list(DEFAULT_SEARCH_EXCLUDE_ROOMS))
    if not isinstance(raw, list):
        raw = list(DEFAULT_SEARCH_EXCLUDE_ROOMS)
    excluded = {str(room).strip() for room in raw if str(room).strip()}
    excluded.update(DEFAULT_SEARCH_EXCLUDE_ROOMS)
    excluded.add(rules_room)
    return frozenset(excluded)


def drawer_room(row: dict[str, Any]) -> str:
    return str(row.get("room") or row.get("metadata", {}).get("room") or "").strip()


def filter_drawers_for_ordinary_search(
    drawers: list[dict[str, Any]],
    *,
    exclude_rooms: frozenset[str],
) -> list[dict[str, Any]]:
    """Drop drawers in excluded rooms — ordinary search/preflight must never surface rulesRoom."""
    if not exclude_rooms:
        return list(drawers)
    return [row for row in drawers if drawer_room(row) not in exclude_rooms]


def opt_in_excluded_room_warnings(
    *,
    exclude_rooms: frozenset[str],
    requested_rooms: frozenset[str] | None = None,
    explicit_room: str | None = None,
) -> list[str]:
    """Operator warnings when excluded rooms (especially transcripts) are explicitly requested."""
    warnings: list[str] = []
    targets: set[str] = set()
    if requested_rooms:
        targets.update(requested_rooms)
    if explicit_room and explicit_room.strip():
        targets.add(explicit_room.strip())
    for room in sorted(targets):
        if room not in exclude_rooms:
            continue
        if room == "transcripts":
            warnings.append(
                "opt-in transcripts retrieval: excluded/verbatim material was explicitly requested"
            )
        else:
            warnings.append(
                f"opt-in excluded room {room!r}: retrieval targets a room excluded from default search"
            )
    return warnings


def guard_ordinary_search_room(
    room: str | None,
    *,
    rules_room: str,
    exclude_rooms: frozenset[str],
) -> None:
    """Fail closed when ordinary search/preflight would target rulesRoom or other excluded rooms."""
    if not room or not room.strip():
        return
    normalized = room.strip()
    if normalized == rules_room:
        raise ValueError(
            f"ordinary search/preflight must not target rulesRoom ({rules_room!r}); "
            "use rules-load hook transport only"
        )
    if normalized in exclude_rooms:
        raise ValueError(
            f"ordinary search/preflight must not target excluded room {normalized!r} "
            "without explicit opt-in handling"
        )


def resolve_list_recent_exclude_rooms(mem_cfg: dict[str, Any]) -> frozenset[str]:
    """Rooms skipped by list-recent — same exclusion union as ordinary search (R17)."""
    return resolve_search_exclude_rooms(mem_cfg)


def filter_drawers_for_list_recent(
    drawers: list[dict[str, Any]],
    *,
    exclude_rooms: frozenset[str],
) -> list[dict[str, Any]]:
    """Drop drawers in excluded rooms — list-recent must never surface rulesRoom or transcripts."""
    return filter_drawers_for_ordinary_search(drawers, exclude_rooms=exclude_rooms)


def guard_rules_room_write(
    room: str | None,
    *,
    rules_room: str,
    promotion_path: bool = False,
) -> None:
    """Fail closed when ordinary store/modify would target rulesRoom (R15)."""
    if promotion_path:
        return
    if not room or not room.strip():
        return
    normalized = room.strip()
    if normalized == rules_room:
        raise ValueError(
            f"ordinary store/modify must not target rulesRoom ({rules_room!r}); "
            "rule-class drawers only via /sw-memory-audit / human-gated promotion"
        )


def guard_hard_purge(*, confirmed: bool) -> None:
    """Fail closed when destructive purge lacks explicit operator confirmation (R16)."""
    if not confirmed:
        raise ValueError(
            "hard purge requires explicit confirmed destructive verb; "
            "use inactivate (supersede + KG-invalidate) for non-destructive removal"
        )


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


def fail_closed_default(mem_cfg: dict[str, Any]) -> bool:
    """Break-glass: operators may set memory.mempalace.failClosed to false (R23)."""
    value = mem_cfg.get("failClosed", DEFAULT_FAIL_CLOSED)
    return bool(value) if value is not None else DEFAULT_FAIL_CLOSED


def cache_ttl_seconds(mem_cfg: dict[str, Any]) -> int:
    raw = mem_cfg.get("ruleCacheTtlSec", DEFAULT_CACHE_TTL_SEC)
    try:
        ttl = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_CACHE_TTL_SEC
    return max(0, ttl)


def cache_path(workspace: Path) -> Path:
    return workspace / CACHE_REL


def rules_payload_checksum(rules: list[dict[str, str]]) -> str:
    canonical = json.dumps(rules, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _binding_matches(entry: dict[str, Any], *, provider: str, palace_path: Path) -> bool:
    bound_provider = str(entry.get("provider") or "").strip()
    bound_palace = str(entry.get("palacePath") or "").strip()
    if bound_provider != provider:
        return False
    if not bound_palace:
        return False
    try:
        return Path(bound_palace).resolve() == palace_path.resolve()
    except OSError:
        return bound_palace == str(palace_path)


def validate_cache_entry(
    entry: dict[str, Any],
    *,
    provider: str,
    palace_path: Path,
    ttl_seconds: int,
) -> bool:
    if int(entry.get("version", 0)) != CACHE_VERSION:
        return False
    if not _binding_matches(entry, provider=provider, palace_path=palace_path):
        return False
    rules = entry.get("rules")
    if not isinstance(rules, list):
        return False
    checksum = str(entry.get("checksum") or "")
    if not checksum or checksum != rules_payload_checksum(rules):
        return False
    if ttl_seconds <= 0:
        return False
    try:
        written = float(entry.get("writtenAt", 0))
    except (TypeError, ValueError):
        return False
    if not written or time.time() - written > ttl_seconds:
        return False
    return True


def read_rules_cache(
    workspace: Path,
    *,
    provider: str,
    palace_path: Path,
    ttl_seconds: int,
) -> list[dict[str, str]] | None:
    path = cache_path(workspace)
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    if not validate_cache_entry(
        payload,
        provider=provider,
        palace_path=palace_path,
        ttl_seconds=ttl_seconds,
    ):
        return None
    rules = payload.get("rules")
    if not isinstance(rules, list):
        return None
    return [dict(rule) for rule in rules if isinstance(rule, dict)]


def write_rules_cache_atomic(
    workspace: Path,
    *,
    provider: str,
    palace_path: Path,
    rules: list[dict[str, str]],
) -> None:
    path = cache_path(workspace)
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = {
        "version": CACHE_VERSION,
        "provider": provider,
        "palacePath": str(palace_path.resolve()),
        "checksum": rules_payload_checksum(rules),
        "writtenAt": time.time(),
        "rules": rules,
    }
    text = json.dumps(doc, ensure_ascii=False, indent=2) + "\n"
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".mempalace-rules-cache-", suffix=".json.tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _fetch_failure_payload(
    error: str,
    *,
    fail_closed: bool,
) -> tuple[dict[str, Any], int]:
    if fail_closed:
        return (
            {
                "ok": False,
                "applicable": True,
                "provider": PROVIDER_ID,
                "rules": [],
                "error": error,
            },
            1,
        )
    return (
        {
            "ok": True,
            "applicable": True,
            "provider": PROVIDER_ID,
            "rules": [],
            "degraded": True,
            "warning": (
                f"{error} (break-glass: memory.mempalace.failClosed is false — "
                "submit guardrails proceed without injected rules)"
            ),
        },
        0,
    )


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
        room = drawer_room(row)
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
    rules_room = resolve_rules_room(mem_cfg)
    project = str(memory.get("project") or root.name).strip()
    fail_closed = fail_closed_default(mem_cfg)
    cache_ttl = cache_ttl_seconds(mem_cfg)

    try:
        palace_raw = str(mem_cfg.get("palacePath") or "").strip()
        palace_path = canonicalize_palace_path(palace_raw, root)
    except ValueError as exc:
        payload, exit_code = _fetch_failure_payload(str(exc), fail_closed=fail_closed)
        return _emit(payload, exit_code=exit_code)

    if not palace_path.is_dir():
        payload, exit_code = _fetch_failure_payload(
            f"palace path not found or not a directory: {palace_path}",
            fail_closed=fail_closed,
        )
        return _emit(payload, exit_code=exit_code)

    cached_rules = read_rules_cache(
        root,
        provider=PROVIDER_ID,
        palace_path=palace_path,
        ttl_seconds=cache_ttl,
    )
    if cached_rules is not None:
        return _emit(
            {
                "ok": True,
                "applicable": True,
                "provider": PROVIDER_ID,
                "rules": cached_rules,
                "cache": "hit",
            }
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
        payload, exit_code = _fetch_failure_payload(
            (
                "mempalace package not installed or incompatible; "
                "install with: uv tool install 'mempalace>=3.6.0,<4.0.0'"
            ),
            fail_closed=fail_closed,
        )
        return _emit(payload, exit_code=exit_code)

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
        payload, exit_code = _fetch_failure_payload(
            f"invalid ruleFetchCommand: {exc}",
            fail_closed=fail_closed,
        )
        return _emit(payload, exit_code=exit_code)

    drawers_payload = fetch_drawers_raw(
        argv,
        palace_path=palace_path,
        rules_room=rules_room,
        wing=project,
    )
    if drawers_payload.get("error"):
        payload, exit_code = _fetch_failure_payload(
            str(drawers_payload["error"]),
            fail_closed=fail_closed,
        )
        return _emit(payload, exit_code=exit_code)

    rules = drawers_to_rules(drawers_payload, rules_room=rules_room)
    if cache_ttl > 0:
        try:
            write_rules_cache_atomic(
                root,
                provider=PROVIDER_ID,
                palace_path=palace_path,
                rules=rules,
            )
        except OSError:
            pass
    return _emit(
        {
            "ok": True,
            "applicable": True,
            "provider": PROVIDER_ID,
            "rules": rules,
            "cache": "miss",
        }
    )


if __name__ == "__main__":
    raise SystemExit(main())
