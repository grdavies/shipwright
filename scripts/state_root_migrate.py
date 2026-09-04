#!/usr/bin/env python3
"""Gated state-root migration: skew check, quiesce fence, journaled moves (PRD 342 R13/R14/R15/R54)."""

from __future__ import annotations

import atexit
import hashlib
import json
import os
import shutil
import sys
import time
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import shipwright_paths  # noqa: E402

INVENTORY_REL = Path("core/sw-reference/state-root-inventory.json")
FENCE_FILENAME = "state-root-migrate.fence"
JOURNAL_FILENAME = "state-root-migrate.journal.json"
JOURNAL_STATUS_IN_PROGRESS = "in-progress"
JOURNAL_STATUS_COMPLETED = "completed"
JOURNAL_STATUS_ABORTED = "aborted"
ENTRY_PENDING = "pending"
ENTRY_MOVED = "moved"
ENTRY_ROLLED_BACK = "rolled-back"
VERSION_CANDIDATES = ("version.txt", "VERSION")
IN_FLIGHT_RUN_STATUSES = frozenset(
    {
        "running",
        "in-flight",
        "in_flight",
        "shipping",
        "active",
        "pending",
        "queued",
        "dispatching",
        "awaiting",
    }
)

_HELD_FENCES: set[Path] = set()


class StateRootMigrateError(Exception):
    """Structured migration refusal."""

    def __init__(self, code: str, message: str, **extra: Any) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.extra = extra

    def as_dict(self) -> dict[str, Any]:
        return {"verdict": "fail", "error": self.code, "message": self.message, **self.extra}


def _read_version(root: Path) -> str:
    for name in VERSION_CANDIDATES:
        path = root / name
        if path.is_file():
            return path.read_text(encoding="utf-8").strip() or "unknown"
    return "unknown"


def inventory_path(root: Path) -> Path:
    return root / INVENTORY_REL


def load_inventory_entries(root: Path) -> list[dict[str, Any]]:
    path = inventory_path(root)
    if not path.is_file():
        raise StateRootMigrateError(
            "inventory-missing",
            f"state-root inventory missing at {INVENTORY_REL.as_posix()}",
            path=str(path),
        )
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise StateRootMigrateError(
            "inventory-unreadable",
            f"state-root inventory unreadable: {exc}",
            path=str(path),
        ) from exc
    entries = data.get("entries") if isinstance(data, dict) else None
    if not isinstance(entries, list):
        raise StateRootMigrateError(
            "inventory-malformed",
            "state-root inventory entries must be a list",
            path=str(path),
        )
    return [e for e in entries if isinstance(e, dict)]


def redirect_map_from_inventory(root: Path) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for entry in load_inventory_entries(root):
        legacy = str(entry.get("legacyPath") or "").strip().rstrip("/")
        new = str(entry.get("newPath") or "").strip().rstrip("/")
        if legacy and new:
            mapping[legacy] = new
    return mapping


