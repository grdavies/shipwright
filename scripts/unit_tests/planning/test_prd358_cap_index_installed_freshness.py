"""PRD 358 phase 11 — installed capability-index freshness (R10)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

scripts = Path(__file__).resolve().parents[2]
repo_root = Path(__file__).resolve().parents[3]
if str(scripts) not in sys.path:
    sys.path.insert(0, str(scripts))

from capability_index import (
    build_index,
    canonical_json,
    check_freshness,
    default_capability_index_path,
)
from capability_select import select_capabilities

FIXTURE_ROOT = repo_root / "scripts/test/fixtures/cap-index-installed-freshness"
SELECT = scripts / "capability_select.py"


def _ensure_index() -> Path:
    bundle = FIXTURE_ROOT
    scan = bundle
    index_path = default_capability_index_path(bundle)
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index = build_index(scan)
    index_path.write_text(json.dumps(index, indent=2) + "\n", encoding="utf-8")
    return index_path


@pytest.fixture()
def installed_bundle(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Copy fixture so tests can mutate without touching the committed tree."""
    import shutil

    dest = tmp_path_factory.mktemp("cap-index-installed-freshness")
    shutil.copytree(FIXTURE_ROOT, dest, dirs_exist_ok=True)
    scan = dest
    index_path = default_capability_index_path(dest)
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text(
        json.dumps(build_index(scan), indent=2) + "\n",
        encoding="utf-8",
    )
    return dest


def test_installed_freshness_ignores_source_core_skills(installed_bundle: Path) -> None:
    ok, message = check_freshness(installed_bundle)
    assert ok, message
    decoy = installed_bundle / "core" / "skills" / "decoy" / "SKILL.md"
    assert decoy.is_file()
    decoy.write_text(decoy.read_text(encoding="utf-8") + "\n<!-- mutated -->\n", encoding="utf-8")
    ok_after, _ = check_freshness(installed_bundle)
    assert ok_after, "freshness must use installed bundle layout, not source core/"


def test_installed_freshness_fails_when_index_stale(installed_bundle: Path) -> None:
    index_path = default_capability_index_path(installed_bundle)
    payload = json.loads(index_path.read_text(encoding="utf-8"))
    payload["capabilities"] = []
    index_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    ok, message = check_freshness(installed_bundle)
    assert not ok
    assert "does not match" in message


def test_capability_select_defaults_to_installed_index(installed_bundle: Path) -> None:
    ctx = {"version": 1, "body_snapshot": "Text with installed-cap-marker token."}
    proc = subprocess.run(
        [
            sys.executable,
            str(SELECT),
            "--root",
            str(installed_bundle),
            "--context-json",
            json.dumps(ctx),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
    result = json.loads(proc.stdout)
    ids = {row["id"] for row in result.get("capabilities", [])}
    assert "skill.installed-demo" in ids
    assert "skill.decoy" not in ids


def test_committed_fixture_index_matches_bundle(installed_bundle: Path) -> None:
    """Guard the checked-in fixture index against drift."""
    index_path = _ensure_index()
    committed = json.loads(
        (FIXTURE_ROOT / "core" / "sw-reference" / "capability-index.json").read_text(
            encoding="utf-8"
        )
    )
    expected = json.loads(index_path.read_text(encoding="utf-8"))
    assert canonical_json(committed) == canonical_json(expected)


def test_select_in_process_matches_installed_index(installed_bundle: Path) -> None:
    index = json.loads(
        default_capability_index_path(installed_bundle).read_text(encoding="utf-8")
    )
    ctx = {"version": 1, "body_snapshot": "installed-cap-marker in prose"}
    result = select_capabilities(index, ctx, repo_root=installed_bundle)
    ids = {row["id"] for row in result.get("capabilities", [])}
    assert "skill.installed-demo" in ids
