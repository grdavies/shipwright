"""PRD 066 phase 12 — gap-079 absorb linkage record + verify (R22)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

scripts = Path(__file__).resolve().parents[2]
if str(scripts) not in sys.path:
    sys.path.insert(0, str(scripts))

import planning_gap_capture as pgc
import planning_store as ps
from issues_lib import FixtureIssuesStore
from planning_canonical import compose_issue_body


def _fixture_repo() -> tuple[Path, dict]:
    os.environ["SW_ISSUES_FIXTURE"] = "1"
    root = Path(tempfile.mkdtemp())
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    (root / ".cursor").mkdir(parents=True, exist_ok=True)
    fixture = root / ".cursor/hooks/state/issue-store-fixture.json"
    store = FixtureIssuesStore(fixture)
    project_key = "fixture-066"
    gap_uid = pgc.GAP_079_UNIT_ID
    prd_uid = pgc.PRD_066_UNIT_ID
    gap_body = compose_issue_body(
        project_key,
        "gap",
        gap_uid,
        (
            f"---\n"
            f"id: {gap_uid}\n"
            f"type: gap\n"
            f"status: open\n"
            f"visibility: public\n"
            f"---\n"
            f"# Gap 079\n"
        ),
    )
    prd_body = compose_issue_body(
        project_key,
        "prd",
        prd_uid,
        (
            f"---\n"
            f"id: {prd_uid}\n"
            f"type: prd\n"
            f"status: draft\n"
            f"frozen: true\n"
            f"visibility: public\n"
            f"---\n"
            f"# PRD 066\n"
        ),
    )
    gap_rec = store.create(
        title="Gap 079",
        body=gap_body,
        labels=["sw:gap", f"sw:unit:{gap_uid}"],
        project_key=project_key,
        artifact_type="gap",
        unit_id=gap_uid,
    )
    prd_rec = store.create(
        title="PRD 066",
        body=prd_body,
        labels=["sw:prd", f"sw:unit:{prd_uid}"],
        project_key=project_key,
        artifact_type="prd",
        unit_id=prd_uid,
    )
    cfg = {
        "version": 1,
        "host": {"provider": "github"},
        "planning": {
            "store": {
                "backend": "issue-store",
                "issuesProvider": "github-issues",
                "projectKey": project_key,
            }
        },
    }
    (root / ".cursor/workflow.config.json").write_text(
        json.dumps(cfg), encoding="utf-8"
    )
    (root / ".cursor/hooks/state/issue-store-unit-index.json").write_text(
        json.dumps(
            {
                "version": 1,
                "units": {
                    f"{project_key}:{gap_uid}": gap_rec.id,
                    f"{project_key}:{prd_uid}": prd_rec.id,
                },
            }
        ),
        encoding="utf-8",
    )
    return root, cfg


def test_record_and_verify_absorb_linkage_066() -> None:
    """R22 — record absorb linkage then verify via store get/doctor."""
    root, cfg = _fixture_repo()
    record = pgc.record_absorb_linkage_066(root, dry_run=False)
    assert record["verdict"] == "ok", record
    assert record["gapUnitId"] == pgc.GAP_079_UNIT_ID

    verify = ps.verify_absorb_linkage_066(root, cfg)
    assert verify["verdict"] == "ok", verify
    assert verify["checks"]["prdAbsorbsGap"] is True
    assert verify["checks"]["gapAbsorbedByPrd"] is True
    assert verify["checks"]["planningIssueRef"] is True
    assert verify["checks"]["issueStoreScheduleLabel"] is True

    doctor = ps.doctor_absorb_linkage_066(root, cfg)
    assert doctor["verdict"] == "pass", doctor


def test_record_absorb_linkage_cli() -> None:
    """CLI record-absorb-linkage returns ok JSON."""
    root, _cfg = _fixture_repo()
    proc = subprocess.run(
        [
            sys.executable,
            str(scripts / "planning_gap_capture.py"),
            str(root),
            "record-absorb-linkage",
        ],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "SW_ISSUES_FIXTURE": "1"},
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["verdict"] == "ok", payload


def test_verify_absorb_linkage_cli_fails_before_record() -> None:
    """Verify fails closed when absorb linkage not yet recorded."""
    root, _cfg = _fixture_repo()
    proc = subprocess.run(
        [
            sys.executable,
            str(scripts / "planning_store.py"),
            "--root",
            str(root),
            "verify-absorb-linkage-066",
        ],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "SW_ISSUES_FIXTURE": "1"},
    )
    assert proc.returncode != 0
    payload = json.loads(proc.stdout)
    assert payload["verdict"] == "fail"


def test_record_absorb_linkage_idempotent() -> None:
    """Second record is a no-op on already-linked units."""
    root, cfg = _fixture_repo()
    first = pgc.record_absorb_linkage_066(root, dry_run=False)
    second = pgc.record_absorb_linkage_066(root, dry_run=False)
    assert first["verdict"] == "ok"
    assert second["verdict"] == "ok"
    assert ps.verify_absorb_linkage_066(root, cfg)["verdict"] == "ok"
