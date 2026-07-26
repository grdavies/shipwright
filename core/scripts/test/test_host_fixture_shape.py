"""Mechanical host fixture shape checks (PRD 079 R15)."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

_CORE_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_CORE_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_CORE_SCRIPTS))

from _sw.host._common import fixture_dir  # noqa: E402

_REPO_ROOT = Path(__file__).resolve().parents[3]


def _is_legacy_labelled(path: Path, data: dict[str, Any]) -> bool:
    if "legacy-status" in path.name:
        return True
    return data.get("_legacyStatus") is True


def _validate_transport_map(path: Path, data: dict[str, Any]) -> list[str]:
    if _is_legacy_labelled(path, data):
        return []
    errors: list[str] = []
    for key, value in data.items():
        if key.startswith("_"):
            continue
        if not key.startswith("/"):
            continue
        if not isinstance(value, dict):
            continue
        has_status = "status" in value
        has_status_code = "statusCode" in value
        if has_status and not has_status_code:
            errors.append(f"{path.name}: entry {key!r} uses legacy status without statusCode")
        if has_status_code and "verdict" not in value:
            errors.append(f"{path.name}: entry {key!r} has statusCode without verdict")
    return errors


def _collect_fixture_shape_errors(root: Path) -> list[str]:
    fdir = fixture_dir(root)
    if not fdir.is_dir():
        return [f"missing fixture directory: {fdir}"]
    errors: list[str] = []
    for path in sorted(fdir.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            errors.append(f"{path.name}: invalid JSON ({exc})")
            continue
        if not isinstance(data, dict):
            continue
        if path.name.startswith("transport-"):
            errors.extend(_validate_transport_map(path, data))
    return errors


def test_fixture_shape_statuscode_production_rules() -> None:
    errors = _collect_fixture_shape_errors(_REPO_ROOT)
    assert not errors, "fixture shape violations:\n" + "\n".join(errors)


def test_legacy_status_fixture_exempt() -> None:
    legacy = fixture_dir(_REPO_ROOT) / "transport-legacy-status-only.json"
    assert legacy.is_file()
    data = json.loads(legacy.read_text(encoding="utf-8"))
    assert data.get("_legacyStatus") is True
    assert _validate_transport_map(legacy, data) == []
