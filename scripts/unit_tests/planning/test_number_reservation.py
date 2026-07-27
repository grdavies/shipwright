"""PRD 081 R16 — concurrent planning-number reservation fixtures."""

from __future__ import annotations

import json
import subprocess
import sys
import threading
from pathlib import Path
from unittest.mock import patch

import pytest

scripts = Path(__file__).resolve().parents[2]
if str(scripts) not in sys.path:
    sys.path.insert(0, str(scripts))

from planning_reserve import (
    active_reserved_numbers,
    complete_reservation,
    reclaim_stale_reservation,
    reserve_number,
    reserve_number_file_store,
    reservation_lock_path,
)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    (root / ".cursor").mkdir(parents=True, exist_ok=True)
    (root / "docs" / "prds" / "080-existing").mkdir(parents=True)
    return root


@pytest.fixture(autouse=True)
def anchor_repo(repo: Path):
    with patch("planning_reserve.canonical_repo_root", return_value=repo):
        with patch("wave_state.canonical_repo_root", return_value=repo):
            yield


def test_concurrent_file_store_reservations_are_distinct(repo: Path) -> None:
    outputs: list[dict] = []
    lock = threading.Lock()

    def worker(unit_id: str, slug: str, holder_id: str) -> None:
        result = reserve_number_file_store(
            repo,
            unit_id=unit_id,
            slug=slug,
            holder_id=holder_id,
        )
        with lock:
            outputs.append(result)

    threads = [
        threading.Thread(target=worker, args=(f"unit-{index}", f"slug-{index}", f"holder-{index}"))
        for index in range(2)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert len(outputs) == 2
    numbers = [item["number"] for item in outputs if item["verdict"] == "pass"]
    assert len(numbers) == 2
    assert len(set(numbers)) == 2
    assert active_reserved_numbers(repo) == set(numbers)


def test_crashed_reservation_is_reclaimable(repo: Path) -> None:
    first = reserve_number_file_store(
        repo,
        unit_id="crashed-unit",
        slug="crashed-slug",
        holder_id="holder-a",
    )
    assert first["verdict"] == "pass"
    lock_path = Path(first["lockPath"])
    meta = json.loads(lock_path.read_text(encoding="utf-8"))
    meta["heartbeatAt"] = "2000-01-01T00:00:00Z"
    meta["pid"] = 999999
    lock_path.write_text(json.dumps(meta), encoding="utf-8")

    assert reclaim_stale_reservation(lock_path) is True
    assert not lock_path.exists()

    second = reserve_number_file_store(
        repo,
        unit_id="replacement-unit",
        slug="replacement-slug",
        holder_id="holder-b",
    )
    assert second["verdict"] == "pass"
    assert second["number"] == first["number"]


def test_no_duplicate_numbers_across_completed_and_active(repo: Path) -> None:
    first = reserve_number_file_store(
        repo,
        unit_id="alpha-unit",
        slug="alpha",
        holder_id="holder-alpha",
    )
    second = reserve_number_file_store(
        repo,
        unit_id="beta-unit",
        slug="beta",
        holder_id="holder-beta",
    )
    assert first["number"] != second["number"]
    active = active_reserved_numbers(repo)
    assert len(active) == 2
    assert first["number"] in active
    assert second["number"] in active
    complete_reservation(repo, unit_id="alpha-unit")
    active_after = active_reserved_numbers(repo)
    assert first["number"] not in active_after
    assert second["number"] in active_after


def _issue_store_cfg(project_key: str) -> dict:
    return {
        "version": 1,
        "planning": {
            "store": {
                "backend": "issue-store",
                "issuesProvider": "github-issues",
                "projectKey": project_key,
                "hierarchy": {"epicSubIssues": True},
            }
        },
        "host": {"provider": "github"},
    }


def test_issue_store_reservation_mints_with_guard(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from issues_lib import FixtureIssuesStore
    from planning_canonical import compose_issue_body

    subprocess.run(["git", "init"], cwd=repo, capture_output=True, check=True)
    monkeypatch.setenv("SW_ISSUES_FIXTURE", "1")
    project_key = "reserve-081"
    cfg = _issue_store_cfg(project_key)
    (repo / ".cursor/workflow.config.json").write_text(json.dumps(cfg), encoding="utf-8")
    store = FixtureIssuesStore(repo / ".cursor/hooks/state/issue-store-fixture.json")
    uid = "082-prd-existing"
    body = compose_issue_body(
        project_key,
        "prd",
        uid,
        f"---\nid: {uid}\ntype: prd\n---\n# Existing\n",
    )
    rec = store.create(
        title=uid,
        body=body,
        labels=["sw:prd", f"sw:unit:{uid}"],
        project_key=project_key,
        artifact_type="prd",
        unit_id=uid,
    )
    (repo / ".cursor/hooks/state/issue-store-unit-index.json").write_text(
        json.dumps({"version": 1, "units": {f"{project_key}:{uid}": rec.id}}),
        encoding="utf-8",
    )

    result = reserve_number(
        repo,
        unit_id="stable-alpha",
        slug="alpha-feature",
        holder_id="doc-run:test",
        cfg=cfg,
    )
    assert result["verdict"] == "pass"
    assert result["backend"] == "issue-store"
    assert result["number"] == 83
    lock_path = reservation_lock_path(repo, int(result["number"]), "stable-alpha")
    assert lock_path.is_file()
