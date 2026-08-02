#!/usr/bin/env python3
"""CI pytest shard grouping for pr-test-plan manifest (PRD 054 TR13 / PRD 088)."""
from __future__ import annotations

import hashlib
import math
from pathlib import Path
from typing import Any

# Configurable target: aim for at most this many test files per required shard.
# Callers may override via compute_required_shard_count(count, target_per_shard=N).
TARGET_PER_SHARD: int = 40

# Hard ceiling on required shard fan-out (PRD 088 R3/D1). Kept beside TARGET_PER_SHARD.
MAX_REQUIRED_SHARDS: int = 12

# Minimum floor: never drop below 4 required shards regardless of suite size
# (unless the unique file count is smaller — see shard_count_for_file_set).
_MIN_REQUIRED_SHARDS: int = 4

ADVISORY_SHARD_COUNT = 1

# Lamping & Veach jump consistent hash multiplier (uint64).
_JUMP_HASH_MULTIPLIER = 2862933555777941757


def compute_required_shard_count(
    total_test_count: int,
    target_per_shard: int = TARGET_PER_SHARD,
) -> int:
    """Return the required shard count scaled to the suite size (R2 / PRD 088 R3).

    Formula: min(MAX_REQUIRED_SHARDS, max(_MIN_REQUIRED_SHARDS,
              ceil(total_test_count / target_per_shard)))

    The result is monotonically non-decreasing as *total_test_count* grows until
    the MAX_REQUIRED_SHARDS cap. At zero or negative input the floor
    (_MIN_REQUIRED_SHARDS = 4) is returned.
    """
    if total_test_count <= 0 or target_per_shard <= 0:
        return _MIN_REQUIRED_SHARDS
    scaled = max(_MIN_REQUIRED_SHARDS, math.ceil(total_test_count / target_per_shard))
    return min(MAX_REQUIRED_SHARDS, scaled)


def shard_count_for_file_set(file_count: int) -> int:
    """N for an expanded unique file set: min(compute_required_shard_count, len(files))."""
    if file_count <= 0:
        return 0
    return min(compute_required_shard_count(file_count), file_count)


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

    Note: required pytest workflow membership uses ``partition_files_sticky``;
    this helper remains for advisory / legacy index-based callers.
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


def _is_required_pytest_entry(entry: dict[str, Any]) -> bool:
    return (
        entry.get("classification") == "required"
        and entry.get("script") == "scripts/test/run_pytest.py"
    )


def _is_required_pytest_shard_entry(entry: dict[str, Any]) -> bool:
    job_id = str(entry.get("ciJobName") or "")
    return _is_required_pytest_entry(entry) and "pytest-required-shard" in job_id


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


