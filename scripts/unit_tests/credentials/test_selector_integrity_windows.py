"""Non-POSIX selector integrity simulation tests (PRD 083 R4)."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from credentials.selector_integrity import (
    PathVerificationResult,
    check_selector_integrity,
    verify_selector_path,
)


def _write_selector(path: Path) -> None:
    if not path.parent.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "entries": {
                    "github-work": {
                        "backend": "github_cli",
                        "provider": "github",
                        "allowedRepos": ["owner/repo"],
                        "allowedProjectIds": ["proj-1"],
                        "allowedEndpoints": ["https://api.github.com"],
                    }
                },
            }
        ),
        encoding="utf-8",
    )


class TestNonPosixSelectorIntegrity:
    def test_verify_selector_path_skips_getuid_on_non_posix(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        selector = tmp_path / "credential-selector.json"
        _write_selector(selector)
        monkeypatch.setattr(os, "name", "nt")
        monkeypatch.delattr(os, "getuid", raising=False)

        result = verify_selector_path(selector)

        assert isinstance(result, PathVerificationResult)
        assert result.verdict == "ok"
        assert result.posture == "windows-reduced"
        assert result.reason

    def test_check_selector_integrity_propagates_windows_reduced_posture(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        selector = tmp_path / "credential-selector.json"
        _write_selector(selector)
        monkeypatch.setattr(os, "name", "nt")
        monkeypatch.delattr(os, "getuid", raising=False)

        report = check_selector_integrity(selector)

        assert report.verdict == "ok"
        assert report.posture == "windows-reduced"
        assert report.reason

    def test_non_posix_with_getuid_still_uses_reduced_posture(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """os.name is authoritative — getuid presence alone must not enable POSIX checks."""
        selector = tmp_path / "credential-selector.json"
        _write_selector(selector)
        monkeypatch.setattr(os, "name", "nt")
        monkeypatch.setattr(os, "getuid", lambda: 0, raising=False)

        result = verify_selector_path(selector)

        assert result.verdict == "ok"
        assert result.posture == "windows-reduced"
