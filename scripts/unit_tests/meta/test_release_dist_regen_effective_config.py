"""Release-dist-regen workflow guards effective_config_gen + projection staging (PRD 329 R7)."""

from __future__ import annotations

from pathlib import Path

import pytest

WORKFLOW_REL = Path(".github/workflows/release-dist-regen.yml")
EFFECTIVE_CONFIG_CMD = "python3 scripts/effective_config_gen.py all --write"
STAGED_PATHS = (
    "docs/guides/configuration.md",
    "core/sw-reference/generated/effective-config.json",
    "core/sw-reference/generated/upgrade-manifest-*.json",
)


def _workflow_text(repo_root: Path) -> str:
    path = repo_root / WORKFLOW_REL
    assert path.is_file(), f"missing workflow {WORKFLOW_REL}"
    return path.read_text(encoding="utf-8")


def test_release_dist_regen_runs_effective_config_gen(repo_root: Path) -> None:
    """R7 — workflow must invoke effective_config_gen all --write on release-please heads."""
    body = _workflow_text(repo_root)
    assert EFFECTIVE_CONFIG_CMD in body, (
        f"{WORKFLOW_REL} must run `{EFFECTIVE_CONFIG_CMD}` "
        "(regression guard for release-please effective-config auto-regen)"
    )


@pytest.mark.parametrize("staged_path", STAGED_PATHS)
def test_release_dist_regen_stages_projection_paths(repo_root: Path, staged_path: str) -> None:
    """R7 — commit step must stage effective-config projection outputs."""
    body = _workflow_text(repo_root)
    assert f"git add {staged_path}" in body, (
        f"{WORKFLOW_REL} must stage `{staged_path}` when projections change"
    )


def test_release_dist_regen_guards_release_please_head(repo_root: Path) -> None:
    """R6/R7 — fork guard and release-please head ref remain wired."""
    body = _workflow_text(repo_root)
    assert "github.event.pull_request.head.repo.full_name == github.repository" in body
    assert "release-please--branches--main" in body