def _path_key(path: str) -> int:
    digest = hashlib.sha256(path.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big")


def jump_consistent_hash(key: int, num_buckets: int) -> int:
    """Jump consistent hash (Lamping & Veach) → bucket in ``[0, num_buckets)``."""
    if num_buckets <= 0:
        raise ValueError("num_buckets must be positive")
    key &= 0xFFFFFFFFFFFFFFFF
    b = -1
    j = 0
    while j < num_buckets:
        b = j
        key = (key * _JUMP_HASH_MULTIPLIER + 1) & 0xFFFFFFFFFFFFFFFF
        j = int((b + 1) * (1 << 31) / ((key >> 33) + 1))
    return int(b)


def _home_shard(path: str, shard_count: int) -> int:
    """Sticky home shard in ``1..shard_count`` (jump consistent hash)."""
    return jump_consistent_hash(_path_key(path), shard_count) + 1


def partition_files_sticky(files: list[str], shard_count: int) -> dict[int, list[str]]:
    """Path-hash ordered striping with exact floor/ceil balance (PRD 088 R1/R2/R4).

    Files are ordered by SHA-256 path key (sticky total order). Contiguous
    strips sized to ``[floor(n/N), ceil(n/N)]`` yield an exhaustive, disjoint,
    optimally balanced partition. Home affinity (``_home_shard``) is jump
    consistent hashing — zero remapping of homes when N is unchanged; the
    strip projection may move at most ``N-1`` existing files across strip
    boundaries when one file is inserted (boundary shift), never a full
    round-robin reshuffle.

    Empty shards are a hard error when files remain.
    """
    if shard_count <= 0:
        return {}
    unique = sorted(set(files), key=lambda p: (_path_key(p), p))
    buckets: dict[int, list[str]] = {i: [] for i in range(1, shard_count + 1)}
    if not unique:
        return buckets

    n = len(unique)
    lo = n // shard_count
    rem = n % shard_count
    # First ``rem`` shards get ceil (=lo+1); the rest get floor (=lo).
    idx = 0
    for shard in range(1, shard_count + 1):
        take = lo + (1 if shard <= rem else 0)
        if take == 0:
            raise ValueError(
                f"empty required shard after partition (files={n}, N={shard_count})"
            )
        buckets[shard] = unique[idx : idx + take]
        idx += take
    if idx != n:
        raise RuntimeError("sticky strip partition failed to cover all files")

    hi = lo + (1 if rem else 0)
    for shard, members in buckets.items():
        if not (lo <= len(members) <= hi):
            raise ValueError(
                f"shard {shard} size {len(members)} outside [{lo}, {hi}] "
                f"(files={n}, N={shard_count})"
            )
    return buckets


def collect_required_pytest_files(
    fixtures: list[dict[str, Any]],
    root: Path,
) -> list[str]:
    """Expand required pytest manifest targets to a unique sorted file/node-id set."""
    claimed: set[str] = set()
    for entry in fixtures:
        if not _is_required_pytest_entry(entry):
            continue
        for path in pytest_paths_from_entry(entry):
            for target in expand_pytest_target(path, root):
                claimed.add(target)
    return sorted(claimed)


def partition_required_pytest_files(
    fixtures: list[dict[str, Any]],
    root: Path,
) -> tuple[dict[int, list[str]], dict[int, list[dict[str, Any]]]]:
    """Assign each expanded required pytest target to exactly one shard (sticky).

    Manifest ``ciJobName`` labels are not assignment authority (PRD 088 R2).
    """
    files = collect_required_pytest_files(fixtures, root)
    shard_count = shard_count_for_file_set(len(files))
    shard_files = partition_files_sticky(files, shard_count)

    file_to_shard: dict[str, int] = {}
    for shard, members in shard_files.items():
        for path in members:
            file_to_shard[path] = shard

    shard_entries: dict[int, list[dict[str, Any]]] = {i: [] for i in range(1, shard_count + 1)}
    seen_entry_ids: dict[int, set[str]] = {i: set() for i in range(1, shard_count + 1)}
    for entry in fixtures:
        if not _is_required_pytest_entry(entry):
            continue
        entry_id = str(entry.get("id") or id(entry))
        touched: set[int] = set()
        for path in pytest_paths_from_entry(entry):
            for target in expand_pytest_target(path, root):
                shard = file_to_shard.get(target)
                if shard is not None:
                    touched.add(shard)
        for shard in sorted(touched):
            if entry_id in seen_entry_ids[shard]:
                continue
            seen_entry_ids[shard].add(entry_id)
            shard_entries[shard].append(entry)
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
    """Collapse manifest fixtures into workflow jobs; synthesize required shards 1..N."""
    repo_root = root or Path.cwd()
    shard_files, shard_entries = partition_required_pytest_files(fixtures, repo_root)
    jobs: list[dict[str, Any]] = []

    for shard in sorted(shard_files):
        files = shard_files[shard]
        if not files:
            raise ValueError(
                f"refusing empty required shard {shard} while synthesizing 1..{len(shard_files)}"
            )
        job_id = shard_job_name("required", shard)
        entries = shard_entries.get(shard, [])
        cmd = "python3 scripts/test/run_pytest.py " + " ".join(files) + " -q"
        jobs.append(
            {
                "ciJobName": job_id,
                "classification": "required",
                "entries": entries,
                "command": cmd,
                "suiteIds": [entry["id"] for entry in entries if "id" in entry],
            }
        )

    order: list[str] = []
    groups: dict[str, list[dict[str, Any]]] = {}
    for entry in fixtures:
        if _is_required_pytest_entry(entry):
            continue
        job_id = str(entry["ciJobName"])
        if job_id not in groups:
            order.append(job_id)
            groups[job_id] = []
        groups[job_id].append(entry)

    for job_id in order:
        entries = groups[job_id]
        head = entries[0]
        classification = head.get("classification", "required")

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
