#!/usr/bin/env python3
"""CI pytest shard grouping for pr-test-plan manifest (PRD 054 TR13)."""
from __future__ import annotations

from typing import Any

REQUIRED_SHARD_COUNT = 4
ADVISORY_SHARD_COUNT = 1


def shard_job_name(classification: str, shard: int) -> str:
    return f"feat-test-plan-pytest-{classification}-shard-{shard}"


def assign_shard(classification: str, index: int, total: int) -> int:
    buckets = REQUIRED_SHARD_COUNT if classification == "required" else ADVISORY_SHARD_COUNT
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


def group_fixtures_for_ci(fixtures: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collapse manifest fixtures sharing ciJobName into one workflow job."""
    order: list[str] = []
    groups: dict[str, list[dict[str, Any]]] = {}
    for entry in fixtures:
        job_id = str(entry["ciJobName"])
        if job_id not in groups:
            order.append(job_id)
            groups[job_id] = []
        groups[job_id].append(entry)

    jobs: list[dict[str, Any]] = []
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
