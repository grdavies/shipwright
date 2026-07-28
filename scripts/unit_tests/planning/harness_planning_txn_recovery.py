#!/usr/bin/env python3
"""Journal replay fixtures for planning transaction recovery (PRD 082 R28)."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from planning_txn import TransactionError, journal_path, planning_transaction  # noqa: E402
from planning_txn_recovery import JournalCorruptError, replay_journal, startup_recovery  # noqa: E402


def _fixture_root(tmp: Path) -> Path:
    (tmp / ".cursor" / "hooks" / "state").mkdir(parents=True, exist_ok=True)
    return tmp


def check_replay_completes_interrupted_link_update() -> dict:
    import tempfile

    with tempfile.TemporaryDirectory() as raw:
        root = _fixture_root(Path(raw))
        store_id = "link-store"
        link = root / "links" / "unit-a.json"
        os.environ["SW_PLANNING_TXN_CRASH_AFTER"] = "after-journal-write"
        try:
            with planning_transaction(root, store_id) as txn:
                txn.stage_write(link, '{"id":"unit-a","target":"unit-b"}\n')
        except TransactionError:
            pass
        finally:
            os.environ.pop("SW_PLANNING_TXN_CRASH_AFTER", None)
        if link.is_file():
            return {"verdict": "fail", "check": "link-not-interrupted"}
        result = replay_journal(root, store_id)
        if result.get("verdict") != "ok" or not link.is_file():
            return {"verdict": "fail", "check": "replay-completes-link", "result": result}
    return {"verdict": "ok", "check": "replay-completes-link"}


def check_repeated_replay_is_noop() -> dict:
    import tempfile

    with tempfile.TemporaryDirectory() as raw:
        root = _fixture_root(Path(raw))
        store_id = "noop-store"
        target = root / "state.json"
        with planning_transaction(root, store_id) as txn:
            txn.stage_write(target, '{"ok":true}\n')
        first = startup_recovery(root)
        second = startup_recovery(root)
        if first.get("verdict") != "ok" or second.get("verdict") != "ok":
            return {"verdict": "fail", "check": "startup-recovery", "first": first, "second": second}
        if second.get("results"):
            return {"verdict": "fail", "check": "second-replay-should-be-empty", "second": second}
    return {"verdict": "ok", "check": "repeated-replay-noop"}


def check_corrupt_journal_fails_closed() -> dict:
    import tempfile

    with tempfile.TemporaryDirectory() as raw:
        root = _fixture_root(Path(raw))
        store_id = "corrupt-store"
        path = journal_path(root, store_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"version": 1, "status": "pending", "ops": []}) + "\n", encoding="utf-8")
        try:
            replay_journal(root, store_id)
        except JournalCorruptError:
            return {"verdict": "ok", "check": "corrupt-journal-fail-closed"}
        return {"verdict": "fail", "check": "corrupt-journal-should-raise"}
    return {"verdict": "fail", "check": "unreachable"}


def main() -> int:
    checks = [
        check_replay_completes_interrupted_link_update(),
        check_repeated_replay_is_noop(),
        check_corrupt_journal_fails_closed(),
    ]
    failed = [item for item in checks if item.get("verdict") != "ok"]
    print(json.dumps({"verdict": "ok" if not failed else "fail", "checks": checks}, indent=2))
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
