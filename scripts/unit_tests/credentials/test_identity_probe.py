"""Identity probe unit tests (PRD 080 13.2 / R3) — Z,O,E,I."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from credentials.identity_probe import (
    AUTHORITATIVE_AUTHZ,
    PROBE_NO_PRINCIPAL,
    IdentityProbe,
    IdentityProbeError,
    authorize_mutating_call,
)
from credentials.model import Principal


@dataclass(frozen=True, slots=True)
class _Ctx:
    run_id: str | None


class TestNoPrincipal:
    def test_absent_principal_blocks_before_mutating(self) -> None:
        probe = IdentityProbe()
        mutated = {"called": False}

        def mutate() -> str:
            mutated["called"] = True
            return "mutated"

        result = probe.probe(run_id="run-z", observed=None, expected=None)
        assert result.blocked is True
        assert result.principal is None
        assert result.code == PROBE_NO_PRINCIPAL
        assert result.report is not None
        assert "supply a resolved principal" in result.report
        assert result.authoritative_authorization == AUTHORITATIVE_AUTHZ

        with pytest.raises(IdentityProbeError) as exc:
            probe.authorize_mutating_call(mutate, run_id="run-z")
        assert exc.value.code == PROBE_NO_PRINCIPAL
        assert mutated["called"] is False


class TestOneMatchingPrincipal:
    def test_matching_principal_pins_and_allows_mutating_gate(self) -> None:
        probe = IdentityProbe()
        principal = Principal(profile="work", account="alice")
        context = _Ctx(run_id="run-one")
        mutated = {"called": False}

        result = probe.probe(context=context, observed=principal, expected=principal)
        assert result.blocked is False
        assert result.reused is False
        assert result.principal == principal
        assert probe.pinned_principal("run-one") == principal
        binding = probe.pin_into_context(context, principal)
        assert binding.principal == principal
        assert binding.run_id == "run-one"

        def mutate() -> str:
            mutated["called"] = True
            return "ok"

        assert (
            authorize_mutating_call(
                mutate,
                run_id="run-one",
                observed=principal,
                registry=probe,
            )
            == "ok"
        )
        assert mutated["called"] is True


class TestPrincipalMismatch:
    def test_mismatch_blocks_with_actionable_report_before_mutating(self) -> None:
        probe = IdentityProbe()
        expected = Principal(profile="work", account="alice")
        observed = Principal(profile="work", account="bob")
        mutated = {"called": False}

        result = probe.probe(run_id="run-mismatch", observed=observed, expected=expected)
        assert result.blocked is True
        assert result.code == "resolver-principal-mismatch"
        assert result.report is not None
        assert "alice" in result.report
        assert "bob" in result.report
        assert "Blocking before any mutating operation" in result.report
        assert probe.pinned_principal("run-mismatch") is None

        def mutate() -> str:
            mutated["called"] = True
            return "should-not-run"

        with pytest.raises(IdentityProbeError) as exc:
            probe.authorize_mutating_call(
                mutate,
                run_id="run-mismatch",
                observed=observed,
                expected=expected,
            )
        assert exc.value.code == "resolver-principal-mismatch"
        assert "Blocking before any mutating operation" in exc.value.report
        assert mutated["called"] is False
        assert result.authoritative_authorization == AUTHORITATIVE_AUTHZ
