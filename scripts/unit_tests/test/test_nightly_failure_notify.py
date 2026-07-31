"""Nightly failure triage-owner notification (PRD 083 R8)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import patch

import pytest


def _load_nightly_failure_notify(repo_root: Path):
    path = repo_root / "scripts" / "nightly-failure-notify.py"
    spec = importlib.util.spec_from_file_location("nightly_failure_notify", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["nightly_failure_notify"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def nfn(repo_root: Path):
    return _load_nightly_failure_notify(repo_root)


def test_notify_fires_with_nonempty_owner(nfn, repo_root) -> None:
    calls: list[dict] = []

    def fake_capture(_root, **kwargs):
        calls.append(kwargs)
        return {"unitId": "gap-999", "action": "gap-capture", "deduped": False}

    payload = {
        "job": "verify-scheduled-full-plus-integration",
        "workflowRunId": "123456",
        "repository": "grdavies/shipwright",
        "conclusion": "failure",
    }

    with patch.object(nfn.pgc, "capture_gap", side_effect=fake_capture):
        result = nfn.notify_nightly_failure(repo_root, payload, dry_run=True, dedupe=False)

    assert result["verdict"] == "pass"
    assert result["owner"]
    assert calls
    assert result["owner"] in calls[0]["problem"]


def test_malformed_payload_still_resolves_owner(nfn, repo_root) -> None:
    with patch.object(nfn.pgc, "capture_gap", return_value={"action": "gap-capture"}):
        result = nfn.notify_nightly_failure(repo_root, {}, dry_run=True, dedupe=False)
    assert result["owner"]


def test_resolve_triage_owner_from_registry(nfn, repo_root) -> None:
    owner = nfn.resolve_triage_owner(repo_root)
    assert owner == "platform-ops"


def test_cli_dry_run_emits_owner(nfn, repo_root, tmp_path, capsys) -> None:
    payload_path = tmp_path / "payload.json"
    payload_path.write_text('{"job": "verify-scheduled-full-plus-integration"}', encoding="utf-8")

    with patch.object(nfn.pgc, "capture_gap", return_value={"action": "gap-capture"}):
        with pytest.raises(SystemExit) as exc:
            nfn.main(
                [
                    "--root",
                    str(repo_root),
                    "--payload-file",
                    str(payload_path),
                    "--dry-run",
                    "--no-dedupe",
                ]
            )
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert '"owner": "platform-ops"' in out
