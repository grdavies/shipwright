"""Pytest port of run_capability_lint_fixtures.py (PRD 054 W1 behavioral)."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import capability_docs as cd
import pytest

_PKG = "scripts/unit_tests/capability"
_HARNESS = "harness_capability_lint.py"


def _load_harness(repo_root: Path):
    path = repo_root / _PKG / _HARNESS
    for entry in (str(repo_root / "scripts" / "test"), str(repo_root / "scripts")):
        if entry not in sys.path:
            sys.path.insert(0, entry)
    spec = importlib.util.spec_from_file_location("harness_capability_lint", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load harness {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_capability_lint_behavior(repo_root: Path, sw_env: dict[str, str], monkeypatch: pytest.MonkeyPatch) -> None:
    for key, value in sw_env.items():
        monkeypatch.setenv(key, value)
    monkeypatch.chdir(repo_root)
    mod = _load_harness(repo_root)
    assert int(mod.main()) == 0


def test_capability_lint_harness_present(repo_root: Path) -> None:
    """R16 — harness module must exist (fail-closed if port regresses)."""
    assert (repo_root / _PKG / _HARNESS).is_file()


def test_derived_shipped_includes_linear_when_conformance_green(repo_root: Path) -> None:
    registry = cd.load_registry(repo_root)
    shipped = cd.derive_shipped_issues_providers(repo_root, registry)
    assert "linear" in shipped
    assert "github-issues" in shipped
    assert "none" in shipped


def test_root_capabilities_includes_linear(repo_root: Path) -> None:
    registry = cd.load_registry(repo_root)
    rendered = cd.render_root_capabilities_md(repo_root, registry)
    assert "`linear`" in rendered
    assert cd.GENERATOR_BANNER in rendered


def test_capability_docs_check_passes_on_repo(repo_root: Path) -> None:
    assert cd.cmd_check(repo_root) == 0


def test_conformance_gated_shipped_requires_green_record(
    repo_root: Path, tmp_path: Path
) -> None:
    registry = cd.load_registry(repo_root)
    fixture_dir = tmp_path / "scripts/test/fixtures/planning-provider-conformance"
    fixture_dir.mkdir(parents=True)
    (fixture_dir / "linear.ok.json").write_text(
        json.dumps({"verdict": "fail", "provider": "linear", "dimensions": {}}),
        encoding="utf-8",
    )
    errors = cd.validate_conformance_semantics(tmp_path, registry)
    assert any("linear" in err for err in errors)
