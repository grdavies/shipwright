#!/usr/bin/env python3
"""Pre-work memory search record + degrade-open breadcrumb (PRD 019 R6/R7, TR2)."""
from __future__ import annotations

import json
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

SCRIPT_DIR = Path(__file__).resolve().parent
RECORD_PATH = Path(".cursor/hooks/state/memory-prework-search.json")
DEFAULT_CLASSES = ("rule", "decision", "learning", "code-context", "design")
DEFAULT_TTL_SECONDS = 3600


def emit(obj: dict[str, Any], exit_code: int = 0) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))
    sys.exit(exit_code)


def fail(error: str, exit_code: int = 2, **extra: Any) -> None:
    emit({"verdict": "fail", "error": error, **extra}, exit_code)


def parse_kv(args: list[str], flag: str, default: str | None = None) -> str | None:
    if flag in args:
        i = args.index(flag)
        return args[i + 1] if i + 1 < len(args) else default
    return default


def load_workflow_config(root: Path) -> dict[str, Any]:
    for rel in (".cursor/workflow.config.json", "workflow.config.json"):
        path = root / rel
        if path.is_file():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
    return {}


def provider_from_config(root: Path, config: dict[str, Any]) -> str:
    memory = config.get("memory") or {}
    provider = str(memory.get("provider") or "").strip().lower()
    if provider:
        return provider
    marker = root / ".cursor" / "sw-memory.provider"
    if marker.is_file():
        return "in-repo"
    return "recallium"


def probe_provider_reachable(root: Path, provider: str, config: dict[str, Any]) -> bool:
    if provider == "in-repo":
        store = root / ".cursor" / "sw-memory"
        return store.is_dir() or (root / ".cursor" / "sw-memory.provider").is_file()
    memory = config.get("memory") or {}
    connection = memory.get("connection") or {}
    base_url = str(connection.get("restBaseUrl") or "").strip().rstrip("/")
    if not base_url:
        return False
    try:
        req = Request(f"{base_url}/health", method="GET")
        with urlopen(req, timeout=3) as resp:  # noqa: S310 — local adapter probe
            return 200 <= resp.status < 500
    except (URLError, OSError, ValueError):
        try:
            req = Request(base_url, method="GET")
            with urlopen(req, timeout=3) as resp:  # noqa: S310
                return 200 <= resp.status < 500
        except (URLError, OSError, ValueError):
            return False


def redact_payload(raw: str) -> str:
    proc = subprocess.run(
        [str(SCRIPT_DIR / "memory-redact.py")],
        input=raw,
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        fail(proc.stderr.strip() or "memory-redact.py failed", exit_code=20)
    return proc.stdout


def append_run_log(root: Path, entry: dict[str, Any]) -> None:
    log_path = root / ".cursor" / "sw-deliver-runs" / "run.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")


def parse_classes(raw: str | None) -> list[str]:
    if not raw:
        return list(DEFAULT_CLASSES)
    return [c.strip() for c in raw.split(",") if c.strip()]


def parse_scope(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [s.strip() for s in raw.split(",") if s.strip()]


def cmd_record(root: Path, args: list[str]) -> None:
    surface = parse_kv(args, "--surface")
    if not surface:
        fail("--surface <sw-command> required (e.g. sw-execute)")

    scope = parse_scope(parse_kv(args, "--scope"))
    classes = parse_classes(parse_kv(args, "--classes"))
    hit_count_raw = parse_kv(args, "--hit-count")
    force_offline = "--offline" in args
    ttl_raw = parse_kv(args, "--ttl-seconds", str(DEFAULT_TTL_SECONDS)) or str(DEFAULT_TTL_SECONDS)

    try:
        ttl_seconds = int(ttl_raw)
    except ValueError:
        ttl_seconds = DEFAULT_TTL_SECONDS
    if ttl_seconds < 60:
        ttl_seconds = 60

    config = load_workflow_config(root)
    provider = provider_from_config(root, config)
    reachable = probe_provider_reachable(root, provider, config) and not force_offline

    now = int(time.time())
    nonce = uuid.uuid4().hex

    if not reachable:
        outcome = "memory:offline"
        summary = "provider unreachable (probe-gated)"
        hit_count = 0
    else:
        try:
            hit_count = int(hit_count_raw) if hit_count_raw is not None else 0
        except ValueError:
            hit_count = 0
        outcome = "memory:none" if hit_count <= 0 else "memory:hits"
        summary = (
            "no relevant memory found"
            if hit_count <= 0
            else f"{hit_count} scoped hit(s) surfaced"
        )

    record = {
        "surface": surface,
        "scope": scope,
        "classes": classes,
        "provider": provider,
        "outcome": outcome,
        "summary": summary,
        "hitCount": hit_count,
        "nonce": nonce,
        "probeReachable": reachable,
        "createdAt": now,
        "expiresAt": now + ttl_seconds,
        "consumedAt": None,
    }

    redacted = redact_payload(json.dumps(record, ensure_ascii=False))
    try:
        redacted_record = json.loads(redacted)
    except json.JSONDecodeError:
        fail("redacted record is not valid JSON", exit_code=20)

    out_path = root / RECORD_PATH
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(redacted_record, indent=2) + "\n", encoding="utf-8")

    breadcrumb = {
        "event": "memory-prework-search",
        "surface": surface,
        "outcome": outcome,
        "nonce": nonce,
        "at": now,
    }
    append_run_log(root, breadcrumb)

    emit(
        {
            "verdict": "pass",
            "action": "memory-prework-record",
            "recordPath": str(out_path),
            "surface": surface,
            "outcome": outcome,
            "nonce": nonce,
            "provider": provider,
            "probeReachable": reachable,
            "expiresAt": record["expiresAt"],
        }
    )


def cmd_status(root: Path, _args: list[str]) -> None:
    path = root / RECORD_PATH
    if not path.is_file():
        emit({"verdict": "pass", "action": "memory-prework-status", "present": False})
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        emit({"verdict": "pass", "action": "memory-prework-status", "present": False, "invalid": True})
    now = int(time.time())
    fresh = (
        isinstance(record, dict)
        and not record.get("consumedAt")
        and int(record.get("expiresAt") or 0) > now
    )
    emit(
        {
            "verdict": "pass",
            "action": "memory-prework-status",
            "present": True,
            "fresh": fresh,
            "record": record,
        }
    )


def main() -> None:
    if len(sys.argv) < 3:
        fail("usage: wave_memory_prework.py <root> <command> [args...]")
    root = Path(sys.argv[1])
    cmd = sys.argv[2]
    args = sys.argv[3:]
    if cmd == "record":
        cmd_record(root, args)
    elif cmd == "status":
        cmd_status(root, args)
    else:
        fail(f"unknown command: {cmd}")


if __name__ == "__main__":
    main()
