#!/usr/bin/env python3
"""Transactional planning-unit number reservation (PRD 081 R16).

Stable unit identity is separate from the sequential PRD number. Under issue-store the
store mints through the duplicate-open-tasks guard; under file-store a git-common-dir lock
file reserves the number until completion or staleness reclaim.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import socket
import sys
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Iterable

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from planning_lifecycle import collect_occupied_prd_numbers, next_free_prd_number, prd_number_from_unit_id
from wave_state import canonical_repo_root, emit, fail, lock_is_stale, lock_owner_live, read_lock_meta, utc_now

RESERVATIONS_DIR_NAME = "sw-planning-reservations"
RESERVATION_STALE_SECONDS = int(os.environ.get("SW_PLANNING_RESERVE_STALE_SECONDS", "300"))
_PRD_DIR_RE = re.compile(r"^(\d{3})-")
# flock(2) is process-scoped; serialize same-process threads separately.
_ALLOCATOR_THREAD_LOCK = threading.Lock()


def reservation_host() -> str:
    return socket.gethostname()


def emit_result(obj: dict[str, Any], exit_code: int = 0) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))
    sys.exit(exit_code)


def reservations_dir(root: Path) -> Path:
    repo_root = canonical_repo_root(root)
    base_raw = repo_root / ".cursor" / RESERVATIONS_DIR_NAME
    parent_raw = repo_root / ".cursor"
    if parent_raw.is_symlink():
        fail("planning-reservation parent is symlinked", exit_code=20, halt="reservation-path-unsafe")
    if base_raw.is_symlink():
        fail("planning-reservation directory is symlinked", exit_code=20, halt="reservation-path-unsafe")
    base = base_raw.resolve()
    parent = base.parent.resolve()
    if parent.is_symlink():
        fail("planning-reservation parent is symlinked", exit_code=20, halt="reservation-path-unsafe")
    base.mkdir(parents=True, exist_ok=True)
    return base


def reservation_digest(unit_id: str) -> str:
    return hashlib.sha256(unit_id.encode("utf-8")).hexdigest()[:16]


def reservation_lock_path(root: Path, number: int, unit_id: str | None = None) -> Path:
    locks = reservations_dir(root)
    filename = f"{number:03d}.lock"
    path = (locks / filename).resolve()
    if path.parent != locks:
        fail("reservation path escapes reservations directory", exit_code=20, halt="reservation-path-unsafe")
    locks_raw = canonical_repo_root(root) / ".cursor" / RESERVATIONS_DIR_NAME
    if locks_raw.is_symlink():
        fail("planning-reservation directory is symlinked", exit_code=20, halt="reservation-path-unsafe")
    return path


def format_prd_unit_id(number: int, slug: str) -> str:
    return f"{number:03d}-prd-{slug}"


def scan_prd_dirs(root: Path) -> set[int]:
    occupied: set[int] = set()
    prds_root = root / "docs" / "prds"
    if not prds_root.is_dir():
        return occupied
    for child in prds_root.iterdir():
        if not child.is_dir():
            continue
        match = _PRD_DIR_RE.match(child.name)
        if match:
            occupied.add(int(match.group(1)))
    return occupied


def read_reservation_meta(lock_path: Path) -> dict[str, Any]:
    return read_lock_meta(lock_path)


def reservation_is_stale(meta: dict[str, Any]) -> bool:
    if not meta:
        return True
    if meta.get("status") == "completed":
        return True
    ts = meta.get("heartbeatAt") or meta.get("acquiredAt")
    if not isinstance(ts, str):
        return True
    try:
        dt = datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        age = (datetime.now(timezone.utc) - dt).total_seconds()
        return age > RESERVATION_STALE_SECONDS
    except ValueError:
        return True


def reservation_owner_live(meta: dict[str, Any]) -> bool:
    if not reservation_is_stale(meta):
        return True
    pid = meta.get("pid")
    if isinstance(pid, int) and pid > 0:
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False
    return False


def reclaim_stale_reservation(lock_path: Path) -> bool:
    meta = read_reservation_meta(lock_path)
    if not meta:
        lock_path.unlink(missing_ok=True)
        return True
    if meta.get("status") == "completed":
        lock_path.unlink(missing_ok=True)
        return True
    if reservation_owner_live(meta):
        return False
    lock_path.unlink(missing_ok=True)
    return True


def active_reserved_numbers(root: Path) -> set[int]:
    numbers: set[int] = set()
    locks = reservations_dir(root)
    for lock_path in locks.glob("*.lock"):
        meta = read_reservation_meta(lock_path)
        if not meta:
            reclaim_stale_reservation(lock_path)
            continue
        if meta.get("status") == "completed":
            continue
        if not reservation_owner_live(meta):
            reclaim_stale_reservation(lock_path)
            continue
        number = meta.get("number")
        if isinstance(number, int):
            numbers.add(number)
        elif isinstance(number, str) and number.isdigit():
            numbers.add(int(number))
    return numbers


def occupied_numbers_file_store(root: Path, *, extra_unit_ids: Iterable[str] | None = None) -> set[int]:
    occupied = scan_prd_dirs(root)
    occupied |= active_reserved_numbers(root)
    if extra_unit_ids:
        occupied |= collect_occupied_prd_numbers(extra_unit_ids)
    return occupied


def _reservation_payload(
    *,
    number: int,
    unit_id: str,
    slug: str,
    holder_id: str,
    backend: str,
) -> dict[str, Any]:
    now = utc_now()
    return {
        "kind": "planning-number-reservation",
        "number": number,
        "unitId": unit_id,
        "slug": slug,
        "holderId": holder_id,
        "backend": backend,
        "status": "reserved",
        "owner": f"{reservation_host()}:{os.getpid()}",
        "host": reservation_host(),
        "pid": os.getpid(),
        "acquiredAt": now,
        "heartbeatAt": now,
    }


def _write_reservation_lock(lock_path: Path, payload: dict[str, Any]) -> None:
    """Create number lock exclusively, then write payload before releasing the fd.

    Callers must hold `_allocator_lock` so concurrent reclaim cannot unlink a
    half-written lock between O_EXCL create and content flush (TOCTOU).
    """
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    try:
        fd = os.open(lock_path, flags, 0o600)
    except FileExistsError:
        raise
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, indent=2))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        lock_path.unlink(missing_ok=True)
        raise


@contextmanager
def _allocator_lock(root: Path) -> Iterator[None]:
    """Serialize number allocation across threads and processes in one repo."""
    with _ALLOCATOR_THREAD_LOCK:
        locks = reservations_dir(root)
        path = locks / ".allocator.lock"
        fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)


def find_reservation_lock(root: Path, unit_id: str) -> Path | None:
    for lock_path in reservations_dir(root).glob("*.lock"):
        if lock_path.name.startswith("."):
            continue
        meta = read_reservation_meta(lock_path)
        if meta.get("unitId") == unit_id:
            return lock_path
    return None


def reserve_number_file_store(
    root: Path,
    *,
    unit_id: str,
    slug: str,
    holder_id: str,
    extra_unit_ids: Iterable[str] | None = None,
) -> dict[str, Any]:
    with _allocator_lock(root):
        existing = find_reservation_lock(root, unit_id)
        if existing and existing.is_file():
            meta = read_reservation_meta(existing)
            if meta.get("status") == "reserved" and reservation_owner_live(meta):
                number = int(meta["number"])
                return {
                    "verdict": "pass",
                    "action": "reserve-number",
                    "backend": "file-store",
                    "number": number,
                    "unitId": unit_id,
                    "slug": slug,
                    "formattedUnitId": format_prd_unit_id(number, slug),
                    "lockPath": str(existing),
                    "replayed": True,
                }
            reclaim_stale_reservation(existing)

        occupied = occupied_numbers_file_store(root, extra_unit_ids=extra_unit_ids)
        for _ in range(128):
            number = next_free_prd_number(occupied)
            lock_path = reservation_lock_path(root, number, unit_id)
            if lock_path.is_file():
                reclaim_stale_reservation(lock_path)
                if lock_path.is_file():
                    occupied.add(number)
                    continue
            payload = _reservation_payload(
                number=number,
                unit_id=unit_id,
                slug=slug,
                holder_id=holder_id,
                backend="file-store",
            )
            try:
                _write_reservation_lock(lock_path, payload)
            except FileExistsError:
                occupied.add(number)
                continue
            owned = read_reservation_meta(lock_path)
            if owned.get("unitId") != unit_id or int(owned.get("number") or -1) != number:
                occupied.add(number)
                continue
            return {
                "verdict": "pass",
                "action": "reserve-number",
                "backend": "file-store",
                "number": number,
                "unitId": unit_id,
                "slug": slug,
                "formattedUnitId": format_prd_unit_id(number, slug),
                "lockPath": str(lock_path),
                "replayed": False,
            }
        return {
            "verdict": "fail",
            "error": "reservation-exhausted",
            "unitId": unit_id,
        }


def _list_issue_store_unit_ids(root: Path, cfg: dict[str, Any]) -> list[str]:
    import planning_store as ps

    backend = ps.get_backend(root, cfg, override="issue-store")
    search = getattr(getattr(backend, "_client", None), "issue_search", None)
    if not callable(search):
        return []
    project_key = getattr(backend, "project_key", "")
    unit_ids: list[str] = []
    for record in search(project_key=project_key):
        unit_id = str(getattr(record, "unit_id", "") or "").strip()
        if unit_id:
            unit_ids.append(unit_id)
    return unit_ids


def reserve_number_issue_store(
    root: Path,
    cfg: dict[str, Any],
    *,
    unit_id: str,
    slug: str,
    holder_id: str,
) -> dict[str, Any]:
    import planning_store as ps
    from planning_migrate_issue_store import issue_store_effective

    if not issue_store_effective(root, cfg):
        return {
            "verdict": "fail",
            "error": "issue-store-not-effective",
            "unitId": unit_id,
        }

    with _allocator_lock(root):
        existing = find_reservation_lock(root, unit_id)
        if existing and existing.is_file():
            meta = read_reservation_meta(existing)
            if meta.get("status") == "reserved" and reservation_owner_live(meta):
                number = int(meta["number"])
                return {
                    "verdict": "pass",
                    "action": "reserve-number",
                    "backend": "issue-store",
                    "number": number,
                    "unitId": unit_id,
                    "slug": slug,
                    "formattedUnitId": format_prd_unit_id(number, slug),
                    "lockPath": str(existing),
                    "replayed": True,
                }
            reclaim_stale_reservation(existing)

        unit_ids = _list_issue_store_unit_ids(root, cfg)
        occupied = collect_occupied_prd_numbers(unit_ids)
        occupied |= active_reserved_numbers(root)
        number = next_free_prd_number(occupied)
        lock_path = reservation_lock_path(root, number, unit_id)
        payload = _reservation_payload(
            number=number,
            unit_id=unit_id,
            slug=slug,
            holder_id=holder_id,
            backend="issue-store",
        )
        try:
            _write_reservation_lock(lock_path, payload)
        except FileExistsError:
            reclaim_stale_reservation(lock_path)
            if lock_path.is_file():
                meta = read_reservation_meta(lock_path)
                if meta.get("unitId") == unit_id and meta.get("status") == "reserved":
                    return {
                        "verdict": "pass",
                        "action": "reserve-number",
                        "backend": "issue-store",
                        "number": int(meta["number"]),
                        "unitId": unit_id,
                        "slug": slug,
                        "formattedUnitId": format_prd_unit_id(int(meta["number"]), slug),
                        "lockPath": str(lock_path),
                        "replayed": True,
                    }
            return {
                "verdict": "fail",
                "error": "reservation-contention",
                "unitId": unit_id,
            }

    backend = ps.get_backend(root, cfg, override="issue-store")
    formatted = format_prd_unit_id(number, slug)
    placeholder_body = (
        f"---\nid: {formatted}\ntype: prd\nstatus: proposed\n"
        f"reservation-holder: {holder_id}\n---\n# Reserved\n"
    )
    body_path = f"docs/prds/{formatted}/prd.md"
    try:
        backend._guard_duplicate_open_tasks_mint(formatted)
        result = backend.put(formatted, body_path, placeholder_body)
    except SystemExit:
        lock_path.unlink(missing_ok=True)
        raise
    if result.verdict != "ok":
        lock_path.unlink(missing_ok=True)
        return {
            "verdict": "fail",
            "error": "issue-store-mint-failed",
            "unitId": unit_id,
            "store": result.__dict__,
        }

    return {
        "verdict": "pass",
        "action": "reserve-number",
        "backend": "issue-store",
        "number": number,
        "unitId": unit_id,
        "slug": slug,
        "formattedUnitId": formatted,
        "lockPath": str(lock_path),
        "storeUnitId": formatted,
        "replayed": False,
    }


def reserve_number(
    root: Path,
    *,
    unit_id: str,
    slug: str,
    holder_id: str,
    cfg: dict[str, Any] | None = None,
    extra_unit_ids: Iterable[str] | None = None,
) -> dict[str, Any]:
    import planning_store as ps
    from planning_migrate_issue_store import issue_store_effective

    root = ps.git_root(root)
    cfg = cfg or ps.load_workflow_config(root)
    if issue_store_effective(root, cfg):
        return reserve_number_issue_store(
            root,
            cfg,
            unit_id=unit_id,
            slug=slug,
            holder_id=holder_id,
        )
    return reserve_number_file_store(
        root,
        unit_id=unit_id,
        slug=slug,
        holder_id=holder_id,
        extra_unit_ids=extra_unit_ids,
    )


def complete_reservation(root: Path, *, unit_id: str) -> dict[str, Any]:
    lock_path = find_reservation_lock(root, unit_id)
    if not lock_path or not lock_path.is_file():
        return {"verdict": "fail", "error": "reservation-not-found", "unitId": unit_id}
    meta = read_reservation_meta(lock_path)
    meta["status"] = "completed"
    meta["completedAt"] = utc_now()
    lock_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lock_path.unlink(missing_ok=True)
    return {
        "verdict": "pass",
        "action": "complete-reservation",
        "unitId": unit_id,
        "number": meta.get("number"),
    }


def release_reservation(root: Path, *, unit_id: str) -> dict[str, Any]:
    lock_path = find_reservation_lock(root, unit_id)
    if not lock_path or not lock_path.is_file():
        return {"verdict": "fail", "error": "reservation-not-found", "unitId": unit_id}
    meta = read_reservation_meta(lock_path)
    lock_path.unlink(missing_ok=True)
    return {
        "verdict": "pass",
        "action": "release-reservation",
        "unitId": unit_id,
        "number": meta.get("number"),
    }


def reclaim_stale_reservations(root: Path) -> dict[str, Any]:
    reclaimed: list[str] = []
    for lock_path in reservations_dir(root).glob("*.lock"):
        if reclaim_stale_reservation(lock_path):
            reclaimed.append(lock_path.name)
    return {"verdict": "pass", "action": "reclaim-stale-reservations", "reclaimed": reclaimed}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Transactional planning-unit number reservation (PRD 081 R16).")
    sub = parser.add_subparsers(dest="command", required=True)

    reserve = sub.add_parser("reserve", help="Reserve the next planning number for a unit id")
    reserve.add_argument("--root", default=".")
    reserve.add_argument("--unit-id", required=True)
    reserve.add_argument("--slug", required=True)
    reserve.add_argument("--holder-id", required=True)

    complete = sub.add_parser("complete", help="Complete and release a reservation")
    complete.add_argument("--root", default=".")
    complete.add_argument("--unit-id", required=True)

    release = sub.add_parser("release", help="Release a reservation without completing")
    release.add_argument("--root", default=".")
    release.add_argument("--unit-id", required=True)

    reclaim = sub.add_parser("reclaim-stale", help="Reclaim stale reservation locks")
    reclaim.add_argument("--root", default=".")

    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    if args.command == "reserve":
        out = reserve_number(
            root,
            unit_id=args.unit_id,
            slug=args.slug,
            holder_id=args.holder_id,
        )
    elif args.command == "complete":
        out = complete_reservation(root, unit_id=args.unit_id)
    elif args.command == "release":
        out = release_reservation(root, unit_id=args.unit_id)
    else:
        out = reclaim_stale_reservations(root)
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if out.get("verdict") == "pass" else 2


if __name__ == "__main__":
  raise SystemExit(main())
