"""PRD 072 R6 — decision bodies live in planning-store home; publish-surface guards."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2]
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import memory_sot as ms
import publish_surface_audit as psa


def test_decision_stub_allowlist_excludes_bodies() -> None:
    assert ms.is_decision_body_path("docs/decisions/001-sample.md")
    assert not ms.is_decision_body_path("docs/decisions/INDEX.md")
    assert not ms.is_decision_body_path("docs/decisions/SUPERSEDED.log")


def test_resolve_decision_home_planning_store(repo_root: Path) -> None:
    home = ms.resolve_decision_home(repo_root)
    assert home["home"] == "planning-store"
    assert home["codeRepoBodies"] is False
    assert home["virtualPathPrefix"] == "docs/decisions/"
    assert home["storeRef"] == "grdavies/planning"
    assert set(home["stubsOnly"]) == set(ms.DECISION_STUB_ALLOWLIST)


def test_publish_surface_audit_decision_body_leak_not_ready() -> None:
    tracked = ["README.md", "docs/decisions/042-migration-fixture.md", "docs/decisions/INDEX.md"]
    result = psa.run_publish_surface_audit(Path("."), tracked_override=tracked)
    assert result["verdict"] == "not-ready"
    assert "denylist-leaked-paths" in result["failed"]
    leaks = result["considered"][0]["detail"]["leaks"]
    assert "docs/decisions/042-migration-fixture.md" in leaks
    assert "docs/decisions/INDEX.md" not in leaks


def test_publish_surface_audit_decision_home_migration_check(repo_root: Path) -> None:
    result = psa.run_publish_surface_audit(repo_root)
    migration = next(item for item in result["considered"] if item["id"] == "decision-home-migration")
    assert migration["status"] == "passed"
    assert migration["detail"]["decisionHome"]["home"] == "planning-store"


def test_memory_sot_resolve_includes_decision_home(repo_root: Path) -> None:
    proc = subprocess.run(
        [sys.executable, str(repo_root / "scripts/memory-sot.py"), "resolve", "--class", "decision", "--json"],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        check=True,
    )
    payload = json.loads(proc.stdout)
    assert payload["decisionHome"]["home"] == "planning-store"
    assert payload["decisionHome"]["codeRepoBodies"] is False


def test_pointer_recipe_planning_store_authoritative(repo_root: Path) -> None:
    proc = subprocess.run(
        [
            sys.executable,
            str(repo_root / "scripts/memory-sot.py"),
            "pointer-recipe",
            "--path",
            "docs/decisions/001-test.md",
            "--json",
        ],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        check=True,
    )
    payload = json.loads(proc.stdout)
    assert payload["planningStore"]["role"] == "authoritative-body"
    assert payload["git"]["snapshotRole"] == "stub-only"


def test_decision_unit_id_from_path() -> None:
    assert ms.decision_unit_id_from_path("docs/decisions/001-sample-slug.md") == "decision-001-sample-slug"
