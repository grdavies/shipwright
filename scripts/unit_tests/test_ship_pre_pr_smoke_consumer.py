"""Consumer pre-PR smoke must execute the consumer's configured verifier."""
from __future__ import annotations

import json
import shlex
import sys
from pathlib import Path

from ship_pre_pr_smoke import run_pre_pr_smoke
import _runner


def _wrong_repo(*_args, **_kwargs):
    raise AssertionError("Shipwright pytest must not run for a consumer")


def _configure(root: Path, command: str) -> None:
    config = root / ".shipwright" / "workflow.config.json"
    config.parent.mkdir(parents=True)
    config.write_text(json.dumps({"verify": {"test": command}}), encoding="utf-8")


def test_consumer_uses_its_configured_verifier(tmp_path: Path, monkeypatch) -> None:
    marker = tmp_path / "verified.txt"
    code = "from pathlib import Path; Path('verified.txt').write_text('consumer')"
    _configure(tmp_path, f"{shlex.quote(sys.executable)} -c {shlex.quote(code)}")
    monkeypatch.setattr(_runner, "run_pytest_scope", _wrong_repo)

    exit_code, cause = run_pre_pr_smoke(tmp_path)

    assert (exit_code, cause) == (0, None)
    assert marker.read_text(encoding="utf-8") == "consumer"


def test_consumer_without_verifier_fails_closed(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(_runner, "run_pytest_scope", _wrong_repo)

    exit_code, cause = run_pre_pr_smoke(tmp_path)

    assert exit_code != 0
    assert cause == "pre-pr-smoke:consumer-verification-unconfigured"


def test_consumer_verifier_failure_blocks_smoke(tmp_path: Path) -> None:
    _configure(tmp_path, f"{shlex.quote(sys.executable)} -c {shlex.quote('raise SystemExit(7)')}")

    exit_code, cause = run_pre_pr_smoke(tmp_path)

    assert exit_code == 7
    assert cause == "pre-pr-smoke:consumer-exit-7"


def test_native_shipwright_repo_keeps_scoped_pytest(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "scripts" / "unit_tests").mkdir(parents=True)
    _configure(tmp_path, "exit 99")
    calls = []
    monkeypatch.setattr(_runner, "run_pytest_scope", lambda root, *, scope: calls.append((root, scope)) or 0)

    exit_code, cause = run_pre_pr_smoke(tmp_path)

    assert (exit_code, cause) == (0, None)
    assert calls == [(tmp_path, "phase")]
