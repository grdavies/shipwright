#!/usr/bin/env python3
"""Codebase Intelligence status collector unit tests (PRD 280 R14; PRD 332 R8, R17)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[2]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from status_collect import (  # noqa: E402
    TRIAGE_RECOMMENDATION_AUTHORITY,
    collect_architecture_radar_last,
    collect_triage_recommendation_explain,
    collect_vocabulary_divergence_last,
)
from triage_evidence import (  # noqa: E402
    SIGNAL_ARCHITECTURE_RADAR,
    SIGNAL_STATE_ABSENT,
    SIGNAL_VERIFICATION_CAPABILITY,
    build_signal,
    build_triage_evidence,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]


def _intelligence_schema() -> dict:
    schema = json.loads((_REPO_ROOT / "core/sw-reference/config.schema.json").read_text(encoding="utf-8"))
    return schema["properties"]["planning"]["properties"]["intelligence"]


def _context_compression_schema() -> dict:
    schema = json.loads((_REPO_ROOT / "core/sw-reference/config.schema.json").read_text(encoding="utf-8"))
    return schema["properties"]["contextCompression"]


def _promotion_thresholds_schema() -> dict:
    schema = json.loads((_REPO_ROOT / "core/sw-reference/config.schema.json").read_text(encoding="utf-8"))
    return schema["definitions"]["capabilityPromotionFamilyThresholds"]


def test_architecture_radar_last_missing(tmp_path: Path) -> None:
    result = collect_architecture_radar_last(tmp_path)
    assert result["verdict"] == "pass"
    assert result["present"] is False
    assert result["readOnly"] is True


def test_architecture_radar_last_present(tmp_path: Path) -> None:
    radar_root = tmp_path / ".cursor" / "sw-architecture-radar"
    scan_dir = radar_root / "scan-1"
    scan_dir.mkdir(parents=True)
    candidates_path = scan_dir / "candidates.json"
    candidates_path.write_text(
        json.dumps(
            {
                "candidates": [
                    {
                        "modulePath": "scripts/foo",
                        "strength": 80,
                        "disposition": "gap-candidate",
                    }
                ]
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (radar_root / "last.json").write_text(
        json.dumps(
            {
                "scanId": "scan-1",
                "scannedAt": "2026-08-19T12:00:00Z",
                "scanDir": ".cursor/sw-architecture-radar/scan-1",
                "candidatesPath": ".cursor/sw-architecture-radar/scan-1/candidates.json",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    result = collect_architecture_radar_last(tmp_path)
    assert result["present"] is True
    assert result["scanId"] == "scan-1"
    assert result["candidateCount"] == 1
    assert result["topCandidates"][0]["modulePath"] == "scripts/foo"


def test_vocabulary_divergence_last_missing(tmp_path: Path) -> None:
    result = collect_vocabulary_divergence_last(tmp_path)
    assert result["verdict"] == "pass"
    assert result["present"] is False


def test_vocabulary_divergence_last_present(tmp_path: Path) -> None:
    artifact_dir = tmp_path / ".cursor" / "sw-vocabulary-divergence"
    artifact_dir.mkdir(parents=True)
    (artifact_dir / "last.json").write_text(
        json.dumps(
            {
                "checkedAt": "2026-08-19T12:00:00Z",
                "maxSeverity": "warn",
                "divergence": [{"concept": "account", "severity": "warn"}],
                "registryTermCount": 2,
                "humanGated": True,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    result = collect_vocabulary_divergence_last(tmp_path)
    assert result["present"] is True
    assert result["maxSeverity"] == "warn"
    assert result["divergenceCount"] == 1


def test_status_triage_explain_golden_absent_producers(tmp_path: Path) -> None:
    """status-triage-explain-golden: absent producers surface explicit dispositions."""
    result = collect_triage_recommendation_explain(tmp_path, description="small tweak", file_count=1)
    assert result["verdict"] == "pass"
    assert result["readOnly"] is True
    assert result["authority"] == TRIAGE_RECOMMENDATION_AUTHORITY
    assert result["productAuthority"] is False
    assert isinstance(result["absent"], list)
    assert len(result["absent"]) >= 1
    assert result["recommendation"]["appliedTier"] in {"quick", "standard", "full"}
    assert result["promotion"]["capabilityId"] == "triage.recommendation"
    assert result["promotion"]["state"] == "shadow"


def test_status_triage_explain_golden_veto_and_contributions(tmp_path: Path) -> None:
    """status-triage-explain-golden: veto reasons and weighted contributions are surfaced."""
    from unittest.mock import patch

    from triage_evidence import aggregate_weighted_advisory

    advisory = build_signal(
        SIGNAL_ARCHITECTURE_RADAR,
        weight=0.8,
        value=0.1,
        producer_path="scripts/architecture_radar.py",
    )
    safety = build_signal(
        SIGNAL_VERIFICATION_CAPABILITY,
        weight=0.3,
        value=0.0,
        safety_class="safety-floor",
        producer_path="scripts/host_doctor_lib.py",
    )
    absent = build_signal(
        "workflow-history",
        weight=0.4,
        state=SIGNAL_STATE_ABSENT,
        absent_reason="producer-unavailable",
    )
    signals = [advisory, safety, absent]
    evidence = build_triage_evidence(signals)
    explain = dict(evidence["explain"])
    explain["aggregation"] = aggregate_weighted_advisory(signals)
    evidence["explain"] = explain

    with patch("triage_evidence.aggregate_project_intelligence_for_triage", return_value=evidence):
        result = collect_triage_recommendation_explain(
            tmp_path,
            description="rename variable",
            file_count=1,
        )

    assert result["authority"] == "non-authoritative"
    assert result["recommendation"]["vetoTier"] == "full"
    assert "workflow-history" in result["absent"]
    assert any(item.get("id") == SIGNAL_ARCHITECTURE_RADAR for item in result["contributions"])


def test_intelligence_config_accepts_safe_defaults() -> None:
    """documentation-and-schema-parity: closed intelligence config defines bounded defaults."""
    intelligence = _intelligence_schema()
    triage = intelligence["properties"]["triageEvidence"]
    assert triage["additionalProperties"] is False
    weights = triage["properties"]["weights"]
    assert weights["additionalProperties"] is False
    assert weights["properties"]["architecture-radar"]["maximum"] == 1
    promotion = intelligence["properties"]["capabilityPromotion"]
    assert promotion["additionalProperties"] is False
    families = promotion["properties"]["families"]["properties"]
    assert "triage-recommendation" in families
    assert "exploration-inference" in families
    assert "context-compression" in families
    thresholds = _promotion_thresholds_schema()
    assert thresholds["properties"]["minQualifyingRuns"]["minimum"] == 1
    compression = _context_compression_schema()
    assert compression["properties"]["phase"]["default"] == "lossless"
    assert set(compression["properties"]["phase"]["enum"]) == {
        "lossless",
        "shadow-lossy",
        "active-lossy",
    }


def test_intelligence_config_rejects_unknown_fields() -> None:
    """accepted-resolution-golden: triageEvidence has no veto-override surface."""
    triage = _intelligence_schema()["properties"]["triageEvidence"]
    assert triage["additionalProperties"] is False
    allowed = set(triage["properties"])
    assert "overrideSafetyVeto" not in allowed
    assert "safetyVetoOverride" not in allowed
    assert "vetoOverride" not in allowed


def test_intelligence_config_rejects_unsafe_thresholds() -> None:
    """schema bounds promotion thresholds to safe ranges."""
    props = _promotion_thresholds_schema()["properties"]
    assert props["minQualifyingRuns"]["minimum"] >= 1
    assert props["maxFalsePositiveRate"]["maximum"] <= 1
    assert props["maxVetoConflictRate"]["maximum"] <= 1
    assert props["minShadowAgreement"]["minimum"] >= 0


def test_context_compression_rejects_invalid_phase() -> None:
    phase = _context_compression_schema()["properties"]["phase"]
    assert "override-active" not in phase["enum"]
    assert "active" not in phase["enum"]