def redirect_map_fingerprint(mapping: dict[str, str]) -> str:
    canonical = json.dumps(mapping, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def compare_plugin_redirect_map(
    repo_root: Path,
    plugin_root: Path | None = None,
) -> dict[str, Any]:
    """Refuse when installed plugin redirect map disagrees with repo content (R54)."""
    plugin = (plugin_root or repo_root).resolve()
    repo = repo_root.resolve()
    repo_map = redirect_map_from_inventory(repo)
    try:
        plugin_map = redirect_map_from_inventory(plugin)
    except StateRootMigrateError as exc:
        raise StateRootMigrateError(
            "plugin-inventory-unavailable",
            "installed plugin state-root inventory unavailable for skew comparison",
            repoVersion=_read_version(repo),
            pluginVersion=_read_version(plugin),
            pluginRoot=str(plugin),
            cause=exc.as_dict(),
        ) from exc

    repo_fp = redirect_map_fingerprint(repo_map)
    plugin_fp = redirect_map_fingerprint(plugin_map)
    matched = repo_fp == plugin_fp
    result = {
        "verdict": "pass" if matched else "fail",
        "matched": matched,
        "repoVersion": _read_version(repo),
        "pluginVersion": _read_version(plugin),
        "repoFingerprint": repo_fp,
        "pluginFingerprint": plugin_fp,
        "repoRoot": str(repo),
        "pluginRoot": str(plugin),
    }
    if not matched:
        raise StateRootMigrateError(
            "plugin-version-skew",
            "installed plugin redirect map disagrees with repository inventory",
            **result,
        )
    return result


def fence_path(root: Path) -> Path:
    return shipwright_paths.deliver_run_locks_dir(root) / FENCE_FILENAME


def fence_held(root: Path) -> bool:
    return fence_path(root).is_file()


def read_fence(root: Path) -> dict[str, Any] | None:
    path = fence_path(root)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"path": str(path), "unreadable": True}
    if isinstance(data, dict):
        return {**data, "path": str(path)}
    return {"path": str(path), "unreadable": True}


def _release_held_fences_atexit() -> None:
    for path in list(_HELD_FENCES):
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
        _HELD_FENCES.discard(path)


atexit.register(_release_held_fences_atexit)


def acquire_quiesce_fence(root: Path, *, holder: str | None = None) -> dict[str, Any]:
    path = fence_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "kind": "state-root-migrate-fence",
        "pid": os.getpid(),
        "holder": holder or f"state-root-migrate:{os.getpid()}",
        "acquiredAt": time.time(),
    }
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    try:
        fd = os.open(str(path), flags, 0o600)
    except FileExistsError as exc:
        existing = read_fence(root) or {}
        raise StateRootMigrateError(
            "quiesce-fence-held",
            "state-root migration quiesce fence already held",
            fence=existing,
            path=str(path),
        ) from exc
    try:
        os.write(fd, (json.dumps(payload, indent=2) + "\n").encode("utf-8"))
    finally:
        os.close(fd)
    _HELD_FENCES.add(path.resolve())
    return {"verdict": "pass", "fence": payload, "path": str(path)}


def release_quiesce_fence(root: Path, *, missing_ok: bool = True) -> dict[str, Any]:
    path = fence_path(root)
    try:
        path.unlink(missing_ok=missing_ok)
    except TypeError:
        # Python <3.8 compatibility for missing_ok
        if path.exists():
            path.unlink()
        elif not missing_ok:
            raise
    except OSError as exc:
        if not missing_ok:
            raise StateRootMigrateError(
                "fence-release-failed",
                f"failed to release quiesce fence: {exc}",
                path=str(path),
            ) from exc
        _HELD_FENCES.discard(path.resolve())
        return {"verdict": "pass", "released": False, "path": str(path)}
    _HELD_FENCES.discard(path.resolve())
    return {"verdict": "pass", "released": True, "path": str(path)}


def assert_no_quiesce_fence(root: Path) -> None:
    if fence_held(root):
        raise StateRootMigrateError(
            "quiesce-fence-blocks-acquire",
            "state-root migration quiesce fence blocks new lock acquisition",
            fence=read_fence(root),
            path=str(fence_path(root)),
        )


def _safe_listdir(path: Path) -> list[Path] | None:
    if not path.exists():
        return []
    if not path.is_dir():
        return None
    try:
        return list(path.iterdir())
    except OSError:
        return None


