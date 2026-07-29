"""PRD 082 R32 — committed-tier confirmed-private probe fixtures."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2]
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import memory_visibility_probe as probe  # noqa: E402

_SAMPLE = "contact user@corp.example.com from 10.1.2.3"
_EMAIL = "user@corp.example.com"
_IP = "10.1.2.3"


def _probe(outcome: str) -> dict:
    return {"verdict": "ok", "outcome": outcome, "source": "test", "cached": False}


@pytest.mark.parametrize(
    "outcome",
    ["public", "inconclusive", "rate-limited", "absent", "unprobeable"],
)
def test_relaxation_detectors_removed_when_not_confirmed_private(outcome: str) -> None:
    redacted, record = probe.redact_with_visibility_probe(
        _SAMPLE,
        Path("."),
        probe=_probe(outcome),
    )
    assert _EMAIL not in redacted
    assert _IP not in redacted
    assert "[REDACTED:EMAIL]" in redacted
    assert "[REDACTED:INTERNAL_IP]" in redacted
    assert record["committedRelaxation"] is False
    assert record["visibilityProbe"]["effectiveDestination"] == "external"


def test_relaxation_detectors_retained_on_confirmed_private() -> None:
    redacted, record = probe.redact_with_visibility_probe(
        _SAMPLE,
        Path("."),
        probe=_probe("confirmed-private"),
    )
    assert _EMAIL in redacted
    assert _IP in redacted
    assert record["committedRelaxation"] is True
    assert record["visibilityProbe"]["effectiveDestination"] == "committed"


def test_private_to_public_flip_tightens_on_next_evaluation() -> None:
    private_redacted, _ = probe.redact_with_visibility_probe(
        _SAMPLE,
        Path("."),
        probe=_probe("confirmed-private"),
    )
    assert _EMAIL in private_redacted

    public_redacted, record = probe.redact_with_visibility_probe(
        _SAMPLE,
        Path("."),
        probe=_probe("public"),
    )
    assert _EMAIL not in public_redacted
    assert record["committedRelaxation"] is False


def test_probe_repository_visibility_honors_override(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("SW_MEMORY_VISIBILITY_PROBE", "rate-limited")
    result = probe.probe_repository_visibility(tmp_path)
    assert result["outcome"] == "rate-limited"
    assert result["cached"] is False


def test_probe_never_reports_cached(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("SW_MEMORY_VISIBILITY_PROBE", "confirmed-private")
    first = probe.probe_repository_visibility(tmp_path)
    monkeypatch.setenv("SW_MEMORY_VISIBILITY_PROBE", "public")
    second = probe.probe_repository_visibility(tmp_path)
    assert first["outcome"] == "confirmed-private"
    assert second["outcome"] == "public"
    assert first["cached"] is False
    assert second["cached"] is False


def test_effective_destination_maps_committed_to_external_unless_private() -> None:
    assert probe.effective_destination("committed", _probe("confirmed-private")) == "committed"
    assert probe.effective_destination("committed", _probe("public")) == "external"
    assert probe.effective_destination("external", _probe("confirmed-private")) == "external"
