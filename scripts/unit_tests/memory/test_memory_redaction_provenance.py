"""PRD 082 R29/R32 — redaction provenance and egress enforcement fixtures."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2]
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import memory_envelope_v2 as env  # noqa: E402
import memory_redaction_provenance as prov  # noqa: E402


def _envelope(**overrides: object) -> dict:
    doc = env.new_envelope(
        stable_id="mem-egress-1",
        project_id="shipwright",
        category="learning",
        sensitivity="internal",
    )
    doc.update(overrides)
    return doc


def test_missing_redaction_record_blocks_egress(tmp_path: Path) -> None:
    envelope = _envelope(appliedRedaction=env.empty_applied_redaction())
    result = prov.enforce_egress(
        envelope,
        egress_point="memory-sync",
        destination_tier="cross-project",
        root=tmp_path,
    )
    assert result["verdict"] == "fail"
    assert result["cause"] == "egress:missing-redaction-provenance"
    assert result["treatedAsUnredacted"] is True
    journal = prov.load_egress_refusal_journal(tmp_path)
    assert len(journal["entries"]) == 1
    entry = journal["entries"][0]
    assert entry["destinationPolicyId"] == prov.DEFAULT_DESTINATION_POLICY_ID
    assert entry["destinationPolicyVersion"] == prov.DEFAULT_DESTINATION_POLICY_VERSION
    assert entry["cause"] == "egress:missing-redaction-provenance"


def test_complete_provenance_record_fields_are_distinct_from_sensitivity() -> None:
    secret = "ghp_" + "A" * 36
    record = prov.build_applied_redaction_record(destination_tier="external", text=secret)
    assert record["applied"] is True
    assert record["destinationTierApplied"] == "external"
    assert isinstance(record["patternSetVersion"], str)
    assert record["substitutionCount"] >= 1
    envelope = _envelope(appliedRedaction=record, sensitivity="secret")
    assert envelope["sensitivity"] == "secret"
    assert envelope["appliedRedaction"]["destinationTierApplied"] == "external"


def test_stricter_destination_re_redacts_when_payload_present() -> None:
    secret = "ghp_" + "A" * 36
    record = prov.build_applied_redaction_record(destination_tier="local", text=secret)
    envelope = _envelope(appliedRedaction=record)
    result = prov.enforce_egress(
        envelope,
        egress_point="cross-project-copy",
        destination_tier="cross-project",
        payload_text=secret,
        allow_reredact=True,
    )
    assert result["verdict"] == "pass"
    assert result["action"] == "re-redacted"
    assert result["destinationTierApplied"] == "cross-project"
    assert "ghp_" not in result["payloadText"]
    assert result["envelope"]["appliedRedaction"]["destinationTierApplied"] == "cross-project"


def test_stricter_destination_refuses_without_payload(tmp_path: Path) -> None:
    secret = "ghp_" + "A" * 36
    record = prov.build_applied_redaction_record(destination_tier="local", text=secret)
    envelope = _envelope(appliedRedaction=record)
    result = prov.enforce_egress(
        envelope,
        egress_point="memory-sync",
        destination_tier="cross-project",
        root=tmp_path,
        allow_reredact=False,
    )
    assert result["verdict"] == "fail"
    assert result["cause"] == "egress:stricter-destination-refused"
    entry = prov.load_egress_refusal_journal(tmp_path)["entries"][0]
    assert entry["destinationPolicyId"] == prov.DEFAULT_DESTINATION_POLICY_ID
    assert entry["destinationPolicyVersion"] == prov.DEFAULT_DESTINATION_POLICY_VERSION
    assert entry["destinationTier"] == "cross-project"


def test_same_or_looser_destination_allows_egress() -> None:
    secret = "ghp_" + "A" * 36
    record = prov.build_applied_redaction_record(destination_tier="external", text=secret)
    envelope = _envelope(appliedRedaction=record)
    result = prov.enforce_egress(
        envelope,
        egress_point="memory-sync",
        destination_tier="committed",
    )
    assert result["verdict"] == "pass"
    assert result["action"] == "allow"
