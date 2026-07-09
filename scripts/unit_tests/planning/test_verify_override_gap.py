"""PRD 060 R8–R9 verify-override gap capture tests."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

import planning_gap_capture as pgc


def _init_repo(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=tmp_path, check=True)
    (tmp_path / ".cursor" / "hooks" / "state").mkdir(parents=True, exist_ok=True)


def test_verify_override_signature_stable_excludes_reason() -> None:
    override_a = {
        "inconclusiveClass": "no-baseline",
        "reason": "first reason with secret AKIAIOSFODNN7EXAMPLE",
        "when": "2026-01-01T00:00:00Z",
    }
    override_b = {**override_a, "reason": "different reason", "when": "2026-02-02T00:00:00Z"}
    sig_a = pgc.verify_override_signature(override_a, unit_id="060-prd-x", pr_number=42)
    sig_b = pgc.verify_override_signature(override_b, unit_id="060-prd-x", pr_number=42)
    assert sig_a == sig_b


def test_capture_verify_override_create_and_reuse(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path
    _init_repo(root)
    written: dict[str, str] = {}

    def fake_put(r: Path, unit_id: str, body_path_rel: str, content: str) -> None:
        path = r / body_path_rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        written[unit_id] = content

    monkeypatch.setattr(pgc, "store_put_gap", fake_put)
    override = {
        "who": "dev@example.com",
        "inconclusiveClass": "no-baseline",
        "reason": "key AKIAIOSFODNN7EXAMPLE leaked",
    }
    first = pgc.capture_verify_override(root, override, unit_id="060-prd-x", pr_number=7)
    assert first["action"] == "created"
    assert first["unitId"]
    body = written[first["unitId"]]
    assert "AKIA" not in body
    assert "redacted" in body.lower() or "[redacted" in body.lower() or "REDACTED" in body

    second = pgc.capture_verify_override(root, override, unit_id="060-prd-x", pr_number=7)
    assert second["action"] == "reused"
    assert second["unitId"] == first["unitId"]


def test_capture_verify_override_skips_missing_required(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    out = pgc.capture_verify_override(
        tmp_path,
        {"inconclusiveClass": "missing-required", "reason": "blocked"},
    )
    assert out["action"] == "skipped"
