#!/usr/bin/env python3
"""First-release exploration acceptance harness (PRD 331 R3, R32, R38, R40, R48)."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Callable, Mapping

SCRIPT_DIR = Path(__file__).resolve().parent.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from explore_command_contract import (  # noqa: E402
    CLOSED_ANTI_GOALS,
    validate_command_contract,
)
from exploration_brief import emit_brief  # noqa: E402
from exploration_engine import ExplorationEngine, destination_ready  # noqa: E402
from exploration_intelligence import (  # noqa: E402
    blocks_destination_progress,
    enrich_exploration_context,
)
from exploration_metrics import (  # noqa: E402
    EVENT_PREMATURE_DOC,
    EVENT_RESUME_FAILURE,
    EVENT_RESUME_SUCCESS,
    EVENT_SESSION_START,
    build_event,
    emit_metrics_report,
)
from exploration_projection import project_frontier  # noqa: E402
from exploration_store import ExplorationStore  # noqa: E402
from planning_readiness import compute_readiness  # noqa: E402
from status_collect import collect_exploration_summary  # noqa: E402
from workflow_extensions import (  # noqa: E402
    propose_doc_backward_route,
    propose_explore_forward_handoff,
    validate_doc_explore_handoff_contract,
)

ACCEPTANCE_REL = Path("core/sw-reference/exploration-acceptance.json")


class AcceptanceHarnessError(RuntimeError):
    """Acceptance scenario failure."""


def _repo_root(root: Path | None = None) -> Path:
    if root is not None:
        return root
    return SCRIPT_DIR.parent


def load_acceptance_config(root: Path | None = None) -> dict[str, Any]:
    path = _repo_root(root) / ACCEPTANCE_REL
    if not path.is_file():
        raise AcceptanceHarnessError("acceptance-config-missing")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise AcceptanceHarnessError("acceptance-config-invalid")
    return data


def _sample_map(*, blocking: bool = False, map_id: str = "acceptance-map") -> dict[str, Any]:
    unknowns = (
        [{"id": "unk-1", "statement": "Tier?", "classification": "blocking"}]
        if blocking
        else [{"id": "unk-deferred", "statement": "Optional viz", "classification": "deferred"}]
    )
    nodes: list[dict[str, Any]] = []
    if blocking:
        nodes.append(
            {
                "id": "q-1",
                "type": "question",
                "status": "open",
                "statement": "Which doc tier applies?",
            }
        )
    return {
        "id": map_id,
        "version": "ExplorationMap@v1",
        "revision": 1,
        "destination": {
            "statement": "Deliver first-release /sw-explore acceptance.",
            "nonCommittal": True,
        },
        "structuredFields": {
            "problem": "Operators need atomic first-release gates.",
            "outcomes": ["Core explore surfaces green", "Intel may degrade"],
            "successCriteria": ["Acceptance harness passes"],
            "unknowns": unknowns,
            "planningUnitCandidates": [
                {
                    "id": "unit-core",
                    "title": "Core explore release",
                    "rationale": "Atomic acceptance boundary.",
                }
            ],
        },
        "nodes": nodes,
        "provenance": {"createdAt": "2026-08-25T00:00:00Z", "source": "idea"},
    }


def scenario_entry_paths(root: Path) -> dict[str, Any]:
    contract = validate_command_contract(root)
    if contract["verdict"] != "pass":
        raise AcceptanceHarnessError(f"entry-paths-failed:{contract.get('failures')}")
    if len(CLOSED_ANTI_GOALS) != 5:
        raise AcceptanceHarnessError("anti-goals-incomplete")
    return {"scenario": "entry_paths", "verdict": "pass", "entryPaths": contract["entryPaths"]}


def scenario_map_readiness_brief(root: Path, tmp: Path) -> dict[str, Any]:
    store = ExplorationStore(tmp)
    engine = ExplorationEngine(store)
    started = engine.start_session(
        map_id="acceptance-core",
        destination_statement="Ship explore acceptance core.",
    )
    revision = int(started["map"]["revision"])
    for field, value in (
        ("problem", "Need readiness and brief."),
        ("outcomes", ["Readiness computed"]),
        ("successCriteria", ["Brief emitted"]),
    ):
        updated = engine.set_structured_field(
            "acceptance-core",
            field,
            value,
            expected_revision=revision,
        )
        revision = int(updated["revision"])
    loaded = store.read("acceptance-core")
    if loaded is None:
        raise AcceptanceHarnessError("map-not-found")
    document = loaded["map"]
    if not destination_ready(document):
        raise AcceptanceHarnessError("destination-not-ready")
    readiness = compute_readiness(document)
    if not readiness.get("readyForDocHandoff"):
        raise AcceptanceHarnessError("readiness-not-ready-for-doc")
    brief = emit_brief(document, readiness=readiness)
    if brief.get("version") != "ExplorationBrief@v1":
        raise AcceptanceHarnessError("brief-failed")
    return {
        "scenario": "map_readiness_brief",
        "verdict": "pass",
        "mapRevision": document.get("revision"),
        "readinessState": readiness.get("invalidation", {}).get("state"),
        "briefId": brief.get("id"),
        "started": started.get("verdict"),
    }


def scenario_authority_and_routing(root: Path) -> dict[str, Any]:
    handoff = validate_doc_explore_handoff_contract(root)
    if handoff.get("verdict") != "pass":
        raise AcceptanceHarnessError("handoff-contract-failed")
    blocking_map = _sample_map(blocking=True)
    backward = propose_doc_backward_route(blocking_map)
    if backward.get("verdict") != "propose":
        raise AcceptanceHarnessError("backward-route-missing")
    ready_map = _sample_map(blocking=False, map_id="acceptance-ready")
    readiness = compute_readiness(ready_map)
    forward = propose_explore_forward_handoff(ready_map, readiness=readiness)
    if forward.get("verdict") != "propose":
        raise AcceptanceHarnessError("forward-route-missing")
    return {
        "scenario": "authority_and_routing",
        "verdict": "pass",
        "backward": backward.get("destination"),
        "forward": forward.get("destination"),
    }


def scenario_degraded_intel(root: Path) -> dict[str, Any]:
    snapshot = enrich_exploration_context(root, _sample_map(), query="acceptance")
    if snapshot.get("blocking") is True:
        raise AcceptanceHarnessError("intel-blocked-core")
    if blocks_destination_progress(snapshot.get("intelligence") or {}):
        raise AcceptanceHarnessError("intel-blocks-destination")
    intel = snapshot.get("intelligence") or {}
    degraded = [
        key
        for key, value in intel.items()
        if isinstance(value, dict) and value.get("status") == "degraded"
    ]
    return {
        "scenario": "degraded_intel",
        "verdict": "pass",
        "destinationReady": snapshot.get("destinationReady"),
        "degradedHooks": degraded,
    }


def scenario_projection_status(root: Path, tmp: Path) -> dict[str, Any]:
    store = ExplorationStore(tmp)
    document = _sample_map(map_id="acceptance-projection")
    store.create(document)
    projection = project_frontier(document, provider_fn=None)
    if projection.get("verdict") != "pass":
        raise AcceptanceHarnessError("projection-failed")
    summary = collect_exploration_summary(root, "acceptance-projection", store=store)
    if summary.get("verdict") != "pass":
        raise AcceptanceHarnessError("status-summary-failed")
    local = projection.get("local") if isinstance(projection.get("local"), dict) else {}
    return {
        "scenario": "projection_status",
        "verdict": "pass",
        "textFallback": bool(local.get("textFallback")),
        "summaryKeys": sorted(summary.keys()),
    }


def scenario_quality_metrics() -> dict[str, Any]:
    events = [build_event(EVENT_SESSION_START, f"map-{index}", sequence=0) for index in range(10)]
    events.extend(
        build_event(EVENT_RESUME_SUCCESS, f"map-{index}", sequence=1) for index in range(10)
    )
    report = emit_metrics_report(events)
    evaluation = report["thresholdEvaluation"]
    if evaluation.get("verdict") != "pass":
        raise AcceptanceHarnessError(f"metrics-threshold-failed:{evaluation.get('failures')}")
    return {
        "scenario": "quality_metrics",
        "verdict": "pass",
        "aggregated": report["aggregated"],
    }


ScenarioFn = Callable[[Path], dict[str, Any]]


def _wrap_tmp(scenario: Callable[[Path, Path], dict[str, Any]]) -> ScenarioFn:
    def runner(root: Path) -> dict[str, Any]:
        import tempfile

        with tempfile.TemporaryDirectory(prefix="sw-explore-acceptance-") as tmpdir:
            return scenario(root, Path(tmpdir))

    return runner


NAMED_SCENARIOS: dict[str, ScenarioFn] = {
    "entry_paths": scenario_entry_paths,
    "map_readiness_brief": _wrap_tmp(scenario_map_readiness_brief),
    "authority_and_routing": scenario_authority_and_routing,
    "degraded_intel": scenario_degraded_intel,
    "projection_status": _wrap_tmp(scenario_projection_status),
    "quality_metrics": lambda root: scenario_quality_metrics(),
}


def evaluate_core_gates(
    config: Mapping[str, Any],
    scenario_results: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    checklist = config.get("checklist") or []
    failures: list[str] = []
    for item in checklist:
        if not isinstance(item, dict):
            continue
        gate_id = str(item.get("id") or "")
        blocking = bool(item.get("blocking", True))
        if not blocking:
            continue
        mapped = {
            "entry_paths": "entry_paths",
            "exploration_map": "map_readiness_brief",
            "planning_readiness": "map_readiness_brief",
            "exploration_brief": "map_readiness_brief",
            "authority_anti_goals": "authority_and_routing",
            "doc_explore_routing": "authority_and_routing",
            "projection_status": "projection_status",
            "quality_metrics": "quality_metrics",
        }.get(gate_id)
        if mapped and scenario_results.get(mapped, {}).get("verdict") != "pass":
            failures.append(gate_id)
    intel = scenario_results.get("degraded_intel", {})
    if intel.get("verdict") != "pass":
        failures.append("intelligence_hooks")
    return {"verdict": "pass" if not failures else "fail", "failures": failures}


def run_acceptance(root: Path | None = None) -> dict[str, Any]:
    repo = _repo_root(root)
    config = load_acceptance_config(repo)
    results: dict[str, dict[str, Any]] = {}
    failures: list[str] = []
    for name, runner in NAMED_SCENARIOS.items():
        try:
            results[name] = runner(repo)
        except AcceptanceHarnessError as exc:
            failures.append(f"{name}:{exc}")
            results[name] = {"scenario": name, "verdict": "fail", "error": str(exc)}
        except Exception as exc:  # pragma: no cover - surfaced in harness output
            failures.append(f"{name}:{exc}")
            results[name] = {"scenario": name, "verdict": "fail", "error": str(exc)}
    core = evaluate_core_gates(config, results)
    if core.get("verdict") != "pass":
        failures.extend(core.get("failures") or [])
    verdict = "pass" if not failures else "fail"
    return {
        "verdict": verdict,
        "action": "run-exploration-acceptance",
        "prd": config.get("prd"),
        "scenarios": results,
        "coreGates": core,
        "failures": failures,
    }


def main(argv: list[str] | None = None) -> int:
    from _sw.cli import run_module_main

    parser = argparse.ArgumentParser(description="Run /sw-explore first-release acceptance harness")
    parser.add_argument("--repo-root", type=Path, default=_repo_root())
    parser.add_argument("--json", action="store_true", help="Emit JSON report (default)")
    args = parser.parse_args(argv)
    report = run_acceptance(args.repo_root.resolve())
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report.get("verdict") == "pass" else 20


if __name__ == "__main__":
    from _sw.cli import run_module_main

    run_module_main(main)
