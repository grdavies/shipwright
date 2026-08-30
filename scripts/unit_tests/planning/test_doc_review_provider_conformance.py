"""PRD 341 R30 — doc-review provider conformance suite (fixture + GitHub enablement)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

scripts = Path(__file__).resolve().parents[2]
if str(scripts) not in sys.path:
    sys.path.insert(0, str(scripts))

from _planning_pkg_loader import load_submodule

_pc = load_submodule("doc_review_conformance")
DOC_REVIEW_CONFORMANCE_DIMENSIONS = _pc.DOC_REVIEW_CONFORMANCE_DIMENSIONS
run_doc_review_conformance_suite = _pc.run_doc_review_conformance_suite


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


@pytest.fixture(autouse=True)
def _fixture_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SW_ISSUES_FIXTURE", "1")


def test_github_doc_review_conformance_suite_green(tmp_path: Path) -> None:
    import json
    import subprocess

    root = tmp_path
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    (root / ".cursor" / "hooks" / "state").mkdir(parents=True, exist_ok=True)
    suite = run_doc_review_conformance_suite("github-issues", root)
    assert suite["verdict"] == "ok", suite.get("failedDimensions") or suite
    for dim in DOC_REVIEW_CONFORMANCE_DIMENSIONS:
        assert suite["dimensions"][dim]["verdict"] == "ok", (dim, suite["dimensions"][dim])


@pytest.mark.parametrize("provider", ["jira", "linear", "notion", "gitlab-issues"])
def test_non_github_doc_review_conformance_disabled(provider: str) -> None:
    root = _repo_root()
    suite = run_doc_review_conformance_suite(provider, root)
    assert suite["verdict"] == "ok"
    assert suite.get("posture") == "disabled"
    for dim in DOC_REVIEW_CONFORMANCE_DIMENSIONS:
        assert suite["dimensions"][dim]["verdict"] == "ok"
        assert suite["dimensions"][dim].get("posture") == "disabled"
