#!/usr/bin/env python3
"""PRD 366 phase-1 fixture contracts — 2.22.0 leftover classification and witness policy."""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

PRD366_ALLOWED_REQUIREMENT_IDS = frozenset({"R4", "R5", "R6", "R7"})
PRD366_LEFTOVER_REGION_COUNT = 7
PRD366_GAP_UNIT_IDS = frozenset(
    {
        "gap-486-version-section-token-domain-rewrite",
        "gap-487-implicit-autolink-identity-comparison-mismatch",
        "gap-488-mixed-bold-inline-code-both-sides-unwrap",
        "gap-489-acceptance-criteria-underscore-full-line",
    }
)
PRD366_PRIVATE_PILOT_DIR = Path(
    ".shipwright/migrations/linear-20260914/pilot-2.22.0"
)
PRD366_PRIVATE_DIAGNOSIS = PRD366_PRIVATE_PILOT_DIR / "pilot-diagnosis-2.22.0.json"
PRD366_MARKDOWN_REPRO = PRD366_PRIVATE_PILOT_DIR / "markdown-repro-2.22.0.json"
PRD366_RUNTIME_RECHECK = PRD366_PRIVATE_PILOT_DIR / "runtime-recheck-2.22.0.json"
PRD366_INPUT_R6 = PRD366_PRIVATE_PILOT_DIR / "input-r6.md"
PRD366_READBACK_R6 = PRD366_PRIVATE_PILOT_DIR / "readback-r6.md"
COMMITTED_FAMILY_MAP = Path(
    "scripts/test/fixtures/linear/markdown-repro-2.22.0-family-map.json"
)
DEFAULT_STUCK_ISSUE_IDENTIFIER = "TIE-8"

FORBIDDEN_REDACTED_SUBSTRINGS = (
    "Authorization:",
    "Bearer ",
    "upsertDiscount",
    "listDiscounts",
    "Tierforge.dev",
    "linear.app/acme",
    "RED-1",
    "sw:token",
)


class WitnessUnavailableError(RuntimeError):
    """Raised when neither private 2.22.0 bytes nor a live TIE-8 re-read is available."""


class WitnessKind(str, Enum):
    PRIVATE_PILOT = "private-pilot"
    LIVE_TIE8 = "live-tie8"


