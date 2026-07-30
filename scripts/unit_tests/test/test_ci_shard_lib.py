"""Disjoint pytest shard partitioning for pr-test-plan CI (PRD 083 R1)."""

from __future__ import annotations

import json
from pathlib import Path

import ci_shard_lib as csl


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
