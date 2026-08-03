"""Benchmark metric computation for hermetic memory-eval runs (PRD 082 R33)."""
from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fixtures import MemoryFixture, is_reserved_id

SCRIPT_DIR = Path(__file__).resolve().parent
SCRIPTS = SCRIPT_DIR.parents[1]
IN_REPO_SEARCH = SCRIPTS / "in-repo-memory-search.py"

SCENARIOS = (
    "memory_enabled",
    "memory_disabled",
    "stale",
    "contradictory",
    "cross_project",
)

# Fixed query strings for real in-repo search (R1 — no live provider / LLM).
SCENARIO_SEARCH_QUERIES: dict[str, str] = {
    "stale": "planning",
    "contradictory": "planning writes",
}

METRIC_NAMES = (
    "precision_at_k",
    "decision_adherence",
    "stale_memory_harm",
    "repeated_failure_rate",
    "token_cost",
    "cross_project_leakage",
)


@dataclass(frozen=True)
class ScenarioInput:
    scenario: str
    retrieved: list[MemoryFixture]
    expected_decision: str
    actual_decision: str
    token_cost: int = 0
    failures: int = 0
    attempts: int = 1
    foreign_hits: int = 0


def precision_at_k(retrieved: list[MemoryFixture], *, k: int = 3) -> float:
    if not retrieved:
        return 0.0
    top = retrieved[:k]
    relevant = sum(1 for item in top if item.corpus == "relevant" and not item.stale)
    return relevant / min(k, len(top))


def decision_adherence(expected: str, actual: str) -> float:
    return 1.0 if expected == actual else 0.0


def stale_memory_harm(retrieved: list[MemoryFixture], actual_decision: str) -> float:
    harm = 0.0
    for item in retrieved:
        if item.stale and actual_decision == item.decision_hint:
            harm += 1.0
    return harm


def repeated_failure_rate(failures: int, attempts: int) -> float:
    if attempts <= 0:
        return 0.0
    return failures / attempts


def cross_project_leakage(foreign_hits: int, retrieved_count: int) -> float:
    if retrieved_count <= 0:
        return 0.0
    return foreign_hits / retrieved_count


def build_fixture_index(corpora: dict[str, list[MemoryFixture]]) -> dict[str, MemoryFixture]:
    index: dict[str, MemoryFixture] = {}
    for fixtures in corpora.values():
        for item in fixtures:
            index[item.memory_id] = item
    return index