def _run_id_from_state(path: Path) -> str | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    for key in ("runId", "id", "deliverRunId"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return path.parent.name


def _status_from_state(path: Path) -> str | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    for key in ("status", "phaseStatus", "verdict"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip().lower()
    return None


def _rel_display(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path)


def scan_inflight_blockers(root: Path) -> list[dict[str, Any]]:
    """Scan deliver runs, wave/deliver locks, and worktree locks (R14). Fail-closed on uncertainty."""
    blockers: list[dict[str, Any]] = []

    runs_dir = shipwright_paths.deliver_runs_dir(root)
    children = _safe_listdir(runs_dir)
    if children is None:
        raise StateRootMigrateError(
            "inflight-status-indeterminate",
            "cannot determine deliver-run in-flight status",
            path=str(runs_dir),
        )
    for child in children:
        if not child.is_dir():
            continue
        state_file = None
        for name in ("state.json", "run-state.json", "status.json"):
            candidate = child / name
            if candidate.is_file():
                state_file = candidate
                break
        if state_file is None:
            try:
                nonempty = any(child.iterdir())
            except OSError as exc:
                raise StateRootMigrateError(
                    "inflight-status-indeterminate",
                    f"cannot inspect deliver run directory {child.name}: {exc}",
                    path=str(child),
                ) from exc
            if nonempty:
                raise StateRootMigrateError(
                    "inflight-status-indeterminate",
                    f"deliver run {child.name} has no readable state file",
                    path=str(child),
                    runId=child.name,
                )
            continue
        status = _status_from_state(state_file)
        if status is None:
            raise StateRootMigrateError(
                "inflight-status-indeterminate",
                f"deliver run state unreadable or missing status: {child.name}",
                path=str(state_file),
                runId=child.name,
            )
        if status in IN_FLIGHT_RUN_STATUSES:
            blockers.append(
                {
                    "kind": "deliver-run",
                    "runId": _run_id_from_state(state_file) or child.name,
                    "status": status,
                    "path": _rel_display(root, state_file),
                }
            )

    lock_dirs = (
        ("deliver-lock", shipwright_paths.deliver_locks_dir(root)),
        ("target-lock", shipwright_paths.target_locks_dir(root)),
        ("doc-run-lock", shipwright_paths.doc_run_locks_dir(root)),
        (
            "doc-to-feature-handoff-lock",
            shipwright_paths.doc_to_feature_handoff_locks_dir(root),
        ),
        ("deliver-run-lock", shipwright_paths.deliver_run_locks_dir(root)),
    )
    for kind, directory in lock_dirs:
        entries = _safe_listdir(directory)
        if entries is None:
            raise StateRootMigrateError(
                "inflight-status-indeterminate",
                f"cannot determine {kind} status",
                path=str(directory),
            )
        for entry in entries:
            if entry.name == FENCE_FILENAME:
                continue
            if entry.suffix == ".lock" or entry.name.endswith(".lock"):
                blockers.append(
                    {
                        "kind": kind,
                        "runId": entry.stem,
                        "path": _rel_display(root, entry),
                    }
                )

    living = shipwright_paths.living_docs_lock_path(root)
    if living.is_file():
        blockers.append(
            {
                "kind": "living-docs-lock",
                "runId": "living-docs",
                "path": _rel_display(root, living),
            }
        )

    wt_state = shipwright_paths.worktree_state_path(root)
    if wt_state.is_file():
        try:
            data = json.loads(wt_state.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise StateRootMigrateError(
                "inflight-status-indeterminate",
                f"worktree state unreadable: {exc}",
                path=str(wt_state),
            ) from exc
        if isinstance(data, dict):
            worktrees = data.get("worktrees") or data.get("active") or []
            if isinstance(worktrees, dict):
                worktrees = [
                    {"id": key, **(value if isinstance(value, dict) else {})}
                    for key, value in worktrees.items()
                ]
            if not isinstance(worktrees, list):
                raise StateRootMigrateError(
                    "inflight-status-indeterminate",
                    "worktree state has unexpected shape",
                    path=str(wt_state),
                )
            for item in worktrees:
                if not isinstance(item, dict):
                    continue
                status = str(item.get("status") or item.get("phaseStatus") or "").lower()
                locked = bool(item.get("locked") or item.get("lockHeld"))
                if locked or status in IN_FLIGHT_RUN_STATUSES:
                    blockers.append(
                        {
                            "kind": "worktree-lock",
                            "runId": str(
                                item.get("id")
                                or item.get("slug")
                                or item.get("branch")
                                or item.get("path")
                                or "worktree"
                            ),
                            "status": status or ("locked" if locked else ""),
                            "path": _rel_display(root, wt_state),
                        }
                    )

    return blockers


def assert_quiesced(root: Path) -> list[dict[str, Any]]:
    blockers = scan_inflight_blockers(root)
    if blockers:
        raise StateRootMigrateError(
            "inflight-blockers",
            "state-root migration refuses while deliver/wave/worktree locks are in flight",
            blockers=blockers,
            blockingRunIds=[b.get("runId") for b in blockers],
        )
    return blockers


def proposed_moves(root: Path) -> list[dict[str, Any]]:
    moves: list[dict[str, Any]] = []
    for entry in load_inventory_entries(root):
        legacy = str(entry.get("legacyPath") or "").strip().rstrip("/")
        new = str(entry.get("newPath") or "").strip().rstrip("/")
        if not legacy or not new:
            continue
        src = root / legacy
        exists = src.exists()
        moves.append(
            {
                "family": entry.get("family"),
                "accessor": entry.get("accessor"),
                "from": legacy,
                "to": new,
                "exists": exists,
                "action": "move" if exists else "skip-missing",
            }
        )
    moves.sort(key=lambda m: len(str(m["from"])), reverse=True)
    return moves


def detect_legacy_layout(root: Path) -> dict[str, Any]:
    moves = proposed_moves(root)
    present = [m for m in moves if m.get("exists")]
    fence = read_fence(root)
    return {
        "verdict": "legacy-layout" if present else "pass",
        "legacyPresent": bool(present),
        "moveCount": len(present),
        "moves": present,
        "allMoves": moves,
        "staleFence": fence,
    }



def journal_path(root: Path) -> Path:
    return root / JOURNAL_FILENAME


def tree_digest(path: Path) -> str:
    """Content digest for a file or directory tree (semantic identity for R15)."""
    hasher = hashlib.sha256()
    if path.is_file():
        hasher.update(b"file\0")
        hasher.update(path.read_bytes())
        return hasher.hexdigest()
    if not path.exists():
        return hasher.hexdigest()
    entries: list[tuple[str, bytes]] = []
    for child in sorted(path.rglob("*"), key=lambda p: p.as_posix()):
        if child.is_file():
            rel = child.relative_to(path).as_posix()
            entries.append((rel, child.read_bytes()))
    hasher.update(b"dir\0")
    for rel, payload in entries:
        hasher.update(rel.encode("utf-8"))
        hasher.update(b"\0")
        hasher.update(payload)
        hasher.update(b"\0")
    return hasher.hexdigest()


def semantic_snapshot(root: Path, rel_paths: list[str]) -> dict[str, str]:
    """Map relative paths to digests for identity assertions."""
    out: dict[str, str] = {}
    for rel in rel_paths:
        candidate = root / rel
        if candidate.exists():
            out[rel] = tree_digest(candidate)
    return out


def _write_journal(root: Path, journal: dict[str, Any]) -> None:
    journal_path(root).write_text(json.dumps(journal, indent=2) + "\n", encoding="utf-8")


def _read_journal(root: Path) -> dict[str, Any] | None:
    path = journal_path(root)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise StateRootMigrateError(
            "journal-unreadable",
            f"migration journal unreadable: {exc}",
            path=str(path),
        ) from exc
    if not isinstance(data, dict):
        raise StateRootMigrateError(
            "journal-malformed",
            "migration journal must be a JSON object",
            path=str(path),
        )
    return data


def _clear_journal(root: Path) -> None:
    path = journal_path(root)
    if path.is_file():
        path.unlink()


def _new_journal(moves: list[dict[str, Any]]) -> dict[str, Any]:
    entries = []
    for move in moves:
        entries.append(
            {
                "from": str(move["from"]),
                "to": str(move["to"]),
                "status": ENTRY_PENDING,
                "digestBefore": None,
            }
        )
    return {
        "version": 1,
        "status": JOURNAL_STATUS_IN_PROGRESS,
        "createdAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "entries": entries,
    }


def _relocate_one(root: Path, legacy: str, new: str) -> dict[str, Any]:
    src = root / legacy
    dest = root / new
    if not src.exists():
        return {"from": legacy, "to": new, "action": "skip-missing"}
    if dest.exists():
        # Parent/child inventory pairs: children move first and may already
        # have created the parent destination directory. Merge leftovers.
        if src.is_dir() and dest.is_dir():
            for child in list(src.iterdir()):
                target = dest / child.name
                if target.exists():
                    raise StateRootMigrateError(
                        "destination-exists",
                        f"refusing to overwrite existing destination {new}/{child.name}",
                        fromPath=f"{legacy}/{child.name}",
                        toPath=f"{new}/{child.name}",
                    )
                shutil.move(str(child), str(target))
            try:
                src.rmdir()
            except OSError as exc:
                raise StateRootMigrateError(
                    "source-not-empty",
                    f"legacy path {legacy} not empty after merge into {new}: {exc}",
                    fromPath=legacy,
                    toPath=new,
                ) from exc
            return {"from": legacy, "to": new, "action": "merged"}
        raise StateRootMigrateError(
            "destination-exists",
            f"refusing to overwrite existing destination {new}",
            fromPath=legacy,
            toPath=new,
        )
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dest))
    return {"from": legacy, "to": new, "action": "moved"}


def _rollback_one(root: Path, legacy: str, new: str) -> dict[str, Any]:
    src = root / legacy
    dest = root / new
    if dest.exists() and not src.exists():
        src.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(dest), str(src))
        return {"from": new, "to": legacy, "action": "rolled-back"}
    if src.exists() and not dest.exists():
        return {"from": new, "to": legacy, "action": "already-restored"}
    if not dest.exists() and not src.exists():
        return {"from": new, "to": legacy, "action": "missing-both"}
    raise StateRootMigrateError(
        "rollback-conflict",
        f"cannot rollback {new} → {legacy}: conflicting paths exist",
        fromPath=new,
        toPath=legacy,
    )


