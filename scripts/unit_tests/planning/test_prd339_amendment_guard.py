"""PRD 339 R35 — amendment guard frozen-open parent eligibility."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from authoring_guard import amend_status_guard


def _init_repo(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=tmp_path, check=True)
    (tmp_path / ".cursor" / "hooks" / "state").mkdir(parents=True, exist_ok=True)


def _write_index(tmp_path: Path, derived_line: str = "") -> None:
    planning = tmp_path / "docs" / "planning"
    planning.mkdir(parents=True, exist_ok=True)
    derived_body = f"\n{derived_line}\n" if derived_line else "\n"
    planning.joinpath("INDEX.md").write_text(
        (
            "# Planning units INDEX\n\n"
            "<!-- planning-index:schema v1 -->\n\n"
            "<!-- planning-index:structural begin -->\n"
            "<!-- planning-index:structural end -->\n"
            "<!-- planning-index:derived begin -->"
            f"{derived_body}"
            "<!-- planning-index:derived end -->\n"
            "<!-- planning-index:inFlight begin -->\n"
            "<!-- planning-index:inFlight end -->\n"
        ),
        encoding="utf-8",
    )


def _write_parent(
    tmp_path: Path,
    unit_id: str,
    *,
    status: str = "proposed",
    frozen: bool = False,
) -> Path:
    unit_dir = tmp_path / "docs" / "planning" / "prd" / unit_id
    unit_dir.mkdir(parents=True, exist_ok=True)
    frozen_line = "frozen: true\n" if frozen else ""
    body = (
        "---\n"
        f"id: {unit_id}\n"
        "type: prd\n"
        f"status: {status}\n"
        f"{frozen_line}"
        "---\n"
        "# Parent PRD\n"
    )
    path = unit_dir / f"{unit_id}.md"
    path.write_text(body, encoding="utf-8")
    return path


def _commit_all(tmp_path: Path) -> None:
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=tmp_path, check=True)


def test_frozen_open_proposed_parent(tmp_path: Path) -> None:
    """R35 — frozen-open parent with proposed consumerStatus accepts amend."""
    _init_repo(tmp_path)
    unit_id = "339-prd-amend-parent"
    _write_index(tmp_path)
    _write_parent(tmp_path, unit_id, status="proposed", frozen=True)
    _commit_all(tmp_path)

    amend_status_guard(tmp_path, unit_id, None)


def test_unfrozen_parent_rejected(tmp_path: Path) -> None:
    """R35 — unfrozen parent fails with typed unfrozen-parent cause."""
    _init_repo(tmp_path)
    unit_id = "339-prd-unfrozen-parent"
    _write_index(tmp_path)
    _write_parent(tmp_path, unit_id, status="planned", frozen=False)
    _commit_all(tmp_path)

    with pytest.raises(SystemExit) as exc:
        amend_status_guard(tmp_path, unit_id, None)
    assert exc.value.code == 20


def test_closed_parent_rejected(tmp_path: Path) -> None:
    """R35 — closed (superseded) frozen parent fails with closed-parent cause."""
    _init_repo(tmp_path)
    unit_id = "339-prd-closed-parent"
    _write_index(tmp_path)
    _write_parent(tmp_path, unit_id, status="superseded", frozen=True)
    _commit_all(tmp_path)

    with pytest.raises(SystemExit) as exc:
        amend_status_guard(tmp_path, unit_id, None)
    assert exc.value.code == 20


def test_missing_parent_rejected(tmp_path: Path) -> None:
    """R35 — missing parent body fails with missing-parent cause."""
    _init_repo(tmp_path)
    unit_id = "339-prd-missing-parent"
    _write_index(tmp_path)
    _commit_all(tmp_path)

    with pytest.raises(SystemExit) as exc:
        amend_status_guard(tmp_path, unit_id, None)
    assert exc.value.code == 20


def test_mismatched_parent_rejected(tmp_path: Path) -> None:
    """R35 — unit id without a matching body fails closed."""
    _init_repo(tmp_path)
    _write_index(tmp_path)
    _write_parent(tmp_path, "339-prd-other-parent", status="proposed", frozen=True)
    _commit_all(tmp_path)

    with pytest.raises(SystemExit) as exc:
        amend_status_guard(tmp_path, "339-prd-wrong-parent", None)
    assert exc.value.code == 20


def test_amend_guard_json_causes(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """R35 — subprocess guard emits typed cause fields."""
    _init_repo(tmp_path)
    unit_id = "339-prd-json-parent"
    _write_index(tmp_path)
    _write_parent(tmp_path, unit_id, status="planned", frozen=False)
    _commit_all(tmp_path)

    script = Path(__file__).resolve().parents[2] / "authoring_guard.py"
    proc = subprocess.run(
        [
            sys.executable,
            str(script),
            str(tmp_path),
            "preflight",
            "--unit",
            unit_id,
            "--command",
            "sw-amend",
            "--no-commit",
        ],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 20
    payload = json.loads(proc.stdout)
    assert payload["verdict"] == "fail"
    assert payload["cause"] == "unfrozen-parent"
