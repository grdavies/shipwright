"""PRD 070 phase 7 — CI close-out driver tests (no-op, N-per-wave, surfacing, SLO)."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

import closeout_ci as ci
import deliver_closeout as dc

SHA = "a" * 40
HEAD = "b" * 40
UNIT_A = "prd-070-automated-delivery-closeout"
UNIT_B = "prd-070-other-delivery"


def _mapping(pr_number: int, *, unit: str, slug: str) -> dict:
    return {
        "prNumber": str(pr_number),
        "prdUnitId": unit,
        "deliverySlug": slug,
        "targetBranch": f"feat/{slug}",
        "headSha": HEAD,
        "runSlug": slug,
    }


def _wave_event(*messages: str) -> dict:
    commits = [{"message": msg} for msg in messages]
    return {
        "ref": "refs/heads/main",
        "after": SHA,
        "head_commit": {"id": SHA, "message": messages[-1] if messages else ""},
        "commits": commits,
    }


def test_non_delivery_merge_noops(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    event = _wave_event("docs: update readme")
    event_path = tmp_path / "event.json"
    event_path.write_text(json.dumps(event), encoding="utf-8")
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event_path))

    result = ci.run_ci_closeout(tmp_path, mode="observe")
    assert result["verdict"] == "skipped"
    assert result["reason"] == "no-delivery-mapping"


def test_batched_wave_closes_all_mapped_units(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    dc.record_pr_delivery_mapping(tmp_path, _mapping(10, unit=UNIT_A, slug="automated-delivery-closeout"))
    dc.record_pr_delivery_mapping(tmp_path, _mapping(11, unit=UNIT_B, slug="other-delivery"))
    event = _wave_event(
        "Merge pull request #10 from feat/a",
        "Merge pull request #11 from feat/b",
    )
    event_path = tmp_path / "event.json"
    event_path.write_text(json.dumps(event), encoding="utf-8")
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event_path))
    monkeypatch.setenv("SW_PLANNING_ISSUES_TOKEN", "test-token")

    calls: list[str] = []

    def fake_run_closeout(root, *, prd_unit_id, merge_sha, pr_number=None, dry_run=False, state=None):
        calls.append(prd_unit_id)
        return {"verdict": "ready", "action": "run-closeout", "dryRun": dry_run}

    monkeypatch.setattr(ci, "run_closeout", fake_run_closeout)
    result = ci.run_ci_closeout(tmp_path, mode="mutate")
    assert result["verdict"] == "ready"
    assert result["deliveryCount"] == 2
    assert sorted(calls) == sorted([UNIT_A, UNIT_B])


def test_auth_failure_surfaces_resume_command(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    dc.record_pr_delivery_mapping(tmp_path, _mapping(42, unit=UNIT_A, slug="automated-delivery-closeout"))
    event = _wave_event("Merge pull request #42 from feat/x")
    event_path = tmp_path / "event.json"
    event_path.write_text(json.dumps(event), encoding="utf-8")
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event_path))
    monkeypatch.delenv("SW_PLANNING_ISSUES_TOKEN", raising=False)

    surfaced: list[dict] = []

    def capture_surface(**kwargs):
        surfaced.append(kwargs)
        return {"verdict": "surfaced", "channels": ["test"]}

    result = ci.run_ci_closeout(tmp_path, mode="mutate", surface_hook=capture_surface)
    assert result["verdict"] == "fail"
    assert result["error"] == "planning-token-missing"
    assert "resumeCommand" in result
    assert surfaced
    assert surfaced[0]["resume_command"] == result["resumeCommand"]


def test_hostile_pr_title_cannot_alter_driver_calls(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    dc.record_pr_delivery_mapping(tmp_path, _mapping(55, unit=UNIT_A, slug="automated-delivery-closeout"))
    hostile = "Merge pull request #55 from evil; rm -rf / (#55)"
    event = _wave_event(hostile)
    event_path = tmp_path / "event.json"
    event_path.write_text(json.dumps(event), encoding="utf-8")
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event_path))
    monkeypatch.setenv("SW_PLANNING_ISSUES_TOKEN", "test-token")

    calls: list[dict] = []

    def fake_run_closeout(root, *, prd_unit_id, merge_sha, pr_number=None, dry_run=False, state=None):
        calls.append({"prd_unit_id": prd_unit_id, "pr_number": pr_number, "merge_sha": merge_sha})
        return {"verdict": "ready", "action": "run-closeout"}

    monkeypatch.setattr(ci, "run_closeout", fake_run_closeout)
    result = ci.run_ci_closeout(tmp_path, mode="mutate")
    assert result["verdict"] == "ready"
    assert calls == [{"prd_unit_id": UNIT_A, "pr_number": 55, "merge_sha": SHA}]


def test_slo_breach_surfaces_owner(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    dc.record_pr_delivery_mapping(tmp_path, _mapping(77, unit=UNIT_A, slug="automated-delivery-closeout"))
    event = _wave_event("Merge pull request #77")
    event_path = tmp_path / "event.json"
    event_path.write_text(json.dumps(event), encoding="utf-8")
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event_path))
    monkeypatch.setenv("SW_PLANNING_ISSUES_TOKEN", "test-token")

    clock = {"t": 0.0}

    def fake_clock():
        clock["t"] += 400.0
        return clock["t"]

    monkeypatch.setattr(ci, "run_closeout", lambda *a, **k: {"verdict": "ready"})
    cfg_path = tmp_path / ".cursor"
    cfg_path.mkdir(parents=True, exist_ok=True)
    (cfg_path / "workflow.config.json").write_text(
        json.dumps(
            {
                "defaultBaseBranch": "main",
                "deliver": {"closeout": {"latencySlo": {"maxSeconds": 1, "owner": "closeout-oncall"}}},
                "planning": {"store": {"issues": {"tokenEnv": "SW_PLANNING_ISSUES_TOKEN"}}},
            }
        ),
        encoding="utf-8",
    )

    surfaced: list[dict] = []

    def capture_surface(**kwargs):
        surfaced.append(kwargs)
        return {"verdict": "surfaced", "channels": ["test"]}

    result = ci.run_ci_closeout(tmp_path, mode="mutate", surface_hook=capture_surface, monotonic=fake_clock)
    assert result["verdict"] == "fail"
    assert result["error"] == "closeout-latency-slo-breach"
    assert result["slo"]["withinSlo"] is False
    assert surfaced[0]["slo"]["owner"] == "closeout-oncall"
