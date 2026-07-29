"""PRD 082 R32 — destination binding and emission-point registry fixtures."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2]
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import memory_redact  # noqa: E402
from planning_visibility import (  # noqa: E402
    EMISSION_POINT_REGISTRY,
    emission_point_destinations,
    resolve_emission_destination,
)

EMISSION_DOC = (
    Path(__file__).resolve().parents[3]
    / "core"
    / "skills"
    / "visibility"
    / "references"
    / "emission-points.md"
)


def _parse_doc_destinations() -> dict[str, str]:
    rows: dict[str, str] = {}
    for line in EMISSION_DOC.read_text(encoding="utf-8").splitlines():
        if not line.startswith("|") or line.startswith("| ---"):
            continue
        parts = [p.strip() for p in line.strip("|").split("|")]
        if len(parts) < 3:
            continue
        point = parts[0].strip("`")
        destination = parts[1].strip("`")
        if point in EMISSION_POINT_REGISTRY:
            rows[point] = destination
    return rows


def test_missing_destination_fails_closed_with_no_stdout() -> None:
    proc = subprocess.run(
        [sys.executable, str(SCRIPTS / "memory_redact.py"), "ghp_" + "a" * 36],
        capture_output=True,
        text=True,
    )
    assert proc.returncode != 0
    assert proc.stdout == ""


def test_unregistered_emission_point_resolves_to_external() -> None:
    assert resolve_emission_destination(None) == "external"
    assert resolve_emission_destination("") == "external"
    assert resolve_emission_destination("not-a-real-point") == "external"


@pytest.mark.parametrize("point_id", sorted(EMISSION_POINT_REGISTRY))
def test_registry_matches_documented_destination(point_id: str) -> None:
    documented = _parse_doc_destinations()
    assert point_id in documented
    assert resolve_emission_destination(point_id) == documented[point_id]


def test_redact_requires_valid_destination_tier() -> None:
    with pytest.raises(ValueError):
        memory_redact.redact("secret", destination="invalid-tier")


def test_redact_accepts_each_destination_tier() -> None:
    secret = "ghp_" + "A" * 36
    for destination in sorted(memory_redact.DESTINATION_VALUES):
        out = memory_redact.redact(secret, destination=destination)
        assert "ghp_" not in out
        assert destination in memory_redact.DESTINATION_VALUES


def test_emission_point_destinations_cover_registry() -> None:
    destinations = emission_point_destinations()
    assert set(destinations) == set(EMISSION_POINT_REGISTRY)
    for destination in destinations.values():
        assert destination in memory_redact.DESTINATION_VALUES
