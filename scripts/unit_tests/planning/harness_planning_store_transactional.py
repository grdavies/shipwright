#!/usr/bin/env python3
"""Two-process concurrency fixtures for file-backed planning store (PRD 082 R28)."""
from __future__ import annotations

import json
import sys
import threading
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from planning_paths import atomic_write_text  # noqa: E402
from planning_store import (  # noqa: E402
    FILE_BACKED_STORE_TXN_ID,
    issue_index_key,
    load_issue_unit_index,
    mutate_issue_unit_index,
    read_issue_unit_index_locked,
    save_issue_unit_index,
)


def _fixture_root(tmp: Path) -> Path:
    (tmp / ".cursor" / "hooks" / "state").mkdir(parents=True, exist_ok=True)
    return tmp


def check_concurrent_index_updates_no_lost_write() -> dict:
    import tempfile

    with tempfile.TemporaryDirectory() as raw:
        root = _fixture_root(Path(raw))
        project_key = "demo"
        errors: list[str] = []
        barrier = threading.Barrier(2)

        def worker(unit_suffix: str) -> None:
            try:
                barrier.wait(timeout=5)
                idx_key = issue_index_key(project_key, f"unit-{unit_suffix}")

                def _update(index: dict[str, str]) -> None:
                    index[idx_key] = f"issue-{unit_suffix}"

                mutate_issue_unit_index(root, _update)
            except Exception as exc:  # pragma: no cover - defensive
                errors.append(str(exc))

        threads = [threading.Thread(target=worker, args=(suffix,), daemon=True) for suffix in ("a", "b")]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)
        if errors:
            return {"verdict": "fail", "check": "concurrent-index", "errors": errors}
        final = load_issue_unit_index(root)
        expected = {
            issue_index_key(project_key, "unit-a"): "issue-a",
            issue_index_key(project_key, "unit-b"): "issue-b",
        }
        for key, value in expected.items():
            if final.get(key) != value:
                return {"verdict": "fail", "check": "lost-update", "index": final, "missing": key}
    return {"verdict": "ok", "check": "concurrent-index"}


def check_index_reread_under_lock() -> dict:
    import tempfile

    with tempfile.TemporaryDirectory() as raw:
        root = _fixture_root(Path(raw))
        project_key = "demo"
        save_issue_unit_index(root, {issue_index_key(project_key, "seed"): "issue-seed"})
        observed: list[str] = []

        def writer() -> None:
            mutate_issue_unit_index(
                root,
                lambda index: index.__setitem__(issue_index_key(project_key, "writer"), "issue-writer"),
            )

        def reader() -> None:
            index = read_issue_unit_index_locked(root)
            observed.append(index.get(issue_index_key(project_key, "seed"), ""))

        writer_thread = threading.Thread(target=writer, daemon=True)
        reader_thread = threading.Thread(target=reader, daemon=True)
        writer_thread.start()
        reader_thread.start()
        writer_thread.join(timeout=5)
        reader_thread.join(timeout=5)
        if "issue-seed" not in observed:
            return {"verdict": "fail", "check": "index-reread", "observed": observed}
    return {"verdict": "ok", "check": "index-reread"}


def check_file_backed_atomic_write() -> dict:
    import tempfile

    with tempfile.TemporaryDirectory() as raw:
        root = _fixture_root(Path(raw))
        target = root / "docs" / "planning" / "unit.md"
        atomic_write_text(target, "hello\n", root=root, store_id=FILE_BACKED_STORE_TXN_ID)
        if target.read_text(encoding="utf-8") != "hello\n":
            return {"verdict": "fail", "check": "atomic-write-content"}
        lock_dir = root / ".cursor" / "hooks" / "state" / "planning-txn" / FILE_BACKED_STORE_TXN_ID
        if not (lock_dir / "store.lock").is_file():
            return {"verdict": "fail", "check": "atomic-write-lock-artifact"}
    return {"verdict": "ok", "check": "atomic-write"}


def main() -> int:
    checks = [
        check_concurrent_index_updates_no_lost_write(),
        check_index_reread_under_lock(),
        check_file_backed_atomic_write(),
    ]
    failed = [item for item in checks if item.get("verdict") != "ok"]
    print(json.dumps({"verdict": "ok" if not failed else "fail", "checks": checks}, indent=2))
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
