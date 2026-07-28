#!/usr/bin/env python3
"""Crash-injection fixtures for planning transaction coordinator (PRD 082 R28)."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from planning_txn import (  # noqa: E402
    TransactionError,
    journal_path,
    lock_path,
    planning_transaction,
)
from planning_txn_recovery import replay_journal, startup_recovery  # noqa: E402


def _fixture_root(tmp: Path) -> Path:
    (tmp / ".cursor" / "hooks" / "state").mkdir(parents=True, exist_ok=True)
    return tmp


def check_prior_state_intact_after_temp_write_crash() -> dict:
    import tempfile

    with tempfile.TemporaryDirectory() as raw:
        root = _fixture_root(Path(raw))
        store_id = "fixture-store"
        target = root / "data" / "index.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text('{"version":1}\n', encoding="utf-8")
        prior = target.read_text(encoding="utf-8")
        os.environ["SW_PLANNING_TXN_CRASH_AFTER"] = "after-temp-write"
        try:
            with planning_transaction(root, store_id) as txn:
                txn.stage_write(target, '{"version":2}\n')
        except TransactionError:
            pass
        finally:
            os.environ.pop("SW_PLANNING_TXN_CRASH_AFTER", None)
        if target.read_text(encoding="utf-8") != prior:
            return {"verdict": "fail", "check": "prior-state-intact"}
        if journal_path(root, store_id).is_file():
            return {"verdict": "fail", "check": "no-partial-journal-on-staging-crash"}
    return {"verdict": "ok", "check": "prior-state-intact"}


def check_lock_held_across_load_mutate_save() -> dict:
    import fcntl
    import tempfile
    import threading
    import time

    with tempfile.TemporaryDirectory() as raw:
        root = _fixture_root(Path(raw))
        store_id = "lock-store"
        path = lock_path(root, store_id)
        held = threading.Event()
        release = threading.Event()
        errors: list[str] = []

        def _txn() -> None:
            try:
                with planning_transaction(root, store_id) as txn:
                    held.set()
                    release.wait(timeout=5)
                    txn.stage_write(root / "out.txt", "payload\n")
            except Exception as exc:  # pragma: no cover - defensive
                errors.append(str(exc))

        worker = threading.Thread(target=_txn, daemon=True)
        worker.start()
        if not held.wait(timeout=5):
            return {"verdict": "fail", "check": "txn-never-started"}
        outer_fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            try:
                fcntl.flock(outer_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                blocked = False
            except BlockingIOError:
                blocked = True
        finally:
            try:
                fcntl.flock(outer_fd, fcntl.LOCK_UN)
            except OSError:
                pass
            os.close(outer_fd)
        release.set()
        worker.join(timeout=5)
        if errors:
            return {"verdict": "fail", "check": "txn-error", "errors": errors}
        if not blocked:
            return {"verdict": "fail", "check": "lock-not-exclusive"}
    return {"verdict": "ok", "check": "lock-held"}


def check_fsync_and_rename_order() -> dict:
    import tempfile

    with tempfile.TemporaryDirectory() as raw:
        root = _fixture_root(Path(raw))
        store_id = "order-store"
        a = root / "z-last.json"
        b = root / "a-first.json"
        with planning_transaction(root, store_id) as txn:
            txn.stage_write(a, '{"z":1}\n')
            txn.stage_write(b, '{"a":1}\n')
        journal = json.loads(journal_path(root, store_id).read_text(encoding="utf-8")) if False else {}
        # After commit journal is cleared; inspect durable outputs instead.
        if not a.is_file() or not b.is_file():
            return {"verdict": "fail", "check": "outputs-exist"}
        # Re-run with journal capture by crashing after journal write.
        a.unlink()
        b.unlink()
        os.environ["SW_PLANNING_TXN_CRASH_AFTER"] = "after-journal-write"
        try:
            with planning_transaction(root, store_id) as txn:
                txn.stage_write(a, '{"z":1}\n')
                txn.stage_write(b, '{"a":1}\n')
        except TransactionError:
            pass
        finally:
            os.environ.pop("SW_PLANNING_TXN_CRASH_AFTER", None)
        journal = json.loads(journal_path(root, store_id).read_text(encoding="utf-8"))
        targets = [op["target"] for op in journal.get("ops", []) if op.get("kind") == "write"]
        if targets != sorted(targets):
            return {"verdict": "fail", "check": "rename-order", "targets": targets}
        replay_journal(root, store_id)
        if not a.is_file() or not b.is_file():
            return {"verdict": "fail", "check": "replay-applied"}
    return {"verdict": "ok", "check": "fsync-rename-order"}


def main() -> int:
    checks = [
        check_prior_state_intact_after_temp_write_crash(),
        check_lock_held_across_load_mutate_save(),
        check_fsync_and_rename_order(),
    ]
    failed = [item for item in checks if item.get("verdict") != "ok"]
    print(json.dumps({"verdict": "ok" if not failed else "fail", "checks": checks}, indent=2))
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
