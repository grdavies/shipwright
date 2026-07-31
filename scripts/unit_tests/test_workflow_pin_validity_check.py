"""Unit tests for workflow-pin-validity-check.py (PRD 083 R10).

Tests:
  - fail-closed: deliberate invalid SHA pin → exit non-zero, verdict "fail"
  - fail-open:   upstream lookup error (network) → exit 0, verdict "warn"
"""

from __future__ import annotations

import json
import textwrap
from pathlib import Path
from unittest.mock import patch

import pytest

import sys

SCRIPT_DIR = Path(__file__).resolve().parent.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import workflow_pin_validity_check_lib as lib


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_workflow(tmp_path: Path, content: str) -> Path:
    wf_dir = tmp_path / ".github" / "workflows"
    wf_dir.mkdir(parents=True, exist_ok=True)
    wf_file = wf_dir / "test.yml"
    wf_file.write_text(textwrap.dedent(content), encoding="utf-8")
    return tmp_path


# ---------------------------------------------------------------------------
# Fail-closed: confirmed-invalid SHA pin → non-zero exit, verdict "fail"
# ---------------------------------------------------------------------------


def test_fail_closed_invalid_sha_pin(tmp_path: Path) -> None:
    """A workflow with a deliberately invalid SHA pin must fail closed."""
    invalid_sha = "a" * 40  # 40-char hex — looks like a SHA but does not exist
    _write_workflow(
        tmp_path,
        f"""\
        name: CI
        on: [push]
        jobs:
          test:
            runs-on: ubuntu-latest
            steps:
              - uses: actions/checkout@{invalid_sha}
        """,
    )

    # Mock GitHub API to return None (404 — SHA not found)
    def mock_api_request(url: str, token: str | None = None) -> dict | list | None:
        return None  # simulates 404 / not found

    with patch.object(lib, "_github_api_request", side_effect=mock_api_request):
        exit_code, result = lib.run_check(tmp_path)

    assert exit_code != 0, f"Expected non-zero exit for invalid pin, got {exit_code}"
    assert result["verdict"] == "fail", f"Expected verdict 'fail', got {result['verdict']}"
    assert "invalid_pins" in result, "Expected 'invalid_pins' key in result"
    invalid_pins = result["invalid_pins"]
    assert len(invalid_pins) >= 1
    pin = invalid_pins[0]
    assert pin["slug"] == "actions/checkout"
    assert pin["ref"] == invalid_sha


# ---------------------------------------------------------------------------
# Fail-open: transient upstream lookup error → exit 0, verdict "warn"
# ---------------------------------------------------------------------------


def test_fail_open_on_network_error(tmp_path: Path) -> None:
    """A transient upstream lookup error must fail open (exit 0) with a logged warning."""
    valid_sha = "b" * 40  # A SHA-looking pin
    _write_workflow(
        tmp_path,
        f"""\
        name: CI
        on: [push]
        jobs:
          test:
            runs-on: ubuntu-latest
            steps:
              - uses: actions/checkout@{valid_sha}
        """,
    )

    import urllib.error

    # Mock GitHub API to raise URLError (simulating network failure)
    def mock_api_request_error(url: str, token: str | None = None) -> dict | list | None:
        raise urllib.error.URLError("Connection refused (mocked)")

    with patch.object(lib, "_github_api_request", side_effect=mock_api_request_error):
        exit_code, result = lib.run_check(tmp_path)

    assert exit_code == 0, f"Expected exit 0 (fail-open) on network error, got {exit_code}"
    assert result["verdict"] in ("warn", "pass"), (
        f"Expected verdict 'warn' or 'pass' on transient error, got {result['verdict']}"
    )
    # The warning list should contain at least one entry about the skipped pin
    warnings = result.get("warnings", [])
    assert len(warnings) >= 1, "Expected at least one warning for transient lookup failure"
    assert any("transient" in w for w in warnings), (
        f"Expected 'transient' in warning message, got: {warnings}"
    )


# ---------------------------------------------------------------------------
# Extra coverage: no third-party pins → pass cleanly
# ---------------------------------------------------------------------------


def test_no_pins_returns_pass(tmp_path: Path) -> None:
    """Workflow with no action uses → pass immediately without any API calls."""
    _write_workflow(
        tmp_path,
        """\
        name: CI
        on: [push]
        jobs:
          test:
            runs-on: ubuntu-latest
            steps:
              - run: echo hello
        """,
    )
    exit_code, result = lib.run_check(tmp_path)
    assert exit_code == 0
    assert result["verdict"] == "pass"


# ---------------------------------------------------------------------------
# Valid tag pin in allowlist → pass without API call
# ---------------------------------------------------------------------------


def test_valid_tag_in_allowlist_skips_api(tmp_path: Path) -> None:
    """A tag present in the static allowlist passes without any API call."""
    _write_workflow(
        tmp_path,
        """\
        name: CI
        on: [push]
        jobs:
          test:
            runs-on: ubuntu-latest
            steps:
              - uses: actions/checkout@v4
        """,
    )

    call_count = {"n": 0}

    def mock_api_request(url: str, token: str | None = None) -> dict | list | None:
        call_count["n"] += 1
        return {"ref": "refs/tags/v4"}

    with patch.object(lib, "_github_api_request", side_effect=mock_api_request):
        exit_code, result = lib.run_check(tmp_path)

    assert exit_code == 0
    assert result["verdict"] == "pass"
    # allowlist hit should skip the API call
    assert call_count["n"] == 0, "API should not be called for known-valid allowlist tag"
