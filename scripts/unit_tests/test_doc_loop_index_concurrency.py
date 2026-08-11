"""PRD 090 R1 — concurrent doc-run index updates never lose entries."""

from __future__ import annotations

import json
import sys
import threading
from pathlib import Path
from unittest.mock import patch

import pytest

scripts = Path(__file__).resolve().parents[1]
if str(scripts) not in sys.path:
    sys.path.insert(0, str(scripts))

from doc_loop import doc_index_path, provision_doc_run, update_doc_index, initial_doc_state, save_doc_state


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    (root / ".cursor").mkdir(parents=True, exist_ok=True)
    return root


@pytest.fixture(autouse=True)
def anchor_repo(repo: Path):
    with patch("wave_lock._canonical_repo_root_for_locks", return_value=repo):
        yield


def _index_run_ids(repo: Path) -> set[str]:
    index = json.loads(doc_index_path(repo).read_text(encoding="utf-8"))
    runs = index.get("runs") or {}
    if isinstance(runs, dict):
        return {str(run_id) for run_id in runs}
    return set()


def _provision_pair(repo: Path, *, delay: str | None = None) -> tuple[dict[str, str], list[str]]:
    errors: list[str] = []
    barrier = threading.Barrier(2)
    results: dict[str, str] = {}

    def worker(topic: str, run_id: str) -> None:
        try:
            barrier.wait(timeout=5)
            if delay is not None:
                with patch.dict("os.environ", {"SW_DOC_INDEX_WRITE_DELAY_SECONDS": delay}):
                    out = provision_doc_run(repo, topic=topic, tier="Standard", run_id=run_id)
            else:
                out = provision_doc_run(repo, topic=topic, tier="Standard", run_id=run_id)
            if out.get("verdict") != "pass":
                errors.append(f"{run_id}: {out.get('error')}")
            else:
                results[run_id] = topic
        except Exception as exc:  # pragma: no cover - defensive
            errors.append(f"{run_id}: {exc}")

    threads = [
        threading.Thread(target=worker, args=("topic-alpha", "doc-alpha"), daemon=True),
        threading.Thread(target=worker, args=("topic-beta", "doc-beta"), daemon=True),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=15)
    return results, errors


def test_concurrent_different_topic_index_updates_preserve_both_entries(repo: Path) -> None:
    results, errors = _provision_pair(repo)
    assert not errors, errors
    assert set(results) == {"doc-alpha", "doc-beta"}
    assert _index_run_ids(repo) == {"doc-alpha", "doc-beta"}


def test_concurrent_different_topic_index_updates_with_write_delay(repo: Path) -> None:
    results, errors = _provision_pair(repo, delay="0.05")
    assert not errors, errors
    assert set(results) == {"doc-alpha", "doc-beta"}
    assert _index_run_ids(repo) == {"doc-alpha", "doc-beta"}


def test_update_doc_index_stamps_revision(repo: Path) -> None:
    state = initial_doc_state(
        run_id="doc-rev",
        topic="revision-topic",
        tier="Standard",
        lock_key_digest="digest",
    )
    save_doc_state(repo, state)
    index = json.loads(doc_index_path(repo).read_text(encoding="utf-8"))
    assert index.get("revision") == 1
    assert index.get("updatedAt")

    state["stage"] = "prd"
    save_doc_state(repo, state)
    index = json.loads(doc_index_path(repo).read_text(encoding="utf-8"))
    assert index.get("revision") == 2


def test_direct_index_updates_under_lock_preserve_both_entries(repo: Path) -> None:
    errors: list[str] = []
    barrier = threading.Barrier(2)

    def worker(run_id: str, topic: str) -> None:
        try:
            barrier.wait(timeout=5)
            state = initial_doc_state(
                run_id=run_id,
                topic=topic,
                tier="Standard",
                lock_key_digest="digest",
            )
            with patch.dict("os.environ", {"SW_DOC_INDEX_WRITE_DELAY_SECONDS": "0.05"}):
                update_doc_index(repo, state)
        except Exception as exc:  # pragma: no cover - defensive
            errors.append(str(exc))

    threads = [
        threading.Thread(target=worker, args=("doc-one", "topic-one"), daemon=True),
        threading.Thread(target=worker, args=("doc-two", "topic-two"), daemon=True),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=15)
    assert not errors, errors
    assert _index_run_ids(repo) == {"doc-one", "doc-two"}
