#!/usr/bin/env python3
"""PRD 080 phase 15 / R8 — durable disable record + backend-control resolver."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from host_lib import git_remote_url, load_workflow_config, parse_owner_repo, remote_name

DISABLE_DIR_NAME = "shipwright"
DISABLE_FILENAME = "planning-backend-disable.json"
RECORD_FILE_MODE = 0o600
RECORD_DIR_MODE = 0o700
RECORD_VERSION = 1

LEGACY_KILL_SWITCH_ENV = "SW_PLANNING_KILL_SWITCH"
LEGACY_KILL_SWITCH_SHIM_NOTICE = (
    f"{LEGACY_KILL_SWITCH_ENV} is deprecated; use "
    "`python3 scripts/planning_backend_control.py disable` instead "
    "(warn-only shim — does not affect backend resolution)"
)

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---", re.DOTALL)
_VISIBILITY_RE = re.compile(r"^visibility:\s*(\S+)\s*$", re.MULTILINE)


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_iso8601(raw: str) -> datetime | None:
    text = str(raw or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _record_expired(record: dict[str, Any]) -> bool:
    expires_at = record.get("expiresAt")
    if not isinstance(expires_at, str) or not expires_at.strip():
        return False
    parsed = _parse_iso8601(expires_at)
    if parsed is None:
        return False
    return parsed <= datetime.now(UTC)


def git_common_dir(root: Path) -> Path | None:
    proc = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "--git-common-dir"],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        return None
    raw = proc.stdout.strip()
    if not raw:
        return None
    common = Path(raw)
    if not common.is_absolute():
        common = (root / common).resolve()
    return common


def repo_scope_key(root: Path, cfg: dict[str, Any] | None = None) -> str:
    cfg = cfg if cfg is not None else load_workflow_config(root)
    remote = git_remote_url(root, remote_name(cfg)) or ""
    owner_repo = parse_owner_repo(remote)
    if owner_repo:
        return f"{owner_repo[0]}/{owner_repo[1]}"
    return hashlib.sha256(str(root.resolve()).encode("utf-8")).hexdigest()[:16]


def disable_store_dir(common: Path) -> Path:
    return common / DISABLE_DIR_NAME


def disable_store_path(common: Path) -> Path:
    return disable_store_dir(common) / DISABLE_FILENAME


def _assert_record_path_safety(path: Path) -> None:
    owner = os.getuid()
    targets: list[Path] = [path]
    if path.is_file():
        targets.append(path.parent)
    for target in targets:
        if not target.exists():
            continue
        if target.is_symlink():
            raise RuntimeError(f"disable-record path must not be symlinked: {target}")
        stat = target.stat()
        if stat.st_uid != owner:
            raise RuntimeError(f"disable-record path must be owned by current user: {target}")
        mode = stat.st_mode & 0o777
        if target.is_file() and mode != RECORD_FILE_MODE:
            raise RuntimeError(f"disable-record file must be mode {oct(RECORD_FILE_MODE)}")
        if target.is_dir() and mode != RECORD_DIR_MODE:
            raise RuntimeError(f"disable-record directory must be mode {oct(RECORD_DIR_MODE)}")


def _read_store_document(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"version": RECORD_VERSION, "repos": {}}
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise RuntimeError("disable-record document must be a JSON object")
    repos = raw.get("repos")
    if repos is None:
        repos = {}
    if not isinstance(repos, dict):
        raise RuntimeError("disable-record repos must be a JSON object")
    return {"version": int(raw.get("version", RECORD_VERSION)), "repos": repos}


def _write_store_document_locked(fd: int, path: Path, document: dict[str, Any]) -> None:
    payload = (json.dumps(document, indent=2, sort_keys=True) + "\n").encode("utf-8")
    os.ftruncate(fd, 0)
    os.lseek(fd, 0, os.SEEK_SET)
    os.write(fd, payload)
    os.fchmod(fd, RECORD_FILE_MODE)


def _with_store_lock(common: Path, callback) -> Any:
    store_dir = disable_store_dir(common)
    store_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(store_dir, RECORD_DIR_MODE)
    path = disable_store_path(common)
    _assert_record_path_safety(store_dir)
    if path.exists():
        _assert_record_path_safety(path)
    flags = os.O_RDWR | os.O_CREAT
    fd = os.open(path, flags, RECORD_FILE_MODE)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        if path.stat().st_size == 0:
            _write_store_document_locked(fd, path, {"version": RECORD_VERSION, "repos": {}})
        result = callback(fd, path)
        return result
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def _create_store_exclusive(common: Path) -> None:
    store_dir = disable_store_dir(common)
    store_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(store_dir, RECORD_DIR_MODE)
    _assert_record_path_safety(store_dir)
    path = disable_store_path(common)
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    try:
        fd = os.open(path, flags, RECORD_FILE_MODE)
    except FileExistsError:
        return
    try:
        payload = (json.dumps({"version": RECORD_VERSION, "repos": {}}, indent=2) + "\n").encode("utf-8")
        os.write(fd, payload)
    finally:
        os.close(fd)
    _assert_record_path_safety(path)


def read_disable_record(root: Path, cfg: dict[str, Any] | None = None) -> dict[str, Any] | None:
    common = git_common_dir(root)
    if common is None:
        return None
    path = disable_store_path(common)
    if not path.is_file():
        return None
    _assert_record_path_safety(path)
    document = _read_store_document(path)
    scope = repo_scope_key(root, cfg)
    record = document.get("repos", {}).get(scope)
    if not isinstance(record, dict):
        return None
    if _record_expired(record):
        return None
    return dict(record)


def list_disable_records(root: Path) -> dict[str, Any]:
    common = git_common_dir(root)
    if common is None:
        return {"verdict": "ok", "records": [], "offline": True}
    path = disable_store_path(common)
    if not path.is_file():
        return {"verdict": "ok", "records": [], "offline": True, "storePath": str(path)}
    _assert_record_path_safety(path)
    document = _read_store_document(path)
    scope = repo_scope_key(root)
    records: list[dict[str, Any]] = []
    for repo_key, raw in sorted(document.get("repos", {}).items()):
        if not isinstance(raw, dict):
            continue
        entry = dict(raw)
        entry["repoScope"] = repo_key
        entry["active"] = not _record_expired(entry)
        entry["currentRepo"] = repo_key == scope
        records.append(entry)
    return {
        "verdict": "ok",
        "records": records,
        "offline": True,
        "storePath": str(path),
        "currentRepoScope": scope,
    }


def has_pending_private_tier_content(root: Path, cfg: dict[str, Any] | None = None) -> bool:
    cfg = cfg if cfg is not None else load_workflow_config(root)
    search_roots = [root / "docs" / "prds", root / "docs" / "planning", root / ".cursor" / "planning-materialized"]
    for base in search_roots:
        if not base.is_dir():
            continue
        for path in base.rglob("*.md"):
            try:
                text = path.read_text(encoding="utf-8")
            except OSError:
                continue
            match = _FRONTMATTER_RE.match(text)
            if not match:
                continue
            vis_match = _VISIBILITY_RE.search(match.group(1))
            if vis_match and vis_match.group(1).strip().lower() == "private":
                return True
    tier = str((cfg.get("planning") or {}).get("visibilityTier") or "").strip()
    if tier == "all-private":
        return True
    return False


def refuse_disable_if_private_pending(root: Path, cfg: dict[str, Any] | None = None) -> dict[str, Any] | None:
    cfg = cfg if cfg is not None else load_workflow_config(root)
    if has_pending_private_tier_content(root, cfg):
        return {
            "verdict": "fail",
            "error": "private-tier-pending-refuses-forced-fallback",
            "remediation": (
                "resolve or relocate private-tier planning content before forcing "
                "effective-backend fallback to the public file store"
            ),
        }
    return None


def cmd_disable(
    root: Path,
    *,
    set_by: str,
    reason: str,
    expires_at: str | None = None,
) -> dict[str, Any]:
    cfg = load_workflow_config(root)
    refusal = refuse_disable_if_private_pending(root, cfg)
    if refusal is not None:
        return refusal
    common = git_common_dir(root)
    if common is None:
        return {"verdict": "fail", "error": "git-common-dir-unresolved"}
    _create_store_exclusive(common)

    scope = repo_scope_key(root, cfg)
    record = {
        "setBy": set_by,
        "reason": reason,
        "setAt": _utc_now(),
        "expiresAt": expires_at,
    }

    def _write(fd: int, path: Path) -> dict[str, Any]:
        document = _read_store_document(path)
        repos = document.setdefault("repos", {})
        if not isinstance(repos, dict):
            repos = {}
            document["repos"] = repos
        repos[scope] = record
        _write_store_document_locked(fd, path, document)
        return {
            "verdict": "ok",
            "action": "backend-disable",
            "repoScope": scope,
            "record": record,
            "storePath": str(path),
        }

    return _with_store_lock(common, _write)


def cmd_enable(root: Path) -> dict[str, Any]:
    common = git_common_dir(root)
    if common is None:
        return {"verdict": "fail", "error": "git-common-dir-unresolved"}
    scope = repo_scope_key(root)

    def _write(fd: int, path: Path) -> dict[str, Any]:
        if not path.is_file():
            return {"verdict": "ok", "action": "backend-enable", "removed": False, "repoScope": scope}
        document = _read_store_document(path)
        repos = document.get("repos")
        if not isinstance(repos, dict) or scope not in repos:
            return {"verdict": "ok", "action": "backend-enable", "removed": False, "repoScope": scope}
        repos.pop(scope, None)
        _write_store_document_locked(fd, path, document)
        return {"verdict": "ok", "action": "backend-enable", "removed": True, "repoScope": scope}

    return _with_store_lock(common, _write)


def _read_worktree_backend_control(root: Path) -> dict[str, Any] | None:
    state_path = root / ".cursor" / "sw-worktree-state.json"
    if not state_path.is_file():
        return None
    try:
        payload = json.loads(state_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    control = payload.get("backendControl")
    return control if isinstance(control, dict) else None


def _read_session_backend_control(root: Path) -> dict[str, Any] | None:
    cursor = root / ".cursor"
    if not cursor.is_dir():
        return None
    candidates = sorted(cursor.glob("sw-deliver-state*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    for state_path in candidates:
        try:
            payload = json.loads(state_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict):
            continue
        control = payload.get("backendControl")
        if isinstance(control, dict):
            return control
    return None


def legacy_kill_switch_env_shim() -> list[str]:
    """Read-only warn-only shim for the legacy kill-switch env (PRD 080 R8)."""
    raw = os.environ.get(LEGACY_KILL_SWITCH_ENV, "").strip().lower()
    if raw in {"1", "true", "yes"}:
        return [LEGACY_KILL_SWITCH_SHIM_NOTICE]
    return []


def _worktree_forces_fallback(control: dict[str, Any] | None) -> bool:
    if not control:
        return False
    if control.get("forcedFallback") is True:
        return True
    override = control.get("backendOverride")
    return isinstance(override, str) and override.strip() == "in-repo-public"


def resolve_control_layer(
    root: Path,
    cfg: dict[str, Any],
    *,
    override: str | None = None,
    cli_override: str | None = None,
    closeout_override: bool = False,
) -> dict[str, Any]:
    """Report which backend-control layer governs forced fallback (highest wins)."""
    if closeout_override or override:
        return {"layer": "explicit-backend-override", "forcedFallback": False}
    if cli_override:
        return {"layer": "cli-override", "forcedFallback": False}
    worktree = _read_worktree_backend_control(root)
    if _worktree_forces_fallback(worktree):
        return {"layer": "worktree-state", "forcedFallback": True, "control": worktree}
    session = _read_session_backend_control(root)
    if _worktree_forces_fallback(session):
        return {"layer": "session-state", "forcedFallback": True, "control": session}
    record = read_disable_record(root, cfg)
    if record is not None:
        return {"layer": "durable-record", "forcedFallback": True, "record": record}
    return {"layer": "repository-config", "forcedFallback": False}


def is_forced_file_store_fallback(
    root: Path,
    cfg: dict[str, Any],
    *,
    override: str | None = None,
    cli_override: str | None = None,
    closeout_override: bool = False,
) -> bool:
    layer = resolve_control_layer(
        root,
        cfg,
        override=override,
        cli_override=cli_override,
        closeout_override=closeout_override,
    )
    return bool(layer.get("forcedFallback"))


def control_state_snapshot(root: Path, cfg: dict[str, Any]) -> dict[str, Any]:
    record = read_disable_record(root, cfg)
    layer = resolve_control_layer(root, cfg)
    payload = {
        "layer": layer.get("layer"),
        "forcedFallback": layer.get("forcedFallback"),
        "record": record,
        "repoScope": repo_scope_key(root, cfg),
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    payload["fingerprint"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    if isinstance(record, dict):
        payload["disableReason"] = record.get("reason")
    return payload


def validate_control_pin(root: Path, cfg: dict[str, Any], pinned: dict[str, Any]) -> dict[str, Any]:
    current = control_state_snapshot(root, cfg)
    pinned_fp = str(pinned.get("fingerprint") or "")
    if pinned_fp and pinned_fp == current.get("fingerprint"):
        return {"verdict": "ok", "fingerprint": current.get("fingerprint")}
    return {
        "verdict": "fail",
        "halt": "backend-control-changed",
        "error": "planning backend control changed mid-run",
        "reason": current.get("disableReason") or pinned.get("disableReason"),
        "remediation": "finish or abort the deliver run before changing the backend disable record",
        "pinned": pinned,
        "current": current,
    }


def disable_record_doctor_finding(root: Path) -> dict[str, Any] | None:
    listed = list_disable_records(root)
    active = [row for row in listed.get("records") or [] if row.get("currentRepo") and row.get("active")]
    if not active:
        return None
    record = active[0]
    return {
        "check": "backend-disable-record",
        "status": "active",
        "setBy": record.get("setBy"),
        "reason": record.get("reason"),
        "setAt": record.get("setAt"),
        "expiresAt": record.get("expiresAt"),
        "storePath": listed.get("storePath"),
    }


def emit(payload: dict[str, Any], code: int = 0) -> None:
    print(json.dumps(payload, ensure_ascii=False))
    raise SystemExit(code)


def main() -> None:
    parser = argparse.ArgumentParser(description="Planning backend disable record (PRD 080 R8)")
    parser.add_argument("--root", default=".", help="Repository root")
    sub = parser.add_subparsers(dest="command", required=True)
    disable = sub.add_parser("disable", help="Record a durable backend disable for this repository")
    disable.add_argument("--set-by", required=True)
    disable.add_argument("--reason", required=True)
    disable.add_argument("--expires-at", default=None)
    sub.add_parser("enable", help="Remove the durable backend disable for this repository")
    sub.add_parser("list", help="List durable disable records (offline)")
    args = parser.parse_args()
    root = Path(args.root).resolve()
    if args.command == "disable":
        result = cmd_disable(
            root,
            set_by=args.set_by,
            reason=args.reason,
            expires_at=args.expires_at,
        )
        emit(result, 0 if result.get("verdict") == "ok" else 20)
    elif args.command == "enable":
        result = cmd_enable(root)
        emit(result, 0 if result.get("verdict") == "ok" else 20)
    elif args.command == "list":
        emit(list_disable_records(root))


if __name__ == "__main__":
    main()
