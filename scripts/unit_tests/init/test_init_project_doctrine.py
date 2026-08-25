"""PRD 330 R6, R11, R12 — /sw-init consent-gated ProjectDoctrine adoption."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parents[2]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from project_doctrine import (  # noqa: E402
    baseline_draft_path,
    doctrine_sot_path,
    load_baseline_draft,
    load_doctrine,
)

COMMANDS_DIRS = (
    Path("core/commands"),
    Path("commands"),
    Path("dist/cursor/commands"),
    Path("dist/claude-code/commands"),
)
FORBIDDEN_COMMAND_STEMS = frozenset({"sw-codebase-design"})


def _configure(root: Path, subcmd: str, *extra: str) -> tuple[int, dict]:
    proc = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_DIR / "sw-configure.py"),
            "doctrine",
            subcmd,
            "--root",
            str(root),
            *extra,
        ],
        cwd=str(root),
        capture_output=True,
        text=True,
        check=False,
    )
    payload = json.loads(proc.stdout or proc.stderr or "{}")
    return proc.returncode, payload


def _minimal_doctrine(**overrides: object) -> dict:
    doc = {
        "id": "consumer-doctrine",
        "version": "ProjectDoctrine@v1",
        "provenance": {
            "createdAt": "2026-08-24T00:00:00Z",
            "source": "operator-review",
        },
        "confidence": "high",
        "sourceRefs": [{"uri": "file://repo/README.md"}],
    }
    doc.update(overrides)
    return doc


def test_no_prompt_discover_writes_no_doctrine(tmp_git_repo: Path) -> None:
    code, plan = _configure(tmp_git_repo, "discover")
    assert code == 0
    assert plan["action"] == "plan"
    assert plan["writesDoctrine"] is False
    assert plan["authoritative"] is False
    assert not doctrine_sot_path(tmp_git_repo).exists()
    assert load_doctrine(tmp_git_repo) is None


def test_plan_alias_is_read_only(tmp_git_repo: Path) -> None:
    code, payload = _configure(tmp_git_repo, "plan")
    assert code == 0
    assert payload["action"] == "plan"
    assert payload["writesDoctrine"] is False
    assert load_doctrine(tmp_git_repo) is None


def test_skip_is_durable_non_authoritative(tmp_git_repo: Path) -> None:
    code, payload = _configure(tmp_git_repo, "skip")
    assert code == 0
    assert payload["verdict"] == "pass"
    assert payload["authoritative"] is False
    assert payload["promoted"] is False
    assert load_doctrine(tmp_git_repo) is None
    marker = tmp_git_repo / ".cursor/sw-init-project-doctrine.json"
    assert marker.is_file()
    stored = json.loads(marker.read_text(encoding="utf-8"))
    assert stored["declined"] is True
    code, rediscover = _configure(tmp_git_repo, "plan")
    assert code == 0
    assert rediscover["declined"] is True


def test_decline_clears_draft_and_doctrine(tmp_git_repo: Path) -> None:
    code, _ = _configure(tmp_git_repo, "greenfield-scaffold", "--confirm")
    assert code == 0
    assert load_doctrine(tmp_git_repo) is not None
    code, payload = _configure(tmp_git_repo, "decline")
    assert code == 0
    assert payload["authoritative"] is False
    assert payload["promoted"] is False
    assert load_doctrine(tmp_git_repo) is None
    assert load_baseline_draft(tmp_git_repo) is None


def test_greenfield_requires_confirm(tmp_git_repo: Path) -> None:
    code, refused = _configure(tmp_git_repo, "greenfield-scaffold")
    assert code != 0
    assert refused["verdict"] == "confirm-required"
    assert load_doctrine(tmp_git_repo) is None
    code, accepted = _configure(tmp_git_repo, "greenfield-scaffold", "--confirm")
    assert code == 0
    assert accepted["verdict"] == "pass"
    doctrine = load_doctrine(tmp_git_repo)
    assert doctrine is not None
    assert doctrine["provenance"]["source"] == "greenfield-scaffold"


def test_brownfield_synthesis_stays_draft_until_promote(tmp_git_repo: Path) -> None:
    (tmp_git_repo / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
    code, refused = _configure(tmp_git_repo, "brownfield-synthesize")
    assert code != 0
    assert refused["verdict"] == "confirm-required"
    assert load_doctrine(tmp_git_repo) is None
    code, synthesized = _configure(tmp_git_repo, "brownfield-synthesize", "--confirm")
    assert code == 0
    assert synthesized["verdict"] == "pass"
    assert synthesized["promoted"] is False
    assert synthesized["status"] == "draft"
    assert load_doctrine(tmp_git_repo) is None
    assert baseline_draft_path(tmp_git_repo).is_file()
    code, promote_refused = _configure(tmp_git_repo, "accept-promote")
    assert code != 0
    assert promote_refused["verdict"] == "confirm-required"
    code, promoted = _configure(tmp_git_repo, "accept-promote", "--confirm")
    assert code == 0
    assert promoted["verdict"] == "pass"
    assert load_doctrine(tmp_git_repo) is not None


def test_explicit_accept_doctrine_creates_valid_sot(tmp_git_repo: Path) -> None:
    reviewed = tmp_git_repo / "reviewed.json"
    reviewed.write_text(json.dumps(_minimal_doctrine(), indent=2) + "\n", encoding="utf-8")
    code, refused = _configure(tmp_git_repo, "accept-doctrine", "--file", str(reviewed))
    assert code != 0
    assert refused["verdict"] == "confirm-required"
    assert load_doctrine(tmp_git_repo) is None
    code, accepted = _configure(
        tmp_git_repo, "accept-doctrine", "--file", str(reviewed), "--confirm"
    )
    assert code == 0
    assert accepted["verdict"] == "pass"
    loaded = load_doctrine(tmp_git_repo)
    assert loaded is not None
    assert loaded["id"] == "consumer-doctrine"


def test_no_codebase_design_command_registered(repo_root: Path) -> None:
    found: list[str] = []
    for directory in COMMANDS_DIRS:
        root = repo_root / directory
        if not root.is_dir():
            continue
        for path in root.rglob("*"):
            if path.stem in FORBIDDEN_COMMAND_STEMS or "sw-codebase-design" in path.name:
                found.append(str(path.relative_to(repo_root)))
    assert found == [], f"unexpected forbidden command registration: {found}"
    explore = repo_root / "core/commands/sw-explore.md"
    assert explore.is_file(), "PRD 331 phase 5 registers /sw-explore"
    init_text = (repo_root / "core/commands/sw-init.md").read_text(encoding="utf-8")
    assert "does not register" in init_text or "does **not** register" in init_text
    assert "/sw-explore" in init_text
    assert "doctrine plan" in init_text or "doctrine discover" in init_text
