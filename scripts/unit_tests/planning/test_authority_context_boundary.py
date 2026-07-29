"""PRD 082 phase 4 — authority context boundary fixtures (R26) — Z,O,M,E,I."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

scripts = Path(__file__).resolve().parents[2]
if str(scripts) not in sys.path:
    sys.path.insert(0, str(scripts))

import planning_authority_context as pac
import planning_authority_reasons as par
from credentials.model import Principal
from repository_context import ENVELOPE_VERSION


def _envelope(root: Path, *, authority: str = "issue-store:github-issues") -> dict:
    return {
        "version": ENVELOPE_VERSION,
        "root": str(root.resolve()),
        "projectId": "fixture-project",
        "worktreeId": "phase-4",
        "planningAuthority": authority,
        "credentialRefs": ["github:default"],
        "memoryNamespace": "fixture",
        "policyOverrides": {},
        "runId": "run-boundary",
        "remote": "https://github.com/acme/demo.git",
        "repoSlug": "acme/demo",
        "destinationEndpoint": "https://api.github.com/user",
    }


class TestZeroEnvelopeKeys:
    def test_rejects_unpublished_envelope_keys(self, tmp_path: Path) -> None:
        envelope = _envelope(tmp_path)
        envelope["GITHUB_TOKEN"] = "secret"
        with pytest.raises(ValueError, match="unpublished keys"):
            pac.validate_envelope(envelope)


class TestOneTaxonomyMapping:
    @pytest.mark.parametrize(
        ("probe", "expected_state", "expected_reason"),
        [
            (pac.PROBE_VERDICT_RESOLVED, "online", None),
            (pac.PROBE_VERDICT_EXPLICITLY_NO_AUTH, "read-only", par.REASON_STORE_UNAVAILABLE),
            (pac.PROBE_VERDICT_UNRESOLVED, "blocked", par.REASON_AMBIGUOUS_AUTHORITY),
            (pac.PROBE_VERDICT_TIMEOUT, "blocked", par.REASON_STORE_UNAVAILABLE),
        ],
    )
    def test_probe_verdict_maps_to_documented_authority_state(
        self,
        tmp_path: Path,
        probe: str,
        expected_state: str | None,
        expected_reason: str | None,
    ) -> None:
        signals = pac.map_probe_verdict(probe)
        if expected_state:
            assert signals.authority_state_hint == expected_state
        if expected_reason:
            assert signals.reason_hint == expected_reason


class TestManyPrincipalMismatch:
    def test_principal_mismatch_maps_to_identity_reason(self, tmp_path: Path) -> None:
        left = Principal(profile="github", account="alice")
        right = Principal(profile="github", account="bob")
        signals = pac.map_probe_verdict(
            pac.PROBE_VERDICT_RESOLVED,
            principal=left,
            bound_principal=right,
        )
        assert signals.identity_mismatch is True
        assert signals.reason_hint == par.REASON_IDENTITY_MISMATCH


class TestBoundariesNoEnvironmentReads:
    def test_adapter_does_not_read_environment(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_should_not_be_read")
        envelope = _envelope(tmp_path)
        decision = pac.authority_from_context(
            envelope,
            probe_verdict=pac.PROBE_VERDICT_RESOLVED,
        )
        assert decision.configured == "issue-store"
        assert "GITHUB_TOKEN" not in json.dumps(decision.to_dict())


class TestIntegrationEnvelopeAuthority:
    def test_configured_backend_from_envelope_only(self, tmp_path: Path) -> None:
        envelope = _envelope(tmp_path, authority="in-repo-public")
        assert pac.configured_backend_from_envelope(envelope) == "in-repo-public"
        decision = pac.authority_from_context(
            envelope,
            probe_verdict=pac.PROBE_VERDICT_RESOLVED,
        )
        assert decision.configured == "in-repo-public"
