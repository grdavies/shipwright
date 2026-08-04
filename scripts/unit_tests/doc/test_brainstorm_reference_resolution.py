"""PRD 081 R14 — brainstorm reference resolution fixtures."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

scripts = Path(__file__).resolve().parents[2]
if str(scripts) not in sys.path:
    sys.path.insert(0, str(scripts))

import doc_link
import wave_spec_seed as wss
from doc_link import check_artifact, link_target_resolves, write_backref


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    (root / ".cursor").mkdir(parents=True, exist_ok=True)
    (root / "docs" / "brainstorms").mkdir(parents=True)
    (root / "docs" / "prds" / "099-fixture").mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=root, check=True)
    return root


def _write_brainstorm(repo: Path, rel: str = "docs/brainstorms/2026-06-25-fixture.md") -> str:
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "---\ntype: brainstorm\nid: brainstorm-2026-06-25-fixture\n---\n# Brainstorm\n",
        encoding="utf-8",
    )
    return rel


def _write_prd(
    repo: Path,
    *,
    brainstorm: str | None = "docs/brainstorms/2026-06-25-fixture.md",
    frozen: bool = True,
    tier_fm: str | None = "full",
) -> str:
    rel = "docs/prds/099-fixture/099-prd-fixture.md"
    path = repo / rel
    fm = ["---", "type: prd", "id: 099-prd-fixture"]
    if tier_fm:
        fm.append(f"tier: {tier_fm}")
    if frozen:
        fm.append("frozen: true")
    if brainstorm:
        fm.append(f"brainstorm: {brainstorm}")
    fm.append("---")
    path.write_text("\n".join(fm) + "\n# PRD\n", encoding="utf-8")
    return rel


def test_resolvable_unit_id_linkage_passes(repo: Path) -> None:
    bs = _write_brainstorm(repo)
    prd = _write_prd(repo, brainstorm=bs)
    backend = MagicMock()
    backend.exists.return_value = MagicMock(verdict="ok")
    with patch("planning_artifact_handle.issue_store_is_effective", return_value=True), patch(
        "planning_store.get_backend", return_value=backend
    ), patch("planning_artifact_handle.resolve_repo_file", return_value=None):
        assert link_target_resolves(
            repo,
            bs,
            unit_id="brainstorm-2026-06-25-fixture",
            prd_unit_id="099-prd-fixture",
        )
        result = check_artifact(repo, prd, tier="full", unit_id="099-prd-fixture")
    assert result["verdict"] == "pass"


def test_missing_brainstorm_fails_gate(repo: Path) -> None:
    prd = _write_prd(repo, brainstorm="docs/brainstorms/missing.md")
    result = check_artifact(repo, prd, tier="full")
    assert result["verdict"] == "fail"
    assert any(f["code"] == "dangling-brainstorm-backref" for f in result["findings"])


def test_frozen_standard_prd_without_brainstorm_passes(repo: Path) -> None:
    prd = _write_prd(repo, brainstorm=None, frozen=True, tier_fm=None)
    result = check_artifact(repo, prd, tier="standard")
    assert result["verdict"] == "pass"


def test_patch_tier_requires_origin_issue(repo: Path) -> None:
    prd = _write_prd(repo, brainstorm=None, frozen=False, tier_fm=None)
    result = check_artifact(repo, prd, tier="patch")
    assert result["verdict"] == "fail"
    assert any(f["code"] == "missing-origin" for f in result["findings"])


def test_patch_tier_issue_origin_requires_resolvable_ref(repo: Path) -> None:
    rel = "docs/prds/099-fixture/099-prd-fixture.md"
    path = repo / rel
    path.write_text(
        "---\n"
        "type: prd\n"
        "id: 099-prd-fixture\n"
        "origin: issue\n"
        "frozen: true\n"
        "---\n# PRD\n",
        encoding="utf-8",
    )
    result = check_artifact(repo, rel, tier="patch")
    assert result["verdict"] == "fail"
    assert any(f["code"] == "missing-issue-ref" for f in result["findings"])


def test_standard_tier_defaults_origin_request(repo: Path) -> None:
    prd = _write_prd(repo, brainstorm=None, frozen=True, tier_fm=None)
    result = check_artifact(repo, prd, tier="standard")
    assert result["verdict"] == "pass"
    assert not any(f["code"] == "missing-brainstorm-backref" for f in result.get("findings", []))


def test_seeded_feature_branch_resolves_reference(repo: Path) -> None:
    bs_rel = _write_brainstorm(repo)
    prd_rel = _write_prd(repo, brainstorm=bs_rel, frozen=True)
    tasks_rel = "docs/prds/099-fixture/tasks-099-fixture.md"
    tasks_path = repo / tasks_rel
    tasks_path.write_text("---\ntype: tasks\nfrozen: true\n---\n# Tasks\n", encoding="utf-8")
    docs_dir = repo / "docs/prds/099-fixture"
    for path in (repo / bs_rel, repo / prd_rel, tasks_path):
        subprocess.run(["git", "add", str(path.relative_to(repo))], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "seed docs"], cwd=repo, check=True)

    brainstorms = wss.referenced_brainstorm_paths(repo, docs_dir)
    assert any(p.name.endswith("2026-06-25-fixture.md") for p in brainstorms)

    write_backref(repo, bs_rel, prd_rel)
    result = check_artifact(repo, prd_rel, tier="full")
    assert result["verdict"] == "pass"
