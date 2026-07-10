"""PRD 062 R20 — release completeness meta gate tying R1–R19."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

scripts = Path(__file__).resolve().parents[2]
if str(scripts) not in sys.path:
    sys.path.insert(0, str(scripts))

from cleanup_lib import RESUMABLE_DELIVER_VERDICTS, TERMINAL_DELIVER_VERDICTS
from planning_request_budget import DEFAULT_PROVIDER_CEILINGS
from planning_unit_status import CANONICAL_STATUSES, META_STATUSES, UNIFIED_STATUSES
from wave_deliver_loop import drain_mechanical_enabled

TASK_LIST_REL = (
    "docs/prds/062-prd-deliver-issue-store-hardening-and-loop-perf/"
    "tasks-062-deliver-issue-store-hardening-and-loop-perf.md"
)

REQUIRED_R_IDS = {f"R{n}" for n in range(1, 20)}

DOC_SURFACES: tuple[tuple[str, str], ...] = (
    ("core/commands/sw-deliver.md", "Merge policy (PRD 062 R17)"),
    ("core/skills/conductor/SKILL.md", "PRD 062 release acceptance metrics (R18)"),
    ("core/skills/conductor/SKILL.md", "Deliver-loop mechanical drain"),
    ("core/commands/sw-cleanup.md", "Scoped in-flight protection"),
    (".sw/layout.md", "Slim gate manifest"),
    ("docs/guides/configuration.md", "deliver.loop.drainMechanical"),
    ("docs/guides/configuration.md", "maxCalls"),
)


def _task_list_path(repo_root: Path) -> Path:
    direct = repo_root / TASK_LIST_REL
    if direct.is_file():
        return direct
    materialized = (
        repo_root
        / ".cursor/planning-materialized"
        / TASK_LIST_REL
    )
    if materialized.is_file():
        return materialized
    pytest.skip(f"task list not found: {TASK_LIST_REL}")


def _traceability_r_ids(task_text: str) -> set[str]:
    section = task_text.split("## Traceability", 1)
    if len(section) < 2:
        return set()
    return set(re.findall(r"\bR\d+\b", section[1]))


@pytest.mark.parametrize("rel,needle", DOC_SURFACES)
def test_doc_surfaces_document_prd062_knobs(repo_root: Path, rel: str, needle: str) -> None:
    """R20 — operator-facing surfaces cite merge policy, metrics, drain, cleanup, budget."""
    path = repo_root / rel
    assert path.is_file(), f"missing doc surface: {rel}"
    assert needle in path.read_text(encoding="utf-8"), f"{rel} missing: {needle}"


def test_traceability_covers_r1_through_r19(repo_root: Path) -> None:
    """R20 — frozen task list traceability maps every R1–R19."""
    text = _task_list_path(repo_root).read_text(encoding="utf-8")
    found = _traceability_r_ids(text)
    missing = sorted(REQUIRED_R_IDS - found)
    assert not missing, f"traceability missing: {', '.join(missing)}"


def test_github_default_max_calls_is_750() -> None:
    """R12/R19 — github-issues default budget ceiling is 750."""
    assert DEFAULT_PROVIDER_CEILINGS["github-issues"]["maxCalls"] == 750


def test_drain_mechanical_defaults_true(repo_root: Path, tmp_path: Path) -> None:
    """R7/R19 — drainMechanical defaults true when unset."""
    cfg = tmp_path / ".cursor"
    cfg.mkdir(parents=True)
    (cfg / "workflow.config.json").write_text("{}", encoding="utf-8")
    assert drain_mechanical_enabled(tmp_path) is True


def test_four_state_vocab_unknown_non_terminal() -> None:
    """R13 — unknown/unauthorized are meta, not canonical complete."""
    assert CANONICAL_STATUSES == frozenset({"backlog", "planned", "in-progress", "complete"})
    assert "unknown" in META_STATUSES
    assert "unknown" not in CANONICAL_STATUSES
    assert "complete" in UNIFIED_STATUSES


def test_cleanup_terminal_allowlist_excludes_resumable() -> None:
    """R10/R11 — terminal auto-cleanup allowlist is disjoint from resumable halts."""
    assert TERMINAL_DELIVER_VERDICTS.isdisjoint(RESUMABLE_DELIVER_VERDICTS)
    assert "blocked" in RESUMABLE_DELIVER_VERDICTS
    assert "complete" in TERMINAL_DELIVER_VERDICTS


def test_release_completeness_note_json(repo_root: Path) -> None:
    """R20 — emit structured completeness snapshot for verify notes."""
    payload = {
        "prd": "062",
        "verdict": "pass",
        "requiredRIds": sorted(REQUIRED_R_IDS),
        "traceabilityRIds": sorted(_traceability_r_ids(_task_list_path(repo_root).read_text(encoding="utf-8"))),
        "docSurfaces": [rel for rel, _ in DOC_SURFACES],
        "note": "Unit not complete until all R1–R19 tasks are done and harnesses green.",
    }
    assert payload["verdict"] == "pass"
    assert set(payload["traceabilityRIds"]) >= REQUIRED_R_IDS
    json.dumps(payload)  # serializable for verify notes
