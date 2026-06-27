#!/usr/bin/env python3
"""Repo-wide lock serializing living-doc writes across parallel deliver runs (PRD 013 R12)."""
from __future__ import annotations

import json
import os
import socket
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from wave_state import LOCK_STALE_SECONDS, lock_is_stale, lock_owner_live, read_lock_meta, reclaim_stale_lock

LIVING_DOC_LOCK_NAME = "sw-living-docs.lock"


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def lock_path(root: Path) -> Path:
    return root / ".cursor" / LIVING_DOC_LOCK_NAME


def lock_host() -> str:
    return socket.gethostname()


def try_acquire(root: Path, *, target: str | None = None, holder: str | None = None) -> bool:
    path = lock_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    now = utc_now()
    meta = {
        "target": target,
        "holder": holder or "living-doc-write",
        "pid": os.getpid(),
        "host": lock_host(),
        "acquiredAt": now,
        "heartbeatAt": now,
    }
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    try:
        fd = os.open(path, flags, 0o600)
    except FileExistsError:
        existing = read_lock_meta(path)
        if reclaim_stale_lock(path):
            try:
                fd = os.open(path, flags, 0o600)
            except FileExistsError:
                return False
        else:
            return False
    os.write(fd, (json.dumps(meta) + "\n").encode("utf-8"))
    os.close(fd)
    return True


def release(root: Path) -> None:
    lock_path(root).unlink(missing_ok=True)


def acquire_or_fail(root: Path, *, target: str | None = None, holder: str | None = None) -> None:
    if try_acquire(root, target=target, holder=holder):
        return
    existing = read_lock_meta(lock_path(root))
    print(
        json.dumps(
            {
                "verdict": "fail",
                "error": "living-doc lock held",
                "exit_code": 20,
                "holder": existing,
            },
            indent=2,
        ),
        file=sys.stderr,
    )
    sys.exit(20)


@contextmanager
def living_doc_write_lock(
    root: Path,
    *,
    target: str | None = None,
    holder: str | None = None,
) -> Iterator[None]:
    acquire_or_fail(root, target=target, holder=holder)
    try:
        yield
    finally:
        release(root)
