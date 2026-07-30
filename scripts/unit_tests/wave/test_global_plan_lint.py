"""PRD 081 R18 — global-plan literal lint fixtures."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

import global_plan_lint as gpl
from wave_run_paths import GLOBAL_PLAN_REL, mint_run_id, plan_path
from wave_run_plan import ensure_run_id, persist_plan


def _sample_plan() -> dict:
    return {
        "mode": "phase",
        "target": {"branch": "feat/demo", "slug": "demo"},
        "prd_number": "081",
        "items": [{"id": "1", "slug": "alpha"}],
        "waves": [["1"]],
        "edges": [],
    }


def _init_git(path: Path) -> None:
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=path, check=True, capture_output=True)
    (path / "README.md").write_text("seed\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "seed"], cwd=path, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _init_git(root)
    return root


def test_clean_tree_passes(repo_root: Path) -> None:
    result = gpl.check(repo_root)
    assert result["verdict"] == "pass"


def test_helper_is_only_literal_definition_site() -> None:
    permitted = gpl.permitted_literal_paths()
    assert "scripts/wave_run_paths.py" in permitted
    assert "scripts/unit_tests/wave/test_global_plan_lint.py" in permitted


def test_reintroduced_literal_in_converted_reader_fails() -> None:
    poisoned = 'LEGACY_TRAP = ".cursor/sw-deliver-plan.json"\n'
    hits = gpl.scan_text("scripts/docs-currency-gate.py", poisoned)
    assert any(hit["scope"] == "converted-reader" for hit in hits)


def test_scan_text_flags_unlisted_module() -> None:
    hits = gpl.scan_text("scripts/example.py", 'path = ".cursor/sw-deliver-plan.json"\n')
    assert hits
    assert hits[0]["kind"] == "legacy-plan-literal"


def test_docs_currency_gate_resolves_run_scoped_plan(repo: Path) -> None:
    import importlib.util

    script = Path(__file__).resolve().parents[2] / "docs-currency-gate.py"
    spec = importlib.util.spec_from_file_location("docs_currency_gate", script)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    resolve_plan_path = mod.resolve_plan_path

    state: dict = {}
    run_id = ensure_run_id(repo, state)
    persist_plan(repo, run_id, _sample_plan(), state)
    resolved = resolve_plan_path(repo, state, run_id=run_id)
    assert resolved == plan_path(repo, run_id)
    assert GLOBAL_PLAN_REL not in str(resolved)


def test_docs_currency_gate_cli_accepts_run_id(repo: Path) -> None:
    scripts_src = Path(__file__).resolve().parents[2]
    (repo / "scripts").symlink_to(scripts_src, target_is_directory=True)
    state: dict = {"prd_number": "081", "phases": {"1": {"status": "pending"}}, "target": {"branch": "feat/demo"}}
    run_id = ensure_run_id(repo, state)
    persist_plan(repo, run_id, _sample_plan(), state)
    state_path = repo / ".cursor" / "state.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state), encoding="utf-8")
    prds = repo / "docs" / "prds"
    prds.mkdir(parents=True, exist_ok=True)
    (prds / "INDEX.md").write_text(
        "| # | Slug | PRD | Tasks | Status |\n|---|------|-----|-------|--------|\n| 081 | demo | x | y | not-started |\n",
        encoding="utf-8",
    )
    (prds / "GAP-BACKLOG.md").write_text(
        "| Status | Count |\n|--------|------:|\n| resolved | 0 |\n| scheduled | 0 |\n| open | 0 |\n",
        encoding="utf-8",
    )
    script = scripts_src / "docs-currency-gate.py"
    proc = subprocess.run(
        [
            "python3",
            str(script),
            "--run-id",
            run_id,
            "--skip-artifact-currency",
            str(repo),
            str(repo),
            str(state_path),
            str(plan_path(repo, run_id)),
        ],
        cwd=str(repo),
        text=True,
        capture_output=True,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["verdict"] == "pass"
    assert str(plan_path(repo, run_id)) in payload.get("planPath", "")
