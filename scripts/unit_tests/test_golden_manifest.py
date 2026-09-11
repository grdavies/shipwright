"""Unit tests for scripts/golden_manifest.py (PRD 343 phase 1 — R1/R2)."""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

import golden_manifest as gm


def _write_tree(root: Path, files: dict[str, str]) -> None:
    for rel, body in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")


@pytest.fixture
def repo_with_dist(tmp_path: Path) -> Path:
    """Minimal repo layout with dist/cursor content."""
    dist = tmp_path / "dist" / "cursor"
    _write_tree(
        dist,
        {
            "commands/sw-demo.md": "# demo\n",
            "skills/demo/SKILL.md": "# skill\n",
            "scripts/helper.py": "print('hi')\n",
            "scripts/test/ignored.py": "should-skip\n",
            "hooks/pre-commit": "ignored\n",
        },
    )
    return tmp_path


def test_generate_manifest_text_is_deterministic(repo_with_dist: Path) -> None:
    first = gm.generate_manifest_text(repo_with_dist)
    second = gm.generate_manifest_text(repo_with_dist)
    assert first == second
    assert first.endswith("\n")
    assert "commands/sw-demo.md\t" in first
    assert "skills/demo/SKILL.md\t" in first
    assert "scripts/helper.py\t" in first
    # Skipped paths must not appear
    assert "scripts/test/ignored.py" not in first
    assert "hooks/pre-commit" not in first


def test_write_manifest_idempotent(repo_with_dist: Path) -> None:
    out = repo_with_dist / "scripts/test/fixtures/parity/cursor-golden.manifest"
    first = gm.write_manifest(repo_with_dist, out_path=out)
    assert first["verdict"] == "pass"
    assert first["changed"] is True
    assert out.is_file()
    digest = hashlib.sha256(out.read_bytes()).hexdigest()
    assert first["sha256"] == digest

    second = gm.write_manifest(repo_with_dist, out_path=out)
    assert second["verdict"] == "pass"
    assert second["changed"] is False
    assert second["sha256"] == digest
    assert out.read_text(encoding="utf-8") == gm.generate_manifest_text(repo_with_dist)


def test_empty_dist_produces_empty_manifest(tmp_path: Path) -> None:
    (tmp_path / "dist" / "cursor").mkdir(parents=True)
    text = gm.generate_manifest_text(tmp_path)
    assert text == ""


def test_single_file_manifest_hash(tmp_path: Path) -> None:
    dist = tmp_path / "dist" / "cursor"
    body = "only\n"
    _write_tree(dist, {"commands/one.md": body})
    text = gm.generate_manifest_text(tmp_path)
    expected = hashlib.sha256(body.encode()).hexdigest()
    assert text == f"commands/one.md\t{expected}\n"


def test_check_staleness_detects_drift(repo_with_dist: Path) -> None:
    out = repo_with_dist / "cursor-golden.manifest"
    gm.write_manifest(repo_with_dist, out_path=out)
    fresh = gm.check_staleness(repo_with_dist, manifest_path=out)
    assert fresh["verdict"] == "pass"
    assert fresh["stale"] is False

    out.write_text("tampered\n", encoding="utf-8")
    stale = gm.check_staleness(repo_with_dist, manifest_path=out)
    assert stale["verdict"] == "fail"
    assert stale["stale"] is True


def test_check_staleness_missing_manifest(repo_with_dist: Path) -> None:
    missing = repo_with_dist / "missing-cursor-golden.manifest"
    result = gm.check_staleness(repo_with_dist, manifest_path=missing)
    assert result["verdict"] == "fail"
    assert result["stale"] is True
    assert result["error"] == "manifest-missing"


def test_gate_validate_golden_manifest_staleness(repo_with_dist: Path) -> None:
    """Gate validator uses the default manifest path under the given root (PRD 343 R3)."""
    import check_gate_lib as gate

    out = gm.default_manifest_path(repo_with_dist)
    gm.write_manifest(repo_with_dist, out_path=out)
    assert gate.validate_golden_manifest_staleness(repo_with_dist) is None

    out.write_text("stale-on-purpose\n", encoding="utf-8")
    assert gate.validate_golden_manifest_staleness(repo_with_dist) == "golden-manifest:stale"

    out.unlink()
    assert gate.validate_golden_manifest_staleness(repo_with_dist) == "golden-manifest:missing"


def test_gate_validate_skips_under_sw_gate_fixture(
    repo_with_dist: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import check_gate_lib as gate

    out = gm.default_manifest_path(repo_with_dist)
    gm.write_manifest(repo_with_dist, out_path=out)
    out.write_text("stale-on-purpose\n", encoding="utf-8")
    monkeypatch.setenv("SW_GATE_FIXTURE", "green")
    assert gate.validate_golden_manifest_staleness(repo_with_dist) is None


def test_gate_validate_skips_without_dist_cursor(tmp_path: Path) -> None:
    import check_gate_lib as gate

    # Sparse fixture trees have no dist/cursor — do not fail-closed on golden.
    assert not (tmp_path / "dist" / "cursor").exists()
    assert gate.validate_golden_manifest_staleness(tmp_path) is None
