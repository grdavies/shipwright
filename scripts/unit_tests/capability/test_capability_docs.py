"""Unit tests for registry-sourced capability documentation (PRD 270 R8)."""

from __future__ import annotations

import json
from pathlib import Path

import capability_docs as cd


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def test_derived_shipped_includes_linear_when_conformance_green() -> None:
    root = _repo_root()
    registry = cd.load_registry(root)
    shipped = cd.derive_shipped_issues_providers(root, registry)
    assert "linear" in shipped
    assert "github-issues" in shipped
    assert "none" in shipped


def test_root_capabilities_includes_linear() -> None:
    root = _repo_root()
    registry = cd.load_registry(root)
    rendered = cd.render_root_capabilities_md(root, registry)
    assert "`linear`" in rendered
    assert cd.GENERATOR_BANNER in rendered


def test_check_passes_on_repo() -> None:
    root = _repo_root()
    assert cd.cmd_check(root) == 0


def test_conformance_gated_shipped_requires_green_record(tmp_path: Path) -> None:
    registry = cd.load_registry(_repo_root())
    fixture_dir = tmp_path / "scripts/test/fixtures/planning-provider-conformance"
    fixture_dir.mkdir(parents=True)
    (fixture_dir / "linear.ok.json").write_text(
        json.dumps({"verdict": "fail", "provider": "linear", "dimensions": {}}),
        encoding="utf-8",
    )
    errors = cd.validate_conformance_semantics(tmp_path, registry)
    assert any("linear" in err for err in errors)
