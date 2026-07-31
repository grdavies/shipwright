#!/usr/bin/env python3
"""CI pytest shard grouping for pr-test-plan manifest (PRD 054 TR13)."""
from __future__ import annotations

import math
from collections import Counter
from pathlib import Path
from typing import Any

# Configurable target: aim for at most this many test files per required shard.
# Callers may override via compute_required_shard_count(count, target_per_shard=N).
TARGET_PER_SHARD: int = 40

# Minimum floor: never drop below 4 required shards regardless of suite size.
_MIN_REQUIRED_SHARDS: int = 4

ADVISORY_SHARD_COUNT = 1


def compute_required_shard_count(
    total_test_count: int,
    target_per_shard: int = TARGET_PER_SHARD,
) -> int:
    """Return the required shard count scaled to the suite size (R2).

    Formula: max(_MIN_REQUIRED_SHARDS, ceil(total_test_count / target_per_shard))

    The result is monotonically non-decreasing as *total_test_count* grows.
    At zero or negative input the floor (_MIN_REQUIRED_SHARDS = 4) is returned.
    The count first exceeds the floor when total_test_count > _MIN_REQUIRED_SHARDS * target_per_shard
    (with default settings: > 160 test files).
    """
    if total_test_count <= 0 or target_per_shard <= 0:
        return _MIN_REQUIRED_SHARDS
    return max(_MIN_REQUIRED_SHARDS, math.ceil(total_test_count / target_per_shard))


def shard_job_name(classification: str, shard: int) -> str:
    return f"feat-test-plan-pytest-{classification}-shard-{shard}"


def assign_shard(
    classification: str,
    index: int,
    total: int,
    shard_count: int | None = None,
) -> int:
    """Assign *index* (0-based) out of *total* entries to a shard bucket.

    *shard_count* overrides the required-shard count when provided; callers
    that know the live test-file count should pass
    ``compute_required_shard_count(live_count)`` here.  The default (None)
    falls back to ``compute_required_shard_count(0)`` which equals the
    _MIN_REQUIRED_SHARDS floor for backward compatibility.
    """
    if shard_count is None:
        shard_count = compute_required_shard_count(0)
    buckets = shard_count if classification == "required" else ADVISORY_SHARD_COUNT
    if total <= 0:
        return 1
    return (index * buckets // total) + 1


def pytest_paths_from_entry(entry: dict[str, Any]) -> list[str]:
    args = entry.get("args") or []
    if entry.get("script") != "scripts/test/run_pytest.py":
        return []
    paths: list[str] = []
    for token in args:
        if token == "-q":
            break
        if token.startswith("-"):
            continue
        paths.append(token)
    return paths


def _is_required_pytest_shard_entry(entry: dict[str, Any]) -> bool:
    job_id = str(entry.get("ciJobName") or "")
    return (
        entry.get("classification") == "required"
        and entry.get("script") == "scripts/test/run_pytest.py"
        and "pytest-required-shard" in job_id
    )


def expand_pytest_target(path: str, root: Path) -> list[str]:
    """Expand a manifest pytest path to concrete collect targets (files or node ids)."""
    if "::" in path:
        return [path]
    candidate = root / path
    if candidate.is_file():
        return [path.replace("\\", "/")]
    if candidate.is_dir():
        return sorted(
            str(item.relative_to(root)).replace("\\", "/")
            for item in candidate.rglob("test_*.py")
        )
    return [path]


def required_shard_number(ci_job_name: str) -> int | None:
    marker = "pytest-required-shard-"
    if marker not in ci_job_name:
        return None
    suffix = ci_job_name.rsplit("-", 1)[-1]
    if not suffix.isdigit():
        return None
    return int(suffix)


def partition_required_pytest_files(
    fixtures: list[dict[str, Any]],
    root: Path,
) -> tuple[dict[int, list[str]], dict[int, list[dict[str, Any]]]]:
    """Assign each test file/node-id to exactly one required shard (manifest order, first claim wins)."""
    shard_files: dict[int, list[str]] = {}
    shard_entries: dict[int, list[dict[str, Any]]] = {}
    claimed: set[str] = set()

    for entry in fixtures:
        if not _is_required_pytest_shard_entry(entry):
            continue
        shard = required_shard_number(str(entry["ciJobName"]))
        if shard is None:
            continue
        shard_entries.setdefault(shard, []).append(entry)
        for path in pytest_paths_from_entry(entry):
            for target in expand_pytest_target(path, root):
                if target in claimed:
                    continue
                claimed.add(target)
                shard_files.setdefault(shard, []).append(target)
    return shard_files, shard_entries


def duplication_factor(fixtures: list[dict[str, Any]], root: Path) -> float:
    """Assignments per unique file after disjoint partition. 1.0 when every file maps to one shard."""
    shard_files, _ = partition_required_pytest_files(fixtures, root)
    all_files: list[str] = []
    for files in shard_files.values():
        all_files.extend(files)
    unique = len(set(all_files))
    if unique == 0:
        return 1.0
    return len(all_files) / unique


def group_fixtures_for_ci(
    fixtures: list[dict[str, Any]],
    *,
    root: Path | None = None,
) -> list[dict[str, Any]]:
    """Collapse manifest fixtures sharing ciJobName into one workflow job."""
    repo_root = root or Path.cwd()
    order: list[str] = []
    groups: dict[str, list[dict[str, Any]]] = {}
    for entry in fixtures:
        job_id = str(entry["ciJobName"])
        if job_id not in groups:
            order.append(job_id)
            groups[job_id] = []
        groups[job_id].append(entry)

    shard_files, shard_entries = partition_required_pytest_files(fixtures, repo_root)
    jobs: list[dict[str, Any]] = []
    for job_id in order:
        entries = groups[job_id]
        head = entries[0]
        classification = head.get("classification", "required")

        if _is_required_pytest_shard_entry(head):
            shard = required_shard_number(job_id)
            files = shard_files.get(shard or -1, [])
            if not files:
                continue
            cmd = "python3 scripts/test/run_pytest.py " + " ".join(files) + " -q"
            jobs.append(
                {
                    "ciJobName": job_id,
                    "classification": classification,
                    "entries": shard_entries.get(shard or -1, entries),
                    "command": cmd,
                    "suiteIds": [entry["id"] for entry in shard_entries.get(shard or -1, entries)],
                }
            )
            continue

        if len(entries) == 1 and not pytest_paths_from_entry(head):
            jobs.append(
                {
                    "ciJobName": job_id,
                    "classification": classification,
                    "entries": entries,
                    "command": _single_entry_command(head),
                }
            )
            continue

        paths: list[str] = []
        seen: set[str] = set()
        for entry in entries:
            for path in pytest_paths_from_entry(entry):
                if path in seen:
                    continue
                seen.add(path)
                paths.append(path)
        if not paths:
            jobs.append(
                {
                    "ciJobName": job_id,
                    "classification": classification,
                    "entries": entries,
                    "command": _single_entry_command(head),
                }
            )
            continue
        cmd = "python3 scripts/test/run_pytest.py " + " ".join(paths) + " -q"
        jobs.append(
            {
                "ciJobName": job_id,
                "classification": classification,
                "entries": entries,
                "command": cmd,
                "suiteIds": [entry["id"] for entry in entries],
            }
        )
    return jobs


def _single_entry_command(entry: dict[str, Any]) -> str:
    script = entry["script"]
    args = entry.get("args") or []
    runner = "python3" if script.endswith((".py", ".test")) else "bash"
    return runner + " " + script + (" " + " ".join(args) if args else "")
