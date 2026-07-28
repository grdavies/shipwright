#!/usr/bin/env python3
"""Planning store transaction coordinator with durable journal (PRD 082 R28)."""
from __future__ import annotations

import fcntl
import json
import os
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

JOURNAL_VERSION = 1
TXN_STATE_DIR = ".cursor/hooks/state/planning-txn"
RENAME_ORDER = "path-asc"


class TransactionError(RuntimeError):
    """Coordinator transaction failure."""


class JournalCorruptError(TransactionError):
    """Journal record is invalid or incomplete."""


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def txn_state_dir(root: Path, store_id: str) -> Path:
    safe = store_id.replace("/", "_").replace("..", "_")
    return root / TXN_STATE_DIR / safe


def lock_path(root: Path, store_id: str) -> Path:
    return txn_state_dir(root, store_id) / "store.lock"


def journal_path(root: Path, store_id: str) -> Path:
    return txn_state_dir(root, store_id) / "journal.json"


def crash_hook(point: str) -> None:
    target = os.environ.get("SW_PLANNING_TXN_CRASH_AFTER", "").strip()
    if target and target == point:
        raise TransactionError(f"crash-injection:{point}")


def fsync_file(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def fsync_dir(path: Path) -> None:
    try:
        dir_fd = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)


def durable_write_bytes(path: Path, payload: bytes, *, mode: int = 0o600) -> None:
    """Temp write, fsync file, rename, fsync directory (defined durable order)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
    try:
        os.write(fd, payload)
        os.fsync(fd)
    finally:
        os.close(fd)
    crash_hook("after-temp-write")
    os.replace(tmp, path)
    crash_hook("after-rename")
    fsync_file(path)
    fsync_dir(path.parent)


def durable_write_text(path: Path, content: str, *, mode: int = 0o600) -> None:
    durable_write_bytes(path, content.encode("utf-8"), mode=mode)


@dataclass
class StagedOp:
    kind: str
    target: str
    temp: str | None = None
    payload_digest: str | None = None


@dataclass
class PlanningTxnCoordinator:
    root: Path
    store_id: str
    txn_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    _staged: list[StagedOp] = field(default_factory=list)
    _lock_fd: int | None = None
    _journal_written: bool = False

    def stage_write(self, target: Path, content: str | bytes) -> None:
        rel = str(target.resolve().relative_to(self.root.resolve())).replace("\\", "/")
        payload = content.encode("utf-8") if isinstance(content, str) else content
        temp = target.with_name(f".{target.name}.{self.txn_id}.staging")
        durable_write_bytes(temp, payload)
        self._staged.append(StagedOp(kind="write", target=rel, temp=str(temp.resolve())))

    def stage_rename(self, source: Path, target: Path) -> None:
        self._staged.append(
            StagedOp(
                kind="rename",
                target=str(target.resolve().relative_to(self.root.resolve())).replace("\\", "/"),
                temp=str(source.resolve().relative_to(self.root.resolve())).replace("\\", "/"),
            )
        )

    def _sorted_ops(self) -> list[StagedOp]:
        writes = sorted((op for op in self._staged if op.kind == "write"), key=lambda op: op.target)
        renames = sorted((op for op in self._staged if op.kind == "rename"), key=lambda op: op.target)
        return [*writes, *renames]

    def _journal_document(self, *, status: str) -> dict[str, Any]:
        ordered = self._sorted_ops()
        return {
            "version": JOURNAL_VERSION,
            "txnId": self.txn_id,
            "storeId": self.store_id,
            "status": status,
            "renameOrder": RENAME_ORDER,
            "startedAt": utc_now(),
            "ops": [
                {
                    "kind": op.kind,
                    "target": op.target,
                    **({"temp": op.temp} if op.temp else {}),
                }
                for op in ordered
            ],
        }

    def _write_journal(self, status: str) -> None:
        path = journal_path(self.root, self.store_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        durable_write_text(path, json.dumps(self._journal_document(status=status), indent=2) + "\n")
        self._journal_written = True
        crash_hook("after-journal-write")

    def _apply_staged(self) -> None:
        for op in self._sorted_ops():
            if op.kind != "write":
                if op.kind != "rename":
                    raise TransactionError(f"unknown staged op: {op.kind}")
                if not op.temp:
                    raise TransactionError("staged rename missing source path")
                source = self.root / op.temp
                target = self.root / op.target
                target.parent.mkdir(parents=True, exist_ok=True)
                os.replace(source, target)
                fsync_file(target)
                fsync_dir(target.parent)
                continue
            if not op.temp:
                raise TransactionError("staged write missing temp path")
            target = self.root / op.target
            source = Path(op.temp)
            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(source, target)
            crash_hook("after-first-rename")
            fsync_file(target)
            fsync_dir(target.parent)

    def _clear_journal(self) -> None:
        path = journal_path(self.root, self.store_id)
        if path.is_file():
            path.unlink()

    def commit(self) -> None:
        if not self._staged:
            return
        self._write_journal("pending")
        try:
            self._apply_staged()
            self._clear_journal()
        except Exception:
            raise

    def rollback_staging(self) -> None:
        if self._journal_written:
            return
        for op in self._staged:
            if op.kind != "write" or not op.temp:
                continue
            temp = Path(op.temp)
            if temp.is_file():
                temp.unlink(missing_ok=True)


@contextmanager
def store_lock(root: Path, store_id: str) -> Iterator[None]:
    path = lock_path(root, store_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


@contextmanager
def planning_transaction(root: Path, store_id: str) -> Iterator[PlanningTxnCoordinator]:
    """Exclusive per-store lock held across load → mutate → save."""
    root = root.resolve()
    with store_lock(root, store_id):
        coordinator = PlanningTxnCoordinator(root=root, store_id=store_id)
        try:
            yield coordinator
            coordinator.commit()
        except Exception:
            coordinator.rollback_staging()
            raise


def load_journal(root: Path, store_id: str) -> dict[str, Any] | None:
    path = journal_path(root, store_id)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise JournalCorruptError(f"journal corrupt: {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise JournalCorruptError(f"journal root must be object: {path}")
    return data
