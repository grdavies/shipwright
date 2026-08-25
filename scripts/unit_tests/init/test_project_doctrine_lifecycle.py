"""PRD 330 R8, R11, R12, R14 — repo-local ProjectDoctrine lifecycle fixtures."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SCRIPT_DIR = Path(__file__).resolve().parents[2]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from project_doctrine import (  # noqa: E402
    accept_doctrine,
    baseline_draft_path,
    doctrine_sot_path,
    load_baseline_draft,
    load_doctrine,
    load_projection_doctrine,
    projection_path,
    promote_baseline,
    reject_adoption,
    scaffold_greenfield,
    status_report,
    validate_baseline,
    validate_doctrine,
    write_baseline_draft,
    write_projection,
)


def _minimal_doctrine(**overrides: object) -> dict:
    doc = {
        "id": "consumer-doctrine",
        "version": "ProjectDoctrine@v1",
        "provenance": {
            "createdAt": "2026-08-24T00:00:00Z",
            "source": "operator-review",
        },
        "confidence": "high",
        "sourceRefs": [{"uri": "file://repo/README.md"}],
    }
    doc.update(overrides)
    return doc


def _minimal_baseline(**overrides: object) -> dict:
    doc = {
        "id": "consumer-baseline",
        "version": "ProjectBaseline@v1",
        "provenance": {
            "createdAt": "2026-08-24T00:00:00Z",
            "source": "baseline-synthesis",
        },
        "status": "draft",
        "confidence": "medium",
        "facts": [
            {
                "id": "fact-1",
                "claim": "Primary runtime is Python 3.",
                "sourceEvidence": {"uri": "file://repo/pyproject.toml"},
                "confidence": "high",
            }
        ],
    }
    doc.update(overrides)
    return doc


def test_acceptance_leaves_durable_repo_local_doctrine(tmp_git_repo: Path, repo_root: Path) -> None:
    result = accept_doctrine(tmp_git_repo, _minimal_doctrine(), actor="operator")
    assert result.verdict == "pass"
    sot = doctrine_sot_path(tmp_git_repo)
    assert sot.is_file()
    loaded = load_doctrine(tmp_git_repo)
    assert loaded is not None
    assert validate_doctrine(loaded, repo_root)["verdict"] == "pass"


def test_rejection_leaves_no_doctrine(tmp_git_repo: Path, repo_root: Path) -> None:
    accept_doctrine(tmp_git_repo, _minimal_doctrine(), actor="operator")
    assert doctrine_sot_path(tmp_git_repo).is_file()
    result = reject_adoption(tmp_git_repo)
    assert result.verdict == "pass"
    assert load_doctrine(tmp_git_repo) is None
    assert not doctrine_sot_path(tmp_git_repo).exists()


def test_brownfield_output_remains_draft_until_promote(tmp_git_repo: Path, repo_root: Path) -> None:
    result = write_baseline_draft(tmp_git_repo, _minimal_baseline(), actor="synthesis")
    assert result.verdict == "pass"
    draft = load_baseline_draft(tmp_git_repo)
    assert draft is not None
    assert draft["status"] == "draft"
    assert load_doctrine(tmp_git_repo) is None
    refused = promote_baseline(tmp_git_repo, actor="operator", confirm=False)
    assert refused.verdict == "refused"
    assert load_doctrine(tmp_git_repo) is None
    promoted = promote_baseline(tmp_git_repo, actor="operator", confirm=True)
    assert promoted.verdict == "pass"
    assert load_doctrine(tmp_git_repo) is not None


def test_greenfield_scaffold_is_opt_in(tmp_git_repo: Path) -> None:
    refused = scaffold_greenfield(tmp_git_repo, actor="operator", confirm=False)
    assert refused.verdict == "refused"
    assert load_doctrine(tmp_git_repo) is None
    accepted = scaffold_greenfield(tmp_git_repo, actor="operator", confirm=True)
    assert accepted.verdict == "pass"
    doctrine = load_doctrine(tmp_git_repo)
    assert doctrine is not None
    assert doctrine["provenance"]["source"] == "greenfield-scaffold"


def test_issue_store_projection_never_becomes_authority(tmp_git_repo: Path, repo_root: Path) -> None:
    accept_doctrine(tmp_git_repo, _minimal_doctrine(), actor="operator")
    projected = write_projection(tmp_git_repo)
    assert projected.verdict == "pass"
    envelope = json.loads(projection_path(tmp_git_repo).read_text(encoding="utf-8"))
    assert envelope["projection"]["authority"] == "repo-local"
    assert envelope["projection"]["sourceOfTruth"] == ".sw/project-doctrine.json"
    # load_doctrine never reads projection
    assert load_projection_doctrine(tmp_git_repo) is not None
    doctrine_sot_path(tmp_git_repo).unlink()
    assert load_doctrine(tmp_git_repo) is None
    assert load_projection_doctrine(tmp_git_repo) is not None
    report = status_report(tmp_git_repo)
    assert report["hasDoctrine"] is False
    assert report["hasProjection"] is True
    assert report["projectionIsAuthority"] is False


def test_baseline_validation_rejects_promoted_status(tmp_git_repo: Path, repo_root: Path) -> None:
    baseline = _minimal_baseline(status="promoted")
    verdict = validate_baseline(baseline, repo_root)
    assert verdict["verdict"] == "fail"
