"""PRD 325 R6–R7 — publish-surface profile resolution and profile-aware checks."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2]
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import publish_surface_audit as psa


def test_resolve_publish_surface_profile_explicit_config(tmp_path: Path) -> None:
    cfg = {"planning": {"publishSurface": {"profile": "in-repo-public"}}}
    (tmp_path / ".cursor").mkdir()
    (tmp_path / ".cursor" / "workflow.config.json").write_text(
        json.dumps(cfg), encoding="utf-8"
    )
    resolved = psa.resolve_publish_surface_profile(tmp_path, cfg)
    assert resolved["profile"] == "in-repo-public"
    assert resolved["source"] == "config"


def test_resolve_publish_surface_profile_unknown_falls_back_private(tmp_path: Path) -> None:
    cfg = {"planning": {"publishSurface": {"profile": "mystery"}}}
    resolved = psa.resolve_publish_surface_profile(tmp_path, cfg)
    assert resolved["profile"] == "private"
    assert resolved["source"] == "config-unknown"
    assert resolved["requested"] == "mystery"


def test_in_repo_public_skips_docs_prds_absent() -> None:
    tracked = ["README.md", "docs/prds/325-test/tasks-325-test.md"]
    result = psa.run_publish_surface_audit(
        Path("."),
        tracked_override=tracked,
        profile_override="in-repo-public",
    )
    assert result["profile"] == "in-repo-public"
    assert result["verdict"] == "ready"
    assert "docs-prds-absent" in result["skipped"]
    assert "docs-prds-absent" not in result["failed"]
    docs_check = next(
        item for item in result["considered"] if item["id"] == "docs-prds-absent"
    )
    assert docs_check["status"] == "skipped"
    assert docs_check["considered"] is False
    assert docs_check["detail"]["profile"] == "in-repo-public"


def test_private_profile_docs_prds_leak_not_ready() -> None:
    tracked = ["README.md", "docs/prds/069-test/tasks-069-test.md"]
    result = psa.run_publish_surface_audit(
        Path("."),
        tracked_override=tracked,
        profile_override="private",
    )
    assert result["verdict"] == "not-ready"
    assert "docs-prds-absent" in result["failed"]


def test_denylist_critical_unchanged_under_in_repo_public() -> None:
    tracked = [
        "README.md",
        "docs/prds/325-test/tasks-325-test.md",
        "docs/learnings/sample-retro.md",
    ]
    result = psa.run_publish_surface_audit(
        Path("."),
        tracked_override=tracked,
        profile_override="in-repo-public",
    )
    assert result["verdict"] == "not-ready"
    assert "denylist-leaked-paths" in result["failed"]
    assert "docs-prds-absent" in result["skipped"]


def test_gitignore_snippets_drop_docs_prds_for_in_repo_public(tmp_path: Path) -> None:
    gitignore = tmp_path / ".gitignore"
    gitignore.write_text(
        "\n".join(
            [
                ".cursor/planning-materialized/",
                ".cursor/sw-deliver-runs/",
                "docs/learnings/",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    result = psa.run_publish_surface_audit(
        tmp_path,
        tracked_override=["README.md"],
        profile_override="in-repo-public",
    )
    git_check = next(
        item for item in result["considered"] if item["id"] == "gitignore-publish-hygiene"
    )
    assert git_check["status"] == "passed"
    assert git_check["detail"]["profile"] == "in-repo-public"


def test_gitignore_private_still_requires_docs_prds_snippet(tmp_path: Path) -> None:
    gitignore = tmp_path / ".gitignore"
    gitignore.write_text(
        "\n".join(
            [
                ".cursor/planning-materialized/",
                ".cursor/sw-deliver-runs/",
                "docs/learnings/",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    result = psa.run_publish_surface_audit(
        tmp_path,
        tracked_override=["README.md"],
        profile_override="private",
    )
    git_check = next(
        item for item in result["considered"] if item["id"] == "gitignore-publish-hygiene"
    )
    assert git_check["status"] == "failed"
    assert "docs/prds/" in git_check["detail"]["missingSnippets"]
