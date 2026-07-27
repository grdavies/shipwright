"""Legacy adoption atomicity and refusal fixtures (PRD 081 R18, R21)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT_DIR = Path(__file__).resolve().parents[2]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from wave_json_io import read_json, write_json
from wave_run_adopt import adopt_legacy_run, locate_legacy_source, preview_adoption, read_legacy_global_plan_once
from wave_run_paths import global_plan_path, plan_path, state_path
from wave_run_plan import compute_plan_hash, persist_plan, ensure_run_id


def _init_repo(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True)


def _sample_plan(slug: str = "alpha") -> dict:
    return {
        "mode": "phase",
        "source_task_list": f"docs/prds/081-{slug}/tasks-081-{slug}.md",
        "target": {"branch": f"feat/{slug}", "slug": slug},
        "items": [{"id": "1", "slug": "phase-one"}],
        "waves": [["1"]],
        "edges": [],
    }


def _legacy_fixture(tmp_path: Path, slug: str = "alpha") -> dict:
    plan = _sample_plan(slug)
    plan_hash = compute_plan_hash(plan)
    state = {
        "verdict": "running",
        "source_task_list": plan["source_task_list"],
        "target": plan["target"],
        "phases": {"1": {"status": "pending"}},
        "nextAction": "provision-phase",
        "planHash": plan_hash,
        "runId": f"deliver-{slug}",
    }
    scoped = tmp_path / ".cursor" / f"sw-deliver-state.{slug}.json"
    scoped.parent.mkdir(parents=True, exist_ok=True)
    write_json(scoped, state)
    write_json(global_plan_path(tmp_path), plan)
    return {"state": state, "scoped": scoped, "plan": plan, "planHash": plan_hash}


def test_adoption_preview_reports_before_mutation(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    fixture = _legacy_fixture(tmp_path)
    source = locate_legacy_source(tmp_path, slug="alpha")
    assert source is not None
    preview = preview_adoption(tmp_path, source)
    assert preview["globalPlanPresent"] is True
    assert preview["willAdopt"]["state"].endswith(f"deliver-alpha/state.json")
    assert fixture["scoped"].read_text(encoding="utf-8") == json.dumps(fixture["state"], indent=2) + "\n"


def test_adoption_atomic_and_records_hash(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    fixture = _legacy_fixture(tmp_path)
    source = locate_legacy_source(tmp_path, slug="alpha")
    assert source is not None
    result = adopt_legacy_run(tmp_path, source)
    run_id = str(result["runId"])
    adopted_state = read_json(state_path(tmp_path, run_id))
    assert adopted_state.get("legacyAdopted") is True
    assert adopted_state.get("adoptedPlanHash") == fixture["planHash"]
    assert plan_path(tmp_path, run_id).is_file()
    breadcrumb = read_json(fixture["scoped"])
    assert breadcrumb.get("adopted") is True


def test_adoption_interrupted_before_rename_leaves_legacy_intact(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _init_repo(tmp_path)
    fixture = _legacy_fixture(tmp_path)
    source = locate_legacy_source(tmp_path, slug="alpha")
    assert source is not None
    original = fixture["scoped"].read_text(encoding="utf-8")

    def boom(path, data):  # type: ignore[no-untyped-def]
        if str(path).endswith(".adopt-tmp"):
            write_json(path, data)
            raise OSError("simulated crash before rename")
        return write_json(path, data)

    import wave_run_adopt as adopt_mod

    monkeypatch.setattr(adopt_mod, "write_json", boom)
    with pytest.raises(OSError):
        adopt_legacy_run(tmp_path, source)
    assert fixture["scoped"].read_text(encoding="utf-8") == original
    assert not state_path(tmp_path, "deliver-alpha").exists()


def test_adoption_refused_when_run_scoped_state_exists(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    fixture = _legacy_fixture(tmp_path)
    source = locate_legacy_source(tmp_path, slug="alpha")
    assert source is not None
    adopt_legacy_run(tmp_path, source)
    with pytest.raises(SystemExit):
        adopt_legacy_run(tmp_path, source)


def test_plan_hash_mismatch_refuses_adoption(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    fixture = _legacy_fixture(tmp_path)
    tampered = {**fixture["plan"], "tampered": True}
    write_json(global_plan_path(tmp_path), tampered)
    source = locate_legacy_source(tmp_path, slug="alpha")
    assert source is not None
    with pytest.raises(SystemExit):
        adopt_legacy_run(tmp_path, source)


def test_legacy_global_plan_read_once_helper(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    fixture = _legacy_fixture(tmp_path)
    loaded = read_legacy_global_plan_once(tmp_path)
    assert loaded["target"]["slug"] == "alpha"
    assert compute_plan_hash(loaded) == fixture["planHash"]


def test_already_adopted_run_refused_on_second_adopt(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    _legacy_fixture(tmp_path)
    source = locate_legacy_source(tmp_path, slug="alpha")
    assert source is not None
    adopt_legacy_run(tmp_path, source)
    assert locate_legacy_source(tmp_path, slug="alpha") is None
