"""PRD 357 R13 — live Linear facade pilot receipt contract (hermetic)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

scripts = Path(__file__).resolve().parents[2]
if str(scripts) not in sys.path:
    sys.path.insert(0, str(scripts))

import planning_linear_facade_pilot as pilot


def test_receipt_rejects_linear_url_and_graphql_tokens() -> None:
    bad = {
        "version": 1,
        "verdict": "ok",
        "gate": pilot.RECEIPT_GATE,
        "ops": ["create"],
        "canonicalIdentityHash": "abc",
        "descriptionBytes": 10,
        "commentBytesMax": 0,
        "chunkCount": 1,
        "overscopedKeyCheck": "ok",
        "scopeCheck": {"verdict": "ok"},
        "credentialBlocked": False,
        "blockedCause": None,
        "leak": "https://linear.app/team/issue/FOO-1",
    }
    assert pilot.validate_live_facade_receipt(bad)["verdict"] == "fail"


def test_receipt_accepts_allowlisted_shape() -> None:
    good = {
        "version": 1,
        "verdict": "ok",
        "gate": pilot.RECEIPT_GATE,
        "ops": ["create", "read", "update", "materialize", "tombstone"],
        "canonicalIdentityHash": "a" * 64,
        "descriptionBytes": 1200,
        "commentBytesMax": 800,
        "chunkCount": 2,
        "overscopedKeyCheck": "ok",
        "scopeCheck": {"verdict": "ok", "projectId": "proj-pilot"},
        "credentialBlocked": False,
        "blockedCause": None,
    }
    assert pilot.validate_live_facade_receipt(good)["verdict"] == "ok"


def test_synthetic_body_loads_fixture(repo_root: Path) -> None:
    body = pilot.live_facade_pilot_synthetic_body(repo_root)
    assert "Multi" in body or "Live facade pilot" in body
    assert len(body) > 1000


def test_gate_blocks_without_pilot_project(repo_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from host_lib import load_workflow_config

    cfg = load_workflow_config(repo_root)
    cfg = json.loads(json.dumps(cfg))
    issues = cfg["planning"]["store"]["issues"]
    issues["liveFacadePilot"] = {"credentialRef": "planning-work"}
    issues["credentialRef"] = "planning-work"
    out = pilot.live_facade_pilot_gate(repo_root, cfg, skip_live=True)
    assert out["verdict"] in {"blocked", "fail"}
    assert out.get("blockedCause")
