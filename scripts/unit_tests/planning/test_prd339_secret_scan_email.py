"""PRD 339 R36 — schema-version EMAIL false-positive suppression."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

import planning_store_facade as psf
from secret_scan import load_allowlist, scan_text

_CORPUS = (
    Path(__file__).resolve().parents[2] / "test" / "fixtures" / "secret-scan-email" / "corpus.json"
)


def _load_corpus() -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    data = json.loads(_CORPUS.read_text(encoding="utf-8"))
    return list(data["allowed"]), list(data["blocked"])


def _init_repo(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=tmp_path, check=True)
    (tmp_path / ".cursor").mkdir(parents=True, exist_ok=True)


def test_schema_version_email_false_positive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R36 — schema-version tokens pass; real EMAIL secrets still block via planning-store scan."""
    _init_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    allowlist = load_allowlist(tmp_path)
    allowed, blocked = _load_corpus()

    for case in allowed:
        text = case["text"]
        email_findings = [f for f in scan_text(text, allowlist=allowlist) if f.pattern == "EMAIL"]
        assert not email_findings, case["id"]
        psf.secret_scan_text(text)

    for case in blocked:
        text = case["text"]
        email_findings = [f for f in scan_text(text, allowlist=allowlist) if f.pattern == "EMAIL"]
        assert email_findings, case["id"]
        with pytest.raises(SystemExit) as exc:
            psf.secret_scan_text(text)
        assert exc.value.code == 2