def _apply_journal_entries(root: Path, journal: dict[str, Any]) -> list[dict[str, Any]]:
    applied: list[dict[str, Any]] = []
    entries = journal.get("entries")
    if not isinstance(entries, list):
        raise StateRootMigrateError("journal-malformed", "journal entries must be a list")
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        status = str(entry.get("status") or ENTRY_PENDING)
        legacy = str(entry.get("from") or "")
        new = str(entry.get("to") or "")
        if status == ENTRY_MOVED:
            applied.append({"from": legacy, "to": new, "action": "already-moved"})
            continue
        if status == ENTRY_ROLLED_BACK:
            continue
        src = root / legacy
        if src.exists() and entry.get("digestBefore") is None:
            entry["digestBefore"] = tree_digest(src)
        result = _relocate_one(root, legacy, new)
        if result["action"] in ("moved", "merged"):
            entry["status"] = ENTRY_MOVED
            entry["digestAfter"] = tree_digest(root / new)
            # Parent/child merges change the parent tree shape by design (children
            # already landed). Enforce byte-identity only for direct moves.
            if result["action"] == "moved":
                before = entry.get("digestBefore")
                if before and entry["digestAfter"] != before:
                    raise StateRootMigrateError(
                        "semantic-identity-mismatch",
                        f"content digest changed while moving {legacy} → {new}",
                        fromPath=legacy,
                        toPath=new,
                    )
        elif result["action"] == "skip-missing" and (root / new).exists():
            entry["status"] = ENTRY_MOVED
            entry["digestAfter"] = tree_digest(root / new)
            result = {"from": legacy, "to": new, "action": "already-moved"}
        _write_journal(root, journal)
        applied.append(result)
    journal["status"] = JOURNAL_STATUS_COMPLETED
    journal["completedAt"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    _write_journal(root, journal)
    return applied


def abort_migration(root: Path, *, holder: str | None = None) -> dict[str, Any]:
    """Roll back an interrupted migration from the journal and release the fence (R15)."""
    del holder  # holder retained for CLI symmetry; fence release is path-based
    journal = _read_journal(root)
    if journal is None:
        release_info = release_quiesce_fence(root, missing_ok=True)
        return {
            "verdict": "pass",
            "aborted": False,
            "message": "no migration journal present",
            "fenceReleased": release_info,
        }
    rolled: list[dict[str, Any]] = []
    entries = list(reversed(journal.get("entries") or []))
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        if str(entry.get("status")) != ENTRY_MOVED:
            continue
        legacy = str(entry.get("from") or "")
        new = str(entry.get("to") or "")
        result = _rollback_one(root, legacy, new)
        entry["status"] = ENTRY_ROLLED_BACK
        rolled.append(result)
        _write_journal(root, journal)
    journal["status"] = JOURNAL_STATUS_ABORTED
    journal["abortedAt"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    _write_journal(root, journal)
    _clear_journal(root)
    release_info = release_quiesce_fence(root, missing_ok=True)
    return {
        "verdict": "pass",
        "aborted": True,
        "rolledBack": rolled,
        "fenceReleased": release_info,
    }


def relocate(
    root: Path,
    *,
    confirm: bool,
    plugin_root: Path | None = None,
    holder: str | None = None,
    resume: bool = False,
    abort: bool = False,
) -> dict[str, Any]:
    """Skew → quiesce → fence → journaled consent/relocate/resume/abort (R13/R14/R15/R54)."""
    if abort:
        return abort_migration(root, holder=holder)

    existing = _read_journal(root)
    if existing is not None and existing.get("status") == JOURNAL_STATUS_IN_PROGRESS:
        if not resume and not confirm:
            return {
                "verdict": "journal-in-progress",
                "error": "journal-in-progress",
                "message": (
                    "interrupted migration journal present; "
                    "re-run with --resume to complete or --abort to roll back"
                ),
                "journal": existing,
                "fenceHeld": fence_held(root),
            }
        if not fence_held(root):
            fence_meta = acquire_quiesce_fence(
                root, holder=holder or "state-root-migrate-resume"
            )
        else:
            fence_meta = read_fence(root) or {"verdict": "pass", "held": True}
        applied = _apply_journal_entries(root, existing)
        _clear_journal(root)
        release_info = release_quiesce_fence(root, missing_ok=True)
        return {
            "verdict": "pass",
            "resumed": True,
            "moved": applied,
            "fence": fence_meta,
            "fenceReleased": release_info,
            "semanticIdentity": True,
        }

    skew = compare_plugin_redirect_map(root, plugin_root)
    assert_quiesced(root)
    moves = proposed_moves(root)
    actionable = [m for m in moves if m.get("exists")]

    fence_meta = acquire_quiesce_fence(root, holder=holder)
    released = False

    def _release() -> dict[str, Any]:
        nonlocal released
        if released:
            return {"verdict": "pass", "released": False, "alreadyReleased": True}
        out = release_quiesce_fence(root, missing_ok=True)
        released = True
        return out

    try:
        if not confirm and not resume:
            release_info = _release()
            return {
                "verdict": "confirm-required",
                "error": "confirm-required",
                "message": (
                    "declining leaves the repository fully functional on legacy paths; "
                    "re-run with --confirm to relocate"
                ),
                "moves": actionable,
                "allMoves": moves,
                "skew": skew,
                "fence": fence_meta,
                "fenceReleased": release_info,
            }

        journal = _new_journal(actionable)
        for entry, move in zip(journal["entries"], actionable):
            src = root / str(move["from"])
            if src.exists():
                entry["digestBefore"] = tree_digest(src)
        _write_journal(root, journal)
        try:
            applied = _apply_journal_entries(root, journal)
        except Exception:
            # Keep journal + fence so resume/abort can finish without manual surgery.
            raise
        _clear_journal(root)
        release_info = _release()
        return {
            "verdict": "pass",
            "moved": applied,
            "moves": actionable,
            "skew": skew,
            "fence": fence_meta,
            "fenceReleased": release_info,
            "semanticIdentity": True,
        }
    except Exception:
        if not journal_path(root).is_file():
            _release()
        raise


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Gated state-root migration (PRD 342).")
    parser.add_argument("--root", default=None, help="Repository root (default: cwd)")
    parser.add_argument(
        "--plugin-root",
        default=None,
        help="Installed plugin root for redirect-map skew comparison",
    )
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("detect", help="Detect legacy layout and list proposed moves")
    sub.add_parser("skew-check", help="Compare plugin vs repo redirect maps")
    sub.add_parser("quiesce-check", help="Scan in-flight deliver/wave/worktree blockers")
    fence_p = sub.add_parser("fence-acquire", help="Acquire exclusive quiesce fence")
    fence_p.add_argument("--holder", default=None)
    sub.add_parser("fence-release", help="Release quiesce fence")
    sub.add_parser("fence-status", help="Report quiesce fence status")
    migrate_p = sub.add_parser("migrate", help="Skew+quiesce+fence gated migrate")
    migrate_p.add_argument(
        "--confirm",
        action="store_true",
        help="Consent to relocate; without this flag no files are moved",
    )
    migrate_p.add_argument(
        "--resume",
        action="store_true",
        help="Resume an interrupted journaled migration (R15)",
    )
    migrate_p.add_argument(
        "--abort",
        action="store_true",
        help="Abort and roll back an interrupted journaled migration (R15)",
    )
    migrate_p.add_argument("--holder", default=None)
    args = parser.parse_args(argv)

    root = Path(args.root).resolve() if args.root else Path.cwd().resolve()
    plugin_root = Path(args.plugin_root).resolve() if args.plugin_root else None
    command = args.command or "detect"

    try:
        if command == "detect":
            out = detect_legacy_layout(root)
        elif command == "skew-check":
            out = compare_plugin_redirect_map(root, plugin_root)
        elif command == "quiesce-check":
            blockers = assert_quiesced(root)
            out = {"verdict": "pass", "blockers": blockers}
        elif command == "fence-acquire":
            out = acquire_quiesce_fence(root, holder=args.holder)
        elif command == "fence-release":
            out = release_quiesce_fence(root, missing_ok=True)
        elif command == "fence-status":
            meta = read_fence(root)
            out = {
                "verdict": "held" if meta else "clear",
                "held": bool(meta),
                "fence": meta,
                "path": str(fence_path(root)),
            }
        elif command == "migrate":
            out = relocate(
                root,
                confirm=bool(args.confirm),
                plugin_root=plugin_root,
                holder=args.holder,
                resume=bool(getattr(args, "resume", False)),
                abort=bool(getattr(args, "abort", False)),
            )
        else:
            out = {"verdict": "fail", "error": f"unknown command: {command}"}
            print(json.dumps(out, indent=2))
            return 2
    except StateRootMigrateError as exc:
        print(json.dumps(exc.as_dict(), indent=2))
        return 1

    print(json.dumps(out, indent=2))
    if out.get("verdict") in ("pass", "clear", "legacy-layout"):
        return 0
    if out.get("verdict") in ("confirm-required", "journal-in-progress"):
        return 1
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
