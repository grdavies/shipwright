"""PRD 342 R33 — complete five-asset bundle keeps the same canonical body."""
from __future__ import annotations

import subprocess
from pathlib import Path

import planning_bundle as pb
import planning_index_gen as pig
import planning_paths as pp


def _git_init(repo: Path) -> None:
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "test"],
        cwd=repo,
        check=True,
        capture_output=True,
    )


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _canonical(*, unit_id: str = "prd-r33-fixture", declare_bundle: bool = False) -> str:
    lines = [
        "---",
        f"id: {unit_id}",
        "type: prd",
        "status: planned",
        "title: R33 Fixture",
        "visibility: public",
    ]
    if declare_bundle:
        lines.append("bundle: true")
    lines.extend(["---", "", "# Canonical body", ""])
    return "\n".join(lines)


def test_complete_bundle_keeps_same_canonical_body(tmp_path: Path) -> None:
    """R33 — first-body-with-id: selection is unchanged when a complete bundle is present."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git_init(repo)
    unit = repo / "docs" / "prds" / "999-r33-fixture"
    body_name = "999-prd-r33-fixture.md"
    _write(unit / body_name, _canonical(declare_bundle=False))

    before_index = pig.body_file_for_unit_dir(unit)
    before_bundle = pb.canonical_body_path(unit)
    assert before_index is not None
    assert before_bundle is not None
    assert before_index.resolve() == (unit / body_name).resolve()
    assert before_bundle.resolve() == (unit / body_name).resolve()

    _write(unit / body_name, _canonical(declare_bundle=True))
    for role in pp.BUNDLE_ASSET_ROLES:
        # Lexicographically earlier names than the canonical body must not capture selection.
        _write(unit / pp.BUNDLE_ASSET_FILENAMES[role], f"# {role}\nunique-{role}\n")

    after_index = pig.body_file_for_unit_dir(unit)
    after_bundle = pb.canonical_body_path(unit)
    assert after_index.resolve() == before_index.resolve()
    assert after_bundle.resolve() == before_bundle.resolve()

    result = pb.validate_unit_bundle(repo, unit)
    assert result["disposition"] == pb.DISPOSITION_COMPLETE
    assert result["bodyPath"].endswith(body_name)
