#!/usr/bin/env python3
"""Interchange crash-window fixtures for note+link transactional import (PRD 082 R28)."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from basic_memory_interchange import (  # noqa: E402
    ensure_project,
    interchange_store_id,
    load_links,
    write_note,
)
from planning_txn import TransactionError, journal_path, planning_transaction  # noqa: E402
from planning_txn_recovery import replay_journal  # noqa: E402


def check_note_and_link_commit_together() -> dict:
    import tempfile

    with tempfile.TemporaryDirectory() as raw:
        project = Path(raw) / "bm-project"
        ensure_project(project)
        note = {
            "permalink": "alpha-note",
            "category": "learning",
            "frontmatter": {"permalink": "alpha-note", "title": "Alpha"},
            "body": "body\n",
            "links": None,
        }
        root = project
        store_id = interchange_store_id(project)
        with planning_transaction(root, store_id) as txn:
            write_note(project, note, txn=txn)
            from basic_memory_interchange import save_links

            save_links(
                project,
                [{"source": "alpha-note", "target": "beta-note", "edge": "relates-to"}],
                txn=txn,
            )
        links = load_links(project)
        if not any(link["source"] == "alpha-note" for link in links):
            return {"verdict": "fail", "check": "links-present"}
        note_path = project / "memories" / "learning" / "alpha-note.md"
        if not note_path.is_file():
            return {"verdict": "fail", "check": "note-present"}
    return {"verdict": "ok", "check": "note-link-atomic"}


def check_crash_replay_completes_link_update() -> dict:
    import tempfile

    with tempfile.TemporaryDirectory() as raw:
        project = Path(raw) / "bm-project"
        ensure_project(project)
        root = project
        store_id = interchange_store_id(project)
        note = {
            "permalink": "crash-note",
            "category": "learning",
            "frontmatter": {"permalink": "crash-note", "title": "Crash"},
            "body": "body\n",
            "links": None,
        }
        os.environ["SW_PLANNING_TXN_CRASH_AFTER"] = "after-journal-write"
        try:
            with planning_transaction(root, store_id) as txn:
                write_note(project, note, txn=txn)
                from basic_memory_interchange import save_links

                save_links(
                    project,
                    [{"source": "crash-note", "target": "other-note", "edge": "relates-to"}],
                    txn=txn,
                )
        except TransactionError:
            pass
        finally:
            os.environ.pop("SW_PLANNING_TXN_CRASH_AFTER", None)
        if not journal_path(root, store_id).is_file():
            return {"verdict": "fail", "check": "journal-present"}
        replay = replay_journal(root, store_id)
        if replay.get("verdict") != "ok":
            return {"verdict": "fail", "check": "replay", "replay": replay}
        links = load_links(project)
        if not any(link["target"] == "other-note" for link in links):
            return {"verdict": "fail", "check": "link-after-replay", "links": links}
        note_path = project / "memories" / "learning" / "crash-note.md"
        if not note_path.is_file():
            return {"verdict": "fail", "check": "note-after-replay"}
    return {"verdict": "ok", "check": "crash-replay"}


def main() -> int:
    checks = [
        check_note_and_link_commit_together(),
        check_crash_replay_completes_link_update(),
    ]
    failed = [item for item in checks if item.get("verdict") != "ok"]
    print(json.dumps({"verdict": "ok" if not failed else "fail", "checks": checks}, indent=2))
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
