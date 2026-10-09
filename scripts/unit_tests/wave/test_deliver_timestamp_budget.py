"""Aware durable timestamps must enforce the original deliver clock and watchdogs."""
from __future__ import annotations

import copy
from datetime import datetime, timezone
from pathlib import Path

import pytest
import wave_deliver_loop as loop

ORIGINAL_START = "2026-10-05T21:52:13.272712+00:00"
NOW = datetime(2026, 10, 9, 17, 44, 14, tzinfo=timezone.utc)


@pytest.fixture
def fixed_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    class FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW.astimezone(tz) if tz else NOW.replace(tzinfo=None)

    monkeypatch.setattr(loop, "datetime", FixedDatetime)


@pytest.mark.parametrize("timestamp", [
    ORIGINAL_START,
    "2026-10-05T21:52:13.272712Z",
    "2026-10-05T14:52:13.272712-07:00",
    "2026-10-06T03:22:13.272712+05:30",
])
def test_aware_fractional_timestamps_represent_original_start(timestamp, fixed_clock):
    expected = datetime(2026, 10, 5, 21, 52, 13, 272712, tzinfo=timezone.utc)
    assert loop.parse_ts(timestamp) == expected
    assert loop.age_seconds(timestamp) == (NOW - expected).total_seconds()


def test_existing_whole_second_z_remains_supported(fixed_clock):
    expected = datetime(2026, 10, 5, 21, 52, 13, tzinfo=timezone.utc)
    assert loop.parse_ts("2026-10-05T21:52:13Z") == expected
    assert loop.age_seconds("2026-10-05T21:52:13Z") == (NOW - expected).total_seconds()


@pytest.mark.parametrize("timestamp", [
    "", "not-a-timestamp", "2026-13-05T21:52:13Z", "2026-10-05",
    "2026-10-05T21:52:13", "2026-10-05T21:52:13.272712",
    "2026-10-05T21:52:13+25:00",
])
def test_invalid_and_naive_timestamps_have_no_age(timestamp, fixed_clock):
    assert loop.parse_ts(timestamp) is None
    assert loop.age_seconds(timestamp) is None


@pytest.mark.parametrize("timestamp", [
    ORIGINAL_START, "2026-10-05T14:52:13.272712-07:00",
    "2026-10-05T21:52:13Z",
])
def test_real_max_run_budget_uses_durable_original_start(timestamp, fixed_clock, tmp_path, monkeypatch):
    monkeypatch.setattr(loop, "load_workflow_config", lambda root: {
        "deliver": {"autonomy": {"maxRunMinutes": 5512, "maxIterations": 500}}
    })
    state = {"runStartedAt": timestamp, "iterationCount": 82,
             "budgetCounters": {"proposalIterationCount": 9, "executionIterationCount": 73},
             "noProgressStreak": 0}
    original = copy.deepcopy(state)
    assert loop.check_budget_halt(tmp_path, state) == "conductor:max-run-minutes-exceeded"
    for key, value in original.items():
        assert state[key] == value


def test_budget_does_not_halt_before_ceiling(fixed_clock, tmp_path, monkeypatch):
    monkeypatch.setattr(loop, "load_workflow_config", lambda root: {
        "deliver": {"autonomy": {"maxRunMinutes": 5513, "maxIterations": 500}}
    })
    assert loop.check_budget_halt(tmp_path, {"runStartedAt": ORIGINAL_START}) is None


def test_phase_watchdog_expires_fractional_start(fixed_clock):
    assert loop.phase_watchdog_stale({"startedAt": ORIGINAL_START}, 240 * 60)


def test_recent_aware_liveness_suppresses_old_phase_start(fixed_clock):
    assert not loop.phase_watchdog_stale({
        "startedAt": "2026-10-05T21:52:13Z",
        "livenessAt": "2026-10-09T10:44:13.500000-07:00",
    }, 240 * 60)


def test_real_driver_watchdog_uses_aware_heartbeat(fixed_clock, tmp_path):
    assert loop.check_watchdog(tmp_path, {"driverHeartbeatAt": ORIGINAL_START}) == "driver-heartbeat-stale"


def test_real_phase_watchdog_uses_aware_phase_start(fixed_clock, tmp_path, monkeypatch):
    monkeypatch.setattr(loop, "load_workflow_config", lambda root: {
        "deliver": {"watchdog": {"phaseTimeoutMinutes": 240}}
    })
    assert loop.check_watchdog(tmp_path, {"phases": {
        "21": {"status": "in-flight", "startedAt": ORIGINAL_START}
    }}) == "phase-timeout:21"


@pytest.mark.parametrize("timestamp", [
    "0001-01-01T00:00:00+01:00", "9999-12-31T23:59:59-01:00",
])
def test_aware_timestamp_outside_utc_range_has_no_age(timestamp, fixed_clock):
    assert loop.parse_ts(timestamp) is None
    assert loop.age_seconds(timestamp) is None