@dataclass(frozen=True)
class WitnessSource:
    kind: WitnessKind
    repo_root: Path
    pilot_dir: Path | None = None

    def diagnosis_path(self) -> Path | None:
        if self.kind != WitnessKind.PRIVATE_PILOT or self.pilot_dir is None:
            return None
        return self.pilot_dir / "pilot-diagnosis-2.22.0.json"


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_family_map(data: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if data.get("version") != "2.22.0":
        errors.append("family-map version must be 2.22.0")
    leftovers = data.get("leftovers")
    if not isinstance(leftovers, list):
        errors.append("family-map leftovers must be a list")
        return errors
    if len(leftovers) != PRD366_LEFTOVER_REGION_COUNT:
        errors.append(
            f"family-map expects {PRD366_LEFTOVER_REGION_COUNT} leftover rows, got {len(leftovers)}"
        )
    seen_ids: set[str] = set()
    for idx, row in enumerate(leftovers):
        if not isinstance(row, dict):
            errors.append(f"leftovers[{idx}] must be an object")
            continue
        region_id = row.get("regionId")
        if not isinstance(region_id, str) or not region_id:
            errors.append(f"leftovers[{idx}] missing regionId")
        elif region_id in seen_ids:
            errors.append(f"duplicate regionId {region_id}")
        else:
            seen_ids.add(region_id)
        req = row.get("requirementId")
        if req not in PRD366_ALLOWED_REQUIREMENT_IDS:
            errors.append(
                f"leftovers[{idx}] requirementId {req!r} not in {sorted(PRD366_ALLOWED_REQUIREMENT_IDS)}"
            )
        gap = row.get("gapUnitId")
        if gap not in PRD366_GAP_UNIT_IDS:
            errors.append(
                f"leftovers[{idx}] gapUnitId must reference PRD 366 absorb set {sorted(PRD366_GAP_UNIT_IDS)}"
            )
        fixture_ref = row.get("redactedFixtureId")
        if not isinstance(fixture_ref, str) or not fixture_ref:
            errors.append(f"leftovers[{idx}] missing redactedFixtureId")
    return errors


def _diagnosis_leftover_rows(diagnosis: dict[str, Any]) -> list[dict[str, Any]]:
    leftovers = diagnosis.get("leftovers")
    if isinstance(leftovers, list):
        return [row for row in leftovers if isinstance(row, dict)]
    regions = diagnosis.get("regions")
    if isinstance(regions, list):
        return [row for row in regions if isinstance(row, dict)]
    return []


def validate_family_map_against_diagnosis(
    family_map: dict[str, Any], diagnosis: dict[str, Any]
) -> list[str]:
    """When private diagnosis bytes exist, every diagnosis row must be classified R4–R7."""
    errors: list[str] = []
    diag_rows = _diagnosis_leftover_rows(diagnosis)
    if not diag_rows:
        errors.append("diagnosis has no leftover rows to classify")
        return errors
    map_by_region: dict[str, dict[str, Any]] = {}
    for row in family_map.get("leftovers") or []:
        if isinstance(row, dict) and isinstance(row.get("regionId"), str):
            map_by_region[row["regionId"]] = row
    for idx, row in enumerate(diag_rows):
        region_id = row.get("regionId") or row.get("id")
        if not isinstance(region_id, str) or not region_id:
            errors.append(f"diagnosis row[{idx}] missing regionId/id")
            continue
        mapped = map_by_region.get(region_id)
        if mapped is None:
            errors.append(f"unclassified leftover region {region_id}")
            continue
        req = mapped.get("requirementId")
        if req not in PRD366_ALLOWED_REQUIREMENT_IDS:
            errors.append(f"region {region_id} maps to invalid requirementId {req!r}")
    extra = sorted(set(map_by_region) - {str(r.get("regionId") or r.get("id")) for r in diag_rows})
    if extra:
        errors.append(f"family-map references unknown diagnosis regions: {extra}")
    return errors


def private_pilot_tree_present(repo_root: Path) -> bool:
    root = Path(repo_root).resolve()
    diagnosis = root / PRD366_PRIVATE_DIAGNOSIS
    repro = root / PRD366_MARKDOWN_REPRO
    return diagnosis.is_file() and repro.is_file()


def private_pilot_tree_gitignored(repo_root: Path) -> bool:
    """True when the private pilot directory is not tracked (expected for CI)."""
    from subprocess import run

    rel = PRD366_PRIVATE_PILOT_DIR.as_posix()
    proc = run(
        ["git", "check-ignore", "-q", rel],
        cwd=repo_root,
        capture_output=True,
    )
    return proc.returncode == 0


def live_tie8_reread_available(repo_root: Path) -> bool:
    """Broker-only probe: live TIE-8 re-read is allowed when credentials resolve."""
    root = Path(repo_root).resolve()
    try:
        from credentials.model import ResolutionState
        from credentials.resolver import RepositoryContext, resolve
        from credentials.selector_store import load_selector_store
        from host_lib import load_workflow_config
        from planning_linear_facade_pilot import _pilot_section
    except ImportError:
        return False
    cfg = load_workflow_config(root)
    pilot = _pilot_section(cfg)
    if not pilot.get("enabled"):
        return False
    store = load_selector_store(root)
    if store is None:
        return False
    ctx = RepositoryContext(repo_root=root, remote_url=None)
    try:
        resolution = resolve(store, ctx, backend_id="linear")
    except Exception:
        return False
    return resolution.state == ResolutionState.OK and bool(resolution.token)


def resolve_witness_source(repo_root: Path) -> WitnessSource:
    """Prefer gitignored private 2.22.0 bytes; otherwise live TIE-8 re-read."""
    root = Path(repo_root).resolve()
    if private_pilot_tree_present(root):
        return WitnessSource(
            kind=WitnessKind.PRIVATE_PILOT,
            repo_root=root,
            pilot_dir=root / PRD366_PRIVATE_PILOT_DIR,
        )
    if live_tie8_reread_available(root):
        return WitnessSource(kind=WitnessKind.LIVE_TIE8, repo_root=root, pilot_dir=None)
    raise WitnessUnavailableError(
        "missing private 2.22.0 pilot bytes and live TIE-8 re-read unavailable"
    )


def require_witness_source(repo_root: Path) -> WitnessSource:
    """Fail closed when prove cannot use private bytes or live TIE-8."""
    return resolve_witness_source(repo_root)


def load_committed_family_map(repo_root: Path) -> dict[str, Any]:
    path = Path(repo_root).resolve() / COMMITTED_FAMILY_MAP
    if not path.is_file():
        raise FileNotFoundError(f"missing committed family map: {path}")
    return load_json(path)


def validate_redacted_families(data: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if data.get("version") != "2.22.0-redacted":
        errors.append("redacted families version must be 2.22.0-redacted")
    pairs = data.get("pairs")
    mutants = data.get("mutants")
    if not isinstance(pairs, list) or not pairs:
        errors.append("redacted families pairs must be a non-empty list")
    if not isinstance(mutants, list) or not mutants:
        errors.append("redacted families mutants must be a non-empty list")
    blob = json.dumps(data, ensure_ascii=False)
    for needle in FORBIDDEN_REDACTED_SUBSTRINGS:
        if needle in blob:
            errors.append(f"redacted fixture must not contain private corpus marker: {needle}")
    for label, rows in (("pairs", pairs), ("mutants", mutants)):
        if not isinstance(rows, list):
            continue
        for idx, row in enumerate(rows):
            if not isinstance(row, dict):
                errors.append(f"{label}[{idx}] must be an object")
                continue
            for key in ("id", "family", "requirementId", "submitted", "refetched"):
                if not isinstance(row.get(key), str) or not row.get(key):
                    errors.append(f"{label}[{idx}] missing {key}")
            if row.get("requirementId") not in PRD366_ALLOWED_REQUIREMENT_IDS:
                errors.append(f"{label}[{idx}] invalid requirementId")
    return errors


@dataclass(frozen=True)
class PreservedFullFixturePair:
    """Full preserved submit/readback witness for PRD 366 R8 (not redacted family excerpts)."""

    submitted: str
    refetched: str
    witness_kind: WitnessKind
    source_path: str


def _markdown_repro_pair(data: dict[str, Any]) -> tuple[str, str]:
    submitted = data.get("submitMarkdown") or data.get("submittedMarkdown") or data.get("submitted")
    refetched = data.get("refetchedMarkdown") or data.get("refetched")
    if not isinstance(submitted, str) or not submitted.strip():
        raise ValueError("witness fixture missing submitMarkdown")
    if not isinstance(refetched, str) or not refetched.strip():
        raise ValueError("witness fixture missing refetchedMarkdown")
    return submitted, refetched


def load_preserved_full_fixture_pair(repo_root: Path) -> PreservedFullFixturePair:
    """Load the full 2.22.0 preserved input/readback pair (private bytes or live re-read)."""
    witness = require_witness_source(repo_root)
    root = Path(repo_root).resolve()
    if witness.kind == WitnessKind.PRIVATE_PILOT and witness.pilot_dir is not None:
        repro = witness.pilot_dir / PRD366_MARKDOWN_REPRO.name
        if not repro.is_file():
            recheck = witness.pilot_dir / PRD366_RUNTIME_RECHECK.name
            if recheck.is_file():
                repro = recheck
            else:
                raise FileNotFoundError(f"missing private markdown repro: {repro}")
        data = load_json(repro)
        submitted, refetched = _markdown_repro_pair(data)
        return PreservedFullFixturePair(
            submitted=submitted,
            refetched=refetched,
            witness_kind=witness.kind,
            source_path=str(repro.relative_to(root)),
        )
    recheck = root / PRD366_RUNTIME_RECHECK
    if recheck.is_file():
        data = load_json(recheck)
        submitted, refetched = _markdown_repro_pair(data)
        return PreservedFullFixturePair(
            submitted=submitted,
            refetched=refetched,
            witness_kind=WitnessKind.LIVE_TIE8,
            source_path=str(recheck.relative_to(root)),
        )
    raise WitnessUnavailableError(
        "live TIE-8 re-read requires runtime-recheck-2.22.0.json under "
        f"{PRD366_PRIVATE_PILOT_DIR.as_posix()}"
    )


def family_map_covers_redacted_pairs(
    family_map: dict[str, Any], redacted: dict[str, Any]
) -> list[str]:
    errors: list[str] = []
    leftovers = family_map.get("leftovers") or []
    ref_ids = {row.get("redactedFixtureId") for row in leftovers if isinstance(row, dict)}
    pair_ids = {
        row.get("id")
        for row in (redacted.get("pairs") or [])
        if isinstance(row, dict)
    }
    missing = sorted(pair_ids - ref_ids)
    extra = sorted(ref_ids - pair_ids)
    if missing:
        errors.append(f"family-map missing redactedFixtureId for pair ids: {missing}")
    if extra:
        errors.append(f"family-map references unknown redactedFixtureId: {extra}")
    return errors
