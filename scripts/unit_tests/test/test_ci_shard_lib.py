"""Disjoint pytest shard partitioning and auto-scaling shard count for pr-test-plan CI (PRD 083 R1/R2)."""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

import ci_shard_lib as csl

# ---------------------------------------------------------------------------
# R2: compute_required_shard_count monotonicity and scaling tests
# ---------------------------------------------------------------------------

# Scaling threshold: count must exceed this value to produce more than 4 shards.
# With default TARGET_PER_SHARD=40: floor is 4, threshold = 4 * 40 = 160.
_SCALING_THRESHOLD = csl._MIN_REQUIRED_SHARDS * csl.TARGET_PER_SHARD


def test_compute_required_shard_count_floor_at_zero() -> None:
    assert csl.compute_required_shard_count(0) == csl._MIN_REQUIRED_SHARDS


def test_compute_required_shard_count_floor_at_negative() -> None:
    assert csl.compute_required_shard_count(-1) == csl._MIN_REQUIRED_SHARDS


def test_compute_required_shard_count_floor_below_threshold() -> None:
    for count in range(0, _SCALING_THRESHOLD + 1):
        result = csl.compute_required_shard_count(count)
        assert result == csl._MIN_REQUIRED_SHARDS, (
            f"expected floor {csl._MIN_REQUIRED_SHARDS} at count={count}, got {result}"
        )


def test_compute_required_shard_count_exceeds_floor_above_threshold() -> None:
    above = _SCALING_THRESHOLD + 1
    result = csl.compute_required_shard_count(above)
    assert result > csl._MIN_REQUIRED_SHARDS, (
        f"expected >4 shards at count={above}, got {result}"
    )


def test_compute_required_shard_count_monotonic() -> None:
    """Shard count must be non-decreasing as total_test_count grows."""
    counts = list(range(0, 400, 5))
    results = [csl.compute_required_shard_count(c) for c in counts]
    for i in range(1, len(results)):
        assert results[i] >= results[i - 1], (
            f"monotonicity violated: count {counts[i - 1]}->{counts[i]} "
            f"produced shards {results[i - 1]}->{results[i]}"
        )


@pytest.mark.parametrize(
    ("count", "target", "expected"),
    [
        (0, 40, 4),
        (40, 40, 4),
        (80, 40, 4),
        (160, 40, 4),
        (161, 40, 5),
        (200, 40, 5),
        (240, 40, 6),
        (1, 1, 4),
        (100, 100, 4),
        (101, 100, 4),
        (400, 100, 4),
        (401, 100, 5),
    ],
)
def test_compute_required_shard_count_formula(count: int, target: int, expected: int) -> None:
    assert csl.compute_required_shard_count(count, target_per_shard=target) == expected


def test_compute_required_shard_count_manifest_stays_at_floor(repo_root: Path) -> None:
    """Current manifest suite size is below the scaling threshold — shard count stays at 4."""
    manifest = repo_root / "core/sw-reference/pr-test-plan.manifest.json"
    fixtures = json.loads(manifest.read_text(encoding="utf-8"))["fixtures"]
    required_pytest = [
        f for f in fixtures
        if f.get("classification") == "required"
        and f.get("script") == "scripts/test/run_pytest.py"
    ]
    count = len(required_pytest)
    result = csl.compute_required_shard_count(count)
    assert result == csl._MIN_REQUIRED_SHARDS, (
        f"manifest has {count} required pytest fixtures (<= threshold {_SCALING_THRESHOLD}); "
        f"expected floor {csl._MIN_REQUIRED_SHARDS}, got {result}"
    )


# ---------------------------------------------------------------------------
# R1: Disjoint partition regression tests
# ---------------------------------------------------------------------------

def test_required_shard_duplication_factor_is_one(repo_root: Path) -> None:
    manifest = repo_root / "core/sw-reference/pr-test-plan.manifest.json"
    fixtures = json.loads(manifest.read_text(encoding="utf-8"))["fixtures"]
    factor = csl.duplication_factor(fixtures, repo_root)
    assert factor == 1.0


def test_disjoint_partition_no_file_in_multiple_required_shards(repo_root: Path) -> None:
    manifest = repo_root / "core/sw-reference/pr-test-plan.manifest.json"
    fixtures = json.loads(manifest.read_text(encoding="utf-8"))["fixtures"]
    shard_files, _ = csl.partition_required_pytest_files(fixtures, repo_root)
    seen: set[str] = set()
    for files in shard_files.values():
        overlap = seen.intersection(files)
        assert not overlap, f"files assigned to multiple shards: {sorted(overlap)[:5]}"
        seen.update(files)


def test_boundary_directory_overlap_resolves_to_single_shard(repo_root: Path) -> None:
    fixtures = [
        {
            "id": "a",
            "script": "scripts/test/run_pytest.py",
            "args": ["scripts/unit_tests/git", "-q"],
            "classification": "required",
            "ciJobName": "feat-test-plan-pytest-required-shard-1",
        },
        {
            "id": "b",
            "script": "scripts/test/run_pytest.py",
            "args": ["scripts/unit_tests/git/test_build_chain_hygiene.py", "-q"],
            "classification": "required",
            "ciJobName": "feat-test-plan-pytest-required-shard-2",
        },
    ]
    shard_files, _ = csl.partition_required_pytest_files(fixtures, repo_root)
    all_files = [f for files in shard_files.values() for f in files]
    assert len(all_files) == len(set(all_files))
    assert "scripts/unit_tests/git/test_build_chain_hygiene.py" in all_files


def test_empty_fixture_set_duplication_factor_trivial(repo_root: Path) -> None:
    assert csl.duplication_factor([], repo_root) == 1.0