def search_retrieved_fixtures(
    store_path: Path,
    query: str,
    fixture_index: dict[str, MemoryFixture],
) -> list[MemoryFixture]:
    """Run in-repo search and map ranked hits back to seeded fixtures."""
    proc = subprocess.run(
        [
            sys.executable,
            str(IN_REPO_SEARCH),
            "search",
            "--store",
            str(store_path),
            "--query",
            query,
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(proc.stdout)
    retrieved: list[MemoryFixture] = []
    for row in payload.get("results", []):
        memory_id = str(row.get("id") or "")
        fixture = fixture_index.get(memory_id)
        if fixture is not None:
            retrieved.append(fixture)
    return retrieved


def actual_decision_from_stale_policy(
    retrieved: list[MemoryFixture],
    *,
    expected: str,
) -> str:
    """Stale hit decision_hint wins over non-stale hits in ranked order."""
    for item in retrieved:
        if item.stale:
            return item.decision_hint
    if retrieved:
        return retrieved[0].decision_hint
    return expected


def actual_decision_from_contradictory_policy(
    retrieved: list[MemoryFixture],
    *,
    expected: str,
) -> str:
    """Contradictory hit flips the expected decision via its decision_hint."""
    for item in retrieved:
        if item.contradictory:
            return item.decision_hint
    if retrieved:
        return retrieved[0].decision_hint
    return expected


def compute_metrics(run: ScenarioInput, *, k: int = 3) -> dict[str, float]:
    return {
        "precision_at_k": precision_at_k(run.retrieved, k=k),
        "decision_adherence": decision_adherence(run.expected_decision, run.actual_decision),
        "stale_memory_harm": stale_memory_harm(run.retrieved, run.actual_decision),
        "repeated_failure_rate": repeated_failure_rate(run.failures, run.attempts),
        "token_cost": float(run.token_cost),
        "cross_project_leakage": cross_project_leakage(run.foreign_hits, len(run.retrieved)),
    }


def _scenario_run_from_fixtures(
    scenario: str,
    fixtures: list[MemoryFixture],
    *,
    memory_enabled: bool,
    project_id: str,
    store_path: Path | None = None,
    fixture_index: dict[str, MemoryFixture] | None = None,
) -> ScenarioInput:
    if scenario == "memory_disabled" or not memory_enabled:
        return ScenarioInput(
            scenario=scenario,
            retrieved=[],
            expected_decision="no-memory-fallback",
            actual_decision="no-memory-fallback",
            token_cost=0,
            failures=0,
            attempts=1,
            foreign_hits=0,
        )

    retrieved = list(fixtures)
    if scenario in SCENARIO_SEARCH_QUERIES and store_path is not None and fixture_index is not None:
        retrieved = search_retrieved_fixtures(
            store_path,
            SCENARIO_SEARCH_QUERIES[scenario],
            fixture_index,
        )

    foreign_hits = sum(1 for item in retrieved if item.project_id != project_id)

    if scenario == "stale":
        expected = "use-transaction-coordinator"
        actual = actual_decision_from_stale_policy(retrieved, expected=expected)
        return ScenarioInput(
            scenario=scenario,
            retrieved=retrieved,
            expected_decision=expected,
            actual_decision=actual,
            token_cost=42,
            failures=1 if actual != expected else 0,
            attempts=2,
            foreign_hits=foreign_hits,
        )

    if scenario == "contradictory":
        expected = "read-only-when-blocked"
        actual = actual_decision_from_contradictory_policy(retrieved, expected=expected)
        return ScenarioInput(
            scenario=scenario,
            retrieved=retrieved,
            expected_decision=expected,
            actual_decision=actual,
            token_cost=55,
            failures=1 if actual != expected else 0,
            attempts=2,
            foreign_hits=foreign_hits,
        )

    if scenario == "cross_project":
        expected = "no-foreign-leak"
        actual = "rotate-credentials" if foreign_hits else expected
        return ScenarioInput(
            scenario=scenario,
            retrieved=retrieved,
            expected_decision=expected,
            actual_decision=actual,
            token_cost=30,
            failures=foreign_hits,
            attempts=1,
            foreign_hits=foreign_hits,
        )

    # memory_enabled default
    expected = "use-transaction-coordinator"
    actual = expected if any(item.corpus == "relevant" for item in retrieved) else "unknown"
    return ScenarioInput(
        scenario=scenario,
        retrieved=retrieved,
        expected_decision=expected,
        actual_decision=actual,
        token_cost=25,
        failures=0 if actual == expected else 1,
        attempts=1,
        foreign_hits=foreign_hits,
    )


def emit_scenario_metrics(
    scenario: str,
    fixtures: list[MemoryFixture],
    *,
    memory_enabled: bool = True,
    project_id: str = "eval-project",
    k: int = 3,
    store_path: Path | None = None,
    fixture_index: dict[str, MemoryFixture] | None = None,
) -> dict[str, Any]:
    if scenario not in SCENARIOS:
        raise ValueError(f"unknown scenario: {scenario}")
    for item in fixtures:
        if not is_reserved_id(item.memory_id):
            raise ValueError(f"non-reserved fixture id in scenario {scenario}: {item.memory_id}")

    run = _scenario_run_from_fixtures(
        scenario,
        fixtures,
        memory_enabled=memory_enabled,
        project_id=project_id,
        store_path=store_path,
        fixture_index=fixture_index,
    )
    metrics = compute_metrics(run, k=k)
    return {
        "scenario": scenario,
        "memoryEnabled": memory_enabled,
        "projectId": project_id,
        "metrics": metrics,
        "retrievedIds": [item.memory_id for item in run.retrieved],
    }


def emit_all_scenarios(
    corpora: dict[str, list[MemoryFixture]],
    *,
    project_id: str = "eval-project",
    k: int = 3,
    store_path: Path | None = None,
) -> dict[str, Any]:
    fixture_index = build_fixture_index(corpora)
    scenario_fixtures: dict[str, list[MemoryFixture]] = {
        "memory_enabled": corpora.get("relevant", []),
        "memory_disabled": [],
        "stale": corpora.get("stale", []) + corpora.get("relevant", [])[:1],
        "contradictory": corpora.get("contradictory", []),
        "cross_project": corpora.get("foreign_project", []),
    }
    runs = []
    for scenario in SCENARIOS:
        enabled = scenario != "memory_disabled"
        runs.append(
            emit_scenario_metrics(
                scenario,
                scenario_fixtures[scenario],
                memory_enabled=enabled,
                project_id=project_id,
                k=k,
                store_path=store_path,
                fixture_index=fixture_index,
            )
        )
    return {"scenarios": runs, "metricNames": list(METRIC_NAMES)}


def metrics_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
