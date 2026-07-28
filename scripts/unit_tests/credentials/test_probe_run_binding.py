"""Probe run-binding tests (PRD 080 13.3 / R3) — O,S,B,E."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from credentials.identity_probe import (
    PROBE_TTL_CACHE_REJECTED,
    IdentityProbe,
    IdentityProbeError,
    reject_ttl_cache,
)
from credentials.model import Principal


@dataclass(frozen=True, slots=True)
class _Ctx:
    run_id: str | None


class TestReuseWithinRun:
    def test_second_lookup_reuses_pinned_principal(self) -> None:
        probe = IdentityProbe()
        principal = Principal(profile="work", account="alice")
        context = _Ctx(run_id="run-reuse")

        first = probe.probe(context=context, observed=principal)
        assert first.blocked is False
        assert first.reused is False
        assert probe.invocation_count("run-reuse") == 1

        second = probe.probe(context=context, observed=None, expected=None)
        assert second.blocked is False
        assert second.reused is True
        assert second.principal == principal
        assert probe.invocation_count("run-reuse") == 2
        assert probe.pinned_principal("run-reuse") == principal


class TestReprobeOnNewRunId:
    def test_new_run_id_reprobes(self) -> None:
        probe = IdentityProbe()
        alice = Principal(profile="work", account="alice")
        bob = Principal(profile="work", account="bob")

        first = probe.probe(run_id="run-a", observed=alice)
        assert first.reused is False
        assert first.principal == alice

        second = probe.probe(run_id="run-b", observed=bob)
        assert second.reused is False
        assert second.principal == bob
        assert probe.pinned_principal("run-a") == alice
        assert probe.pinned_principal("run-b") == bob
        assert probe.invocation_count("run-a") == 1
        assert probe.invocation_count("run-b") == 1

        # Same run still reuses; new run does not inherit.
        again_a = probe.probe(run_id="run-a")
        assert again_a.reused is True
        assert again_a.principal == alice


class TestTtlCacheRejected:
    def test_ttl_cache_write_is_rejected(self) -> None:
        probe = IdentityProbe()
        principal = Principal(profile="work", account="alice")
        probe.probe(run_id="run-ttl", observed=principal)

        with pytest.raises(IdentityProbeError) as exc:
            probe.write_ttl_cache(run_id="run-ttl", principal=principal, ttl_seconds=300)
        assert exc.value.code == PROBE_TTL_CACHE_REJECTED
        assert "TTL" in exc.value.hint or "TOCTOU" in exc.value.hint

        with pytest.raises(IdentityProbeError) as exc2:
            probe.cache_verdict_with_ttl(verdict="allow", ttl_seconds=60)
        assert exc2.value.code == PROBE_TTL_CACHE_REJECTED

        with pytest.raises(IdentityProbeError) as exc3:
            reject_ttl_cache(registry=probe, ttl_seconds=120)
        assert exc3.value.code == PROBE_TTL_CACHE_REJECTED

        # Pin remains run-bound; rejection did not invent a time-based grant.
        assert probe.pinned_principal("run-ttl") == principal
        reused = probe.probe(run_id="run-ttl")
        assert reused.reused is True
        assert reused.blocked is False
