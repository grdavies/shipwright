"""PRD 348 R4/R4a — user-guide-provenance seeded-guide exclusion fixtures."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from check_user_guide_provenance import (
    EXIT_FAIL,
    EXIT_PASS,
    check_user_guide_provenance,
    evaluate_guide,
    has_provenance_tokens,
    is_seeded_guide,
    should_check_guide,
)


CLEAN_GUIDE = """# Getting started

Install the plugin and run `/sw-init`.
"""

SEEDED_GUIDE = """# Legacy guide

See PRD 341 R12 and GAP-435 for the prior cleanup plan.
"""

POLLUTED_NEW_GUIDE = """# New guide

This incorrectly cites PRD 348 and R4.
"""


def test_has_provenance_tokens_detects_prd_r_gap() -> None:
    assert has_provenance_tokens("mentions PRD 348 here")
    assert has_provenance_tokens("requirement R4 applies")
    assert has_provenance_tokens("tracks GAP-943")
    assert not has_provenance_tokens(CLEAN_GUIDE)
    assert not has_provenance_tokens("GAP-BACKLOG.md is a projection")
    assert not has_provenance_tokens("a PRD folder or issue-backed unit")


def test_seeded_predicate_excludes_already_seeded() -> None:
    assert is_seeded_guide(SEEDED_GUIDE) is True
    assert should_check_guide(base_text=SEEDED_GUIDE) is False


def test_seeded_predicate_includes_clean_new_and_missing_base() -> None:
    assert is_seeded_guide(CLEAN_GUIDE) is False
    assert should_check_guide(base_text=CLEAN_GUIDE) is True
    assert is_seeded_guide(None) is False
    assert should_check_guide(base_text=None) is True


def test_evaluate_excludes_seeded_even_when_head_still_polluted() -> None:
    finding = evaluate_guide(
        rel_path="core/documentation/legacy.md",
        head_text=SEEDED_GUIDE + "\nMore text.\n",
        base_text=SEEDED_GUIDE,
    )
    assert finding is not None
    assert finding.excluded is True
    assert finding.seeded is True
    assert finding.reason == "already-seeded-at-base"


def test_evaluate_fails_clean_new_guide_with_tokens() -> None:
    finding = evaluate_guide(
        rel_path="core/documentation/new-guide.md",
        head_text=POLLUTED_NEW_GUIDE,
        base_text=None,
    )
    assert finding is not None
    assert finding.excluded is False
    assert finding.reason == "provenance-tokens-in-clean-or-new-guide"


def test_evaluate_passes_clean_new_guide() -> None:
    finding = evaluate_guide(
        rel_path="core/documentation/new-guide.md",
        head_text=CLEAN_GUIDE,
        base_text=None,
    )
    assert finding is None


def test_evaluate_fails_previously_clean_guide_that_gains_tokens() -> None:
    finding = evaluate_guide(
        rel_path="core/documentation/workflows.md",
        head_text=CLEAN_GUIDE + "\nIntroduced PRD 348 by mistake.\n",
        base_text=CLEAN_GUIDE,
    )
    assert finding is not None
    assert finding.excluded is False


def _init_repo(root: Path) -> None:
    subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=root,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "fixture"],
        cwd=root,
        check=True,
        capture_output=True,
    )


def _commit_all(root: Path, message: str) -> str:
    subprocess.run(["git", "add", "-A"], cwd=root, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", message],
        cwd=root,
        check=True,
        capture_output=True,
    )
    sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return sha


def test_fixture_already_seeded_vs_clean_new(tmp_path: Path) -> None:
    """R4a — already-seeded guide excluded; clean-new polluted guide fails."""
    root = tmp_path / "repo"
    docs = root / "core" / "documentation"
    docs.mkdir(parents=True)
    (docs / "seeded.md").write_text(SEEDED_GUIDE, encoding="utf-8")
    (docs / "clean.md").write_text(CLEAN_GUIDE, encoding="utf-8")
    (root / "README.md").write_text("# Project\n", encoding="utf-8")
    _init_repo(root)
    base_sha = _commit_all(root, "base with seeded + clean")

    # Touch the seeded guide (still polluted) and add a new polluted guide.
    (docs / "seeded.md").write_text(
        SEEDED_GUIDE + "\nEdited in this PR.\n",
        encoding="utf-8",
    )
    (docs / "brand-new.md").write_text(POLLUTED_NEW_GUIDE, encoding="utf-8")
    _commit_all(root, "head touches seeded + adds polluted new")

    result = check_user_guide_provenance(root, base=base_sha)
    assert "core/documentation/seeded.md" in result.excluded
    assert "core/documentation/brand-new.md" in {f.path for f in result.failures}
    assert result.verdict == "fail"

    # Clean the new guide → seeded remains excluded; gate passes.
    (docs / "brand-new.md").write_text(CLEAN_GUIDE, encoding="utf-8")
    result_clean = check_user_guide_provenance(root, base=base_sha)
    assert "core/documentation/seeded.md" in result_clean.excluded
    assert result_clean.failures == []
    assert result_clean.verdict == "pass"


def test_cli_json_reports_exclusion(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    docs = root / "core" / "documentation"
    docs.mkdir(parents=True)
    (docs / "seeded.md").write_text(SEEDED_GUIDE, encoding="utf-8")
    (root / "README.md").write_text("# Project\n", encoding="utf-8")
    _init_repo(root)
    base_sha = _commit_all(root, "seeded base")
    (docs / "seeded.md").write_text(SEEDED_GUIDE + "\nedit\n", encoding="utf-8")
    _commit_all(root, "edit seeded")

    proc = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_DIR / "check_user_guide_provenance.py"),
            "--root",
            str(root),
            "--base",
            base_sha,
            "--json",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == EXIT_PASS
    payload = json.loads(proc.stdout)
    assert payload["verdict"] == "pass"
    assert "core/documentation/seeded.md" in payload["excluded"]


def test_cli_fails_without_base_when_tokens_present(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    docs = root / "core" / "documentation"
    docs.mkdir(parents=True)
    (docs / "seeded.md").write_text(SEEDED_GUIDE, encoding="utf-8")
    (root / "README.md").write_text("# Project\n", encoding="utf-8")

    proc = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_DIR / "check_user_guide_provenance.py"),
            "--root",
            str(root),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == EXIT_FAIL
