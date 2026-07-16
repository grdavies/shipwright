"""PRD 070 phase 8 — revert detection and provenance-scoped reopen tests."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

import deliver_closeout as dc
from issues_lib import FixtureIssuesStore
from planning_canonical import compose_issue_body, status_label

SHA_A = "a" * 40
SHA_B = "b" * 40
SHA_MAIN = "c" * 40
UNIT_A = "prd-070-automated-delivery-closeout"
UNIT_B = "prd-070-other-delivery"
GAP_OWN = "gap-070-owned"
GAP_REUSED = "gap-070-reused"


def _init_repo(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=tmp_path, check=True)
    (tmp_path / "README.md").write_text("base\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=tmp_path, check=True)


def _issue_store_cfg() -> dict:
    return {
        "version": 1,
        "defaultBaseBranch": "main",
        "planning": {
            "store": {
                "backend": "issue-store",
                "issuesProvider": "github-issues",
                "projectKey": "closeout-070",
                "hierarchy": {"epicSubIssues": True},
            }
        },
        "host": {"provider": "github"},
    }


def _seed_issue(
    store: FixtureIssuesStore,
    *,
    project_key: str,
    artifact_type: str,
    unit_id: str,
    closed: bool = False,
):
    body = compose_issue_body(
        project_key,
        artifact_type,
        unit_id,
        f"---\nid: {unit_id}\ntype: {artifact_type}\nstatus: {'complete' if closed else 'open'}\n---\n# body\n",
    )
    labels = [f"sw:{artifact_type}", f"sw:unit:{unit_id}"]
    if closed:
        labels.append(status_label("complete"))
    rec = store.create(
        title=unit_id,
        body=body,
        labels=labels,
        project_key=project_key,
        artifact_type=artifact_type,
        unit_id=unit_id,
    )
    if closed:
        store.update(rec.id, state="closed")
    return rec


def _write_index(root: Path, project_key: str, mapping: dict[str, str]) -> None:
    (root / ".cursor/hooks/state/issue-store-unit-index.json").write_text(
        json.dumps({"version": 1, "units": {f"{project_key}:{k}": v for k, v in mapping.items()}}),
        encoding="utf-8",
    )


def _manifest(*, prd_unit: str, merge_sha: str, units: list[dict], written_at: str) -> dict:
    return {
        "version": 1,
        "prdUnitId": prd_unit,
        "mergeSha": merge_sha,
        "writtenAt": written_at,
        "deliverySet": units,
        "unitCount": len(units),
    }


def test_detect_revert_from_merge_pr_message() -> None:
    event = {"head_commit": {"message": 'Revert "Merge pull request #42 from feat/x"'}}
    result = dc.detect_revert_from_event(event)
    assert result["recognized"] is True
    assert result["prNumbers"] == [42]
    assert "git-revert-merge-pr" in result["taxonomyIds"]
    assert result["limits"]


def test_reverted_terminal_merge_reopens_delivery_set(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SW_ISSUES_FIXTURE", "1")
    root = tmp_path
    _init_repo(root)
    cfg = _issue_store_cfg()
    (root / ".cursor").mkdir(parents=True, exist_ok=True)
    (root / ".cursor/hooks/state").mkdir(parents=True, exist_ok=True)
    (root / ".cursor/workflow.config.json").write_text(json.dumps(cfg), encoding="utf-8")
    project_key = "closeout-070"
    store = FixtureIssuesStore(root / ".cursor/hooks/state/issue-store-fixture.json")
    prd_rec = _seed_issue(store, project_key=project_key, artifact_type="prd", unit_id=UNIT_A, closed=True)
    gap_rec = _seed_issue(store, project_key=project_key, artifact_type="gap", unit_id=GAP_OWN, closed=True)
    _write_index(root, project_key, {UNIT_A: prd_rec.id, GAP_OWN: gap_rec.id})

    manifest = _manifest(
        prd_unit=UNIT_A,
        merge_sha=SHA_A,
        written_at="2026-07-16T10:00:00Z",
        units=[
            {
                "unitId": UNIT_A,
                "artifactType": "prd",
                "priorState": "open",
                "closureProvenance": {"mergeSha": SHA_A, "prdUnitId": UNIT_A},
            },
            {
                "unitId": GAP_OWN,
                "artifactType": "gap",
                "priorState": "open",
                "closureProvenance": {"mergeSha": SHA_A, "prdUnitId": UNIT_A},
            },
        ],
    )
    dc.persist_closure_manifest(root, manifest)
    dc.write_close_marker(root, UNIT_A, SHA_A, audit={"verdict": "ready"})
    dc.record_pr_delivery_mapping(
        root,
        {
            "prNumber": "42",
            "prdUnitId": UNIT_A,
            "deliverySlug": "automated-delivery-closeout",
            "targetBranch": "feat/automated-delivery-closeout",
            "headSha": SHA_B,
            "runSlug": "automated-delivery-closeout",
        },
    )

    monkeypatch.setattr(dc, "merge_sha_on_default", lambda *_a, **_k: False)

    result = dc.handle_delivery_revert(root, manifest=manifest)
    assert result["verdict"] == "ready"
    reopened_ids = {item["unitId"] for item in result["reopen"]["reopened"]}
    assert reopened_ids == {UNIT_A, GAP_OWN}
    assert dc.load_close_marker(root, UNIT_A) is None


def test_unrelated_reused_unit_untouched_on_revert(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SW_ISSUES_FIXTURE", "1")
    root = tmp_path
    _init_repo(root)
    cfg = _issue_store_cfg()
    (root / ".cursor").mkdir(parents=True, exist_ok=True)
    (root / ".cursor/hooks/state").mkdir(parents=True, exist_ok=True)
    (root / ".cursor/workflow.config.json").write_text(json.dumps(cfg), encoding="utf-8")
    project_key = "closeout-070"
    store = FixtureIssuesStore(root / ".cursor/hooks/state/issue-store-fixture.json")
    prd_rec = _seed_issue(store, project_key=project_key, artifact_type="prd", unit_id=UNIT_A, closed=True)
    gap_rec = _seed_issue(store, project_key=project_key, artifact_type="gap", unit_id=GAP_REUSED, closed=True)
    _write_index(root, project_key, {UNIT_A: prd_rec.id, GAP_REUSED: gap_rec.id})

    manifest_a = _manifest(
        prd_unit=UNIT_A,
        merge_sha=SHA_A,
        written_at="2026-07-16T10:00:00Z",
        units=[
            {"unitId": UNIT_A, "artifactType": "prd", "priorState": "open", "closureProvenance": {"mergeSha": SHA_A, "prdUnitId": UNIT_A}},
        ],
    )
    manifest_b = _manifest(
        prd_unit=UNIT_B,
        merge_sha=SHA_B,
        written_at="2026-07-16T12:00:00Z",
        units=[
            {"unitId": GAP_REUSED, "artifactType": "gap", "priorState": "open", "closureProvenance": {"mergeSha": SHA_B, "prdUnitId": UNIT_B}},
        ],
    )
    dc.persist_closure_manifest(root, manifest_a)
    dc.persist_closure_manifest(root, manifest_b)
    dc.write_close_marker(root, UNIT_A, SHA_A, audit={"verdict": "ready"})

    def sha_on_default(_root, merge_sha, *, cfg=None):
        return merge_sha == SHA_B

    monkeypatch.setattr(dc, "merge_sha_on_default", sha_on_default)

    result = dc.handle_delivery_revert(root, manifest=manifest_a)
    reopened_ids = {item["unitId"] for item in result["reopen"]["reopened"]}
    assert UNIT_A in reopened_ids
    skipped = {item["unitId"] for item in result["reopen"]["skipped"]}
    assert GAP_REUSED not in reopened_ids


def test_missed_revert_reconciles_on_next_entry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SW_ISSUES_FIXTURE", "1")
    root = tmp_path
    _init_repo(root)
    cfg = _issue_store_cfg()
    (root / ".cursor").mkdir(parents=True, exist_ok=True)
    (root / ".cursor/hooks/state").mkdir(parents=True, exist_ok=True)
    (root / ".cursor/workflow.config.json").write_text(json.dumps(cfg), encoding="utf-8")
    project_key = "closeout-070"
    store = FixtureIssuesStore(root / ".cursor/hooks/state/issue-store-fixture.json")
    prd_rec = _seed_issue(store, project_key=project_key, artifact_type="prd", unit_id=UNIT_A, closed=True)
    _write_index(root, project_key, {UNIT_A: prd_rec.id})

    manifest = _manifest(
        prd_unit=UNIT_A,
        merge_sha=SHA_A,
        written_at="2026-07-16T10:00:00Z",
        units=[
            {"unitId": UNIT_A, "artifactType": "prd", "priorState": "open", "closureProvenance": {"mergeSha": SHA_A, "prdUnitId": UNIT_A}},
        ],
    )
    dc.persist_closure_manifest(root, manifest)
    dc.write_close_marker(root, UNIT_A, SHA_A, audit={"verdict": "ready"})
    monkeypatch.setattr(dc, "merge_sha_on_default", lambda *_a, **_k: False)

    result = dc.reconcile_missed_reverts(root, event={})
    assert result["verdict"] == "ready"
    assert result["handled"]
    assert result["handled"][0]["source"] == "structural-missed-revert"
