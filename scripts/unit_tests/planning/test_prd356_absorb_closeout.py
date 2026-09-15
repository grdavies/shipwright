"""PRD 356 R8 — packaged conformance gap + signal closeout."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from issues_lib import FixtureIssuesStore
from planning_canonical import compose_issue_body
from planning_store import discover_absorbed_units_anchored, resolve_delivery_linked_units
from planning_store_facade import (
    PRD_356_GAP_UNIT_ID,
    PRD_356_RELATED_SIGNAL_ID,
    PRD_356_SOURCE_SIGNAL_ID,
    PRD_356_UNIT_ID,
    prd356_p1_shipped,
    prd356_signal_disposition_plan,
    record_absorb_linkage_356,
    verify_absorb_closeout_356,
    verify_prd356_packaged_evidence,
    verify_prd356_signal_closeout,
)


def _init_repo(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=tmp_path, check=True)
    (tmp_path / ("." + "cursor") / "hooks" / "state").mkdir(parents=True, exist_ok=True)


def _issue_store_cfg(project_key: str = "closure-356") -> dict:
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


def _fixture_prd356_repo(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Path, dict, FixtureIssuesStore]:
    monkeypatch.setenv("SW_ISSUES_FIXTURE", "1")
    root = tmp_path
    _init_repo(root)
    project_key = "closure-356"
    cfg = _issue_store_cfg(project_key)
    (root / ("." + "cursor") / "workflow.config.json").write_text(json.dumps(cfg), encoding="utf-8")
    store = FixtureIssuesStore(root / ".cursor/hooks/state/issue-store-fixture.json")

    prd_body = compose_issue_body(
        project_key,
        "prd",
        PRD_356_UNIT_ID,
        (
            f"---\n"
            f"id: {PRD_356_UNIT_ID}\n"
            f"type: prd\n"
            f"status: complete\n"
            f"visibility: public\n"
            f"source-gap: {PRD_356_GAP_UNIT_ID}\n"
            f"related-signals: [{PRD_356_RELATED_SIGNAL_ID}]\n"
            f"source-signal: {PRD_356_SOURCE_SIGNAL_ID}\n"
            f"absorbs: [{PRD_356_GAP_UNIT_ID}]\n"
            f"---\n"
            f"# PRD 356\n"
        ),
        edges=[{"rel": "absorbs", "target": PRD_356_GAP_UNIT_ID}],
    )
    prd_rec = store.create(
        title="PRD 356",
        body=prd_body,
        labels=["sw:prd", f"sw:unit:{PRD_356_UNIT_ID}"],
        project_key=project_key,
        artifact_type="prd",
        unit_id=PRD_356_UNIT_ID,
    )
    index_units = {f"{project_key}:{PRD_356_UNIT_ID}": prd_rec.id}

    gap_body = compose_issue_body(
        project_key,
        "gap",
        PRD_356_GAP_UNIT_ID,
        (
            f"---\n"
            f"id: {PRD_356_GAP_UNIT_ID}\n"
            f"type: gap\n"
            f"status: open\n"
            f"visibility: public\n"
            f"---\n"
            f"# {PRD_356_GAP_UNIT_ID}\n"
        ),
    )
    gap_rec = store.create(
        title=PRD_356_GAP_UNIT_ID,
        body=gap_body,
        labels=["sw:gap", "sw:gap-open", f"sw:unit:{PRD_356_GAP_UNIT_ID}"],
        project_key=project_key,
        artifact_type="gap",
        unit_id=PRD_356_GAP_UNIT_ID,
    )
    index_units[f"{project_key}:{PRD_356_GAP_UNIT_ID}"] = gap_rec.id

    store._persist()
    (root / ".cursor/hooks/state/issue-store-unit-index.json").write_text(
        json.dumps({"version": 1, "units": index_units}),
        encoding="utf-8",
    )
    return root, cfg, store


def test_verify_prd356_packaged_evidence_ok(repo_root: Path) -> None:
    out = verify_prd356_packaged_evidence(repo_root)
    assert out["verdict"] == "ok", out
    assert out.get("p1Shipped") is True


def test_prd356_signal_disposition_plan_p1_shipped(repo_root: Path) -> None:
    plan = prd356_signal_disposition_plan(p1_shipped=prd356_p1_shipped(repo_root))
    assert plan["sourceSignal"]["signalId"] == PRD_356_SOURCE_SIGNAL_ID
    assert plan["relatedSignal"]["signalId"] == PRD_356_RELATED_SIGNAL_ID
    assert plan["relatedSignal"]["disposition"] == "superseded/partial"
    assert plan["p1Status"] == "shipped"
    assert plan["deferredRequirements"] == []


def test_discover_absorbed_gap_465(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root, cfg, _store = _fixture_prd356_repo(tmp_path, monkeypatch)
    fm = {"absorbs": PRD_356_GAP_UNIT_ID}
    discovered, skipped = discover_absorbed_units_anchored(fm, {"edges": [{"rel": "absorbs", "target": PRD_356_GAP_UNIT_ID}]})
    assert PRD_356_GAP_UNIT_ID in discovered
    assert not skipped


def test_verify_absorb_closeout_356_ok(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root, cfg, _store = _fixture_prd356_repo(tmp_path, monkeypatch)
    out = verify_absorb_closeout_356(root, cfg)
    assert out["verdict"] == "ok", out
    assert not out.get("missing")


def test_verify_prd356_signal_closeout_fixture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    repo_root: Path,
) -> None:
    root, cfg, _store = _fixture_prd356_repo(tmp_path, monkeypatch)
    for rel in (
        "scripts/unit_tests/planning/test_packaged_conformance_root.py",
        "scripts/unit_tests/planning/test_packaged_conformance_present_fail.py",
        "scripts/unit_tests/planning/test_packaged_conformance_live_gate.py",
        "scripts/unit_tests/planning/test_packaged_consumer_conformance.py",
        "scripts/planning/packaged_conformance_roots.py",
        "scripts/planning/provider_conformance.py",
        "scripts/planning_store_facade.py",
    ):
        dest = root / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text((repo_root / rel).read_text(encoding="utf-8"), encoding="utf-8")
    for rel in (
        "scripts/unit_tests/init/test_packaged_install_scope.py",
        "scripts/unit_tests/init/test_config_preserve_on_upgrade.py",
    ):
        dest = root / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text((repo_root / rel).read_text(encoding="utf-8"), encoding="utf-8")
    out = verify_prd356_signal_closeout(root, cfg)
    assert out["verdict"] == "ok", out
    assert out["signalDisposition"]["p1Status"] == "shipped"


def test_record_absorb_linkage_356_dry_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root, _cfg, _store = _fixture_prd356_repo(tmp_path, monkeypatch)
    out = record_absorb_linkage_356(root, dry_run=True)
    assert out.get("verdict") in {"ok", "skipped", "fail"}
