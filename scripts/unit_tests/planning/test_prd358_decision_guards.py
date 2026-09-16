"""PRD 358 D1/D2/D3/D9 — decision-log guards on frozen PRD + task list."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

import doc_format as df

REPO_ROOT = Path(__file__).resolve().parents[3]
PRD_358_DIR = (
    REPO_ROOT
    / (".cursor")
    / "planning-materialized"
    / "docs"
    / "prds"
    / "358-linear-issue-store-fidelity"
)
PRD_358_PATH = PRD_358_DIR / "358-prd-linear-issue-store-fidelity.md"
TASKS_358_PATH = PRD_358_DIR / "tasks-358-linear-issue-store-fidelity.md"
PRD_357_DIR = REPO_ROOT / "docs" / "prds" / "357-linear-issue-store-production-readiness"

PRD_358_ABSORB_GAP_UNITS = frozenset(
    {
        "GAP-468",
        "GAP-470",
        "GAP-471",
        "GAP-472",
    }
)
GAP_473_SLUG = "gap-473-doc-review-linear-guidance"
HOTFIX_ACCEPTANCE_IDS = tuple(f"AS{n}" for n in range(1, 10))


def _read(path: Path) -> str:
    if not path.is_file():
        pytest.skip(f"missing frozen artifact: {path.relative_to(REPO_ROOT)}")
    return path.read_text(encoding="utf-8")


def _absorb_gap_ids(prd_text: str) -> frozenset[str]:
    directives = df.parse_frontmatter_directives(prd_text)
    absorbs = directives.get("absorbs") or []
    out: set[str] = set()
    for item in absorbs:
        m = re.search(r"GAP-\d+", item, flags=re.IGNORECASE)
        if m:
            out.add(m.group(0).upper())
    return frozenset(out)


def _phase_headings(tasks_text: str) -> list[tuple[str, str]]:
    phases = df.extract_phases(tasks_text)
    return [(p["id"], p["title"]) for p in phases if p.get("id")]


@pytest.fixture(scope="module")
def prd_358_text() -> str:
    return _read(PRD_358_PATH)


@pytest.fixture(scope="module")
def tasks_358_text() -> str:
    return _read(TASKS_358_PATH)


def test_d1_guard_absorb_set_matches_operator_confirmed_four_gaps(prd_358_text: str) -> None:
    """D1 — one Standard PRD absorbs GAP-468/470/471/472 only."""
    assert _absorb_gap_ids(prd_358_text) == PRD_358_ABSORB_GAP_UNITS
    lowered = prd_358_text.lower()
    assert "does not amend frozen prd 357" in lowered or "does not amend prd 357" in lowered
    assert "gap-468" in lowered and "gap-472" in lowered


def test_d1_frozen_prd357_not_amended_on_integration_branch() -> None:
    """D1 — PRD 357 tree stays unchanged vs integration branch."""
    if not PRD_357_DIR.is_dir():
        pytest.skip("PRD 357 docs tree not present in this checkout")
    branch = (
        subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=REPO_ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    )
    integration = "feat/linear-issue-store-fidelity"
    diff = subprocess.run(
        [
            "git",
            "diff",
            "--name-only",
            integration,
            "--",
            "docs/prds/357-linear-issue-store-production-readiness",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    if diff.returncode != 0 and branch != integration:
        pytest.skip(f"cannot diff against {integration}")
    changed = [line for line in diff.stdout.splitlines() if line.strip()]
    assert changed == [], f"PRD 357 must not be amended: {changed}"


def test_d2_guard_gap_473_excluded_from_implementation_phases(tasks_358_text: str) -> None:
    """D2 — gap-473 is Quick and not a phase in this unit."""
    phases = _phase_headings(tasks_358_text)
    slugs = [slug for _, slug in phases]
    assert not any(GAP_473_SLUG in slug or "473" in slug for slug in slugs)
    assert GAP_473_SLUG in tasks_358_text.lower() or "gap-473" in tasks_358_text.lower()
    assert "stays out" in tasks_358_text.lower() or "stays quick" in tasks_358_text.lower()


def test_d2_tasks_do_not_schedule_gap_473_work(tasks_358_text: str) -> None:
    """D2 — no task row targets gap-473 implementation."""
    for line in tasks_358_text.splitlines():
        if not line.strip().startswith("- [ ]") or "473" not in line:
            continue
        lowered = line.lower()
        if "guard" in lowered and "exclusion" in lowered:
            continue
        assert "out" in lowered or "not" in lowered or "stays" in lowered


def test_d3_guard_operator_absorb_not_ranked_related_work_scan(
    prd_358_text: str, tasks_358_text: str
) -> None:
    """D3 — absorb set is operator-confirmed, not planning-related confirm-list."""
    assert "operator confirmed absorb" in prd_358_text.lower()
    assert "planning-related.py" in prd_358_text
    assert "confirm-list" in prd_358_text.lower()
    assert "index-incomplete" in prd_358_text.lower()
    phases = _phase_headings(tasks_358_text)
    assert not any("related-work" in title.lower() for _, title in phases)
    assert "operator-confirmed gap list" in tasks_358_text.lower()


def test_d9_guard_hotfix_bar_not_corpus_recert_phase(
    prd_358_text: str, tasks_358_text: str
) -> None:
    """D9 — hotfix close is AS1–AS9; corpus recert is bar B, not a listed phase."""
    success = prd_358_text
    assert "hotfix bar" in success.lower()
    for aid in HOTFIX_ACCEPTANCE_IDS:
        assert aid in success
    assert "migration-readiness bar" in success.lower() or "migration-readiness (bar b" in success.lower()
    phases = _phase_headings(tasks_358_text)
    slugs = " ".join(slug for _, slug in phases).lower()
    assert "corpus" not in slugs and "prd-19" not in slugs and "53-version" not in slugs
    assert "bar b" in tasks_358_text.lower() or "migration-readiness" in tasks_358_text.lower()
    assert "as1" in tasks_358_text.lower() and "as9" in tasks_358_text.lower()
