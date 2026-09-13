"""TS5: memory observation gate (PRD 350 R21–R22, R24)."""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest import mock

import pytest

import memory_observation_gate as gate
import memory_preflight as preflight
import wave_journal as capture


def _enable(root: Path) -> None:
    cursor = root / ".cursor"
    cursor.mkdir(parents=True, exist_ok=True)
    (cursor / "workflow.config.json").write_text(
        json.dumps(
            {
                "capture": {
                    "enabled": True,
                    "gapKeywords": ["undocumented"],
                    "maxSummaryLength": 500,
                    "subAgentSidecarEnabled": True,
                    "maxFileSizeBytes": 52_428_800,
                }
            }
        ),
        encoding="utf-8",
    )


def test_observation_mode_writes_pending_human_review(tmp_path: Path) -> None:
    result = gate.write_observation(
        tmp_path,
        summary="learned undocumented helper",
        source_event_id="evt-1",
        run_id="run-obs",
    )
    assert result["status"] == gate.OBSERVATION_STATUS
    assert result["status"] == "pending_human_review"
    assert result["namespace"] == "observations"
    assert str(result["observationRef"]).startswith("observations/")
    path = Path(result["path"])
    assert path.is_file()
    body = json.loads(path.read_text(encoding="utf-8"))
    assert body["status"] == "pending_human_review"
    assert body["namespace"] == "observations"


def test_promotion_gate_blocks_rules_write_when_capture_run_set(tmp_path: Path) -> None:
    _enable(tmp_path)
    capture.ensure_capture_files(tmp_path, "run-gate")
    with mock.patch.dict(os.environ, {gate.CAPTURE_RUN_ENV: "run-gate"}):
        with pytest.raises(gate.PromotionGateError) as raised:
            gate.enforce_promotion_gate(
                namespace="rules",
                root=tmp_path,
                summary="attempted rule write",
            )
        assert raised.value.redirected is True
    # Redirected observation was written.
    obs = list(gate.observations_dir(tmp_path).glob("*.json"))
    assert obs, "expected redirected observation record"
    # Error logged to capture-errors.jsonl
    err_path = capture.capture_errors_path(tmp_path, "run-gate")
    assert err_path.is_file()
    assert "PromotionGateError" in err_path.read_text(encoding="utf-8")


def test_promotion_gate_exempt_without_capture_run(tmp_path: Path) -> None:
    with mock.patch.dict(os.environ, {}, clear=False):
        os.environ.pop(gate.CAPTURE_RUN_ENV, None)
        # Must not raise when audit/no-run context writes rules.
        gate.enforce_promotion_gate(namespace="rules", root=tmp_path, summary="audit")


def test_discovery_routes_observation_and_sets_ref(tmp_path: Path) -> None:
    _enable(tmp_path)
    eid = capture.emit_discovery(
        "found undocumented helper",
        "phase-3",
        "run-disc",
        "tool_output",
        "agent:disc",
        root=tmp_path,
    )
    events = capture.read_events("run-disc", root=tmp_path)
    assert len(events) == 1
    assert events[0]["eventId"] == eid
    ref = events[0].get("memoryObservationRef")
    assert isinstance(ref, str) and ref.startswith("observations/")


def test_memory_preflight_mode_observation_cli(tmp_path: Path) -> None:
    code = preflight.main(
        [
            "--root",
            str(tmp_path),
            "--mode",
            "observation",
            "--summary",
            "cli observation",
            "--run-id",
            "run-cli",
        ]
    )
    assert code == 0
    obs_dir = gate.observations_dir(tmp_path)
    assert any(obs_dir.glob("*.json"))
