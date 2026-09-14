"""PRD 349 R43–R45 unified installer tests."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2].parent
sys.path.insert(0, str(_REPO / "scripts"))

import installer  # noqa: E402


def test_r43_choices_include_codex_and_opencode() -> None:
    choices = installer.available_choices()
    assert "cursor" in choices and "claude-code" in choices
    assert "codex" in choices and "opencode" in choices


def test_r43_installing_codex_does_not_alter_existing_claude(tmp_path: Path) -> None:
    install_root = tmp_path / "adapters"
    claude = install_root / "claude-code"
    claude.mkdir(parents=True)
    marker = claude / "MARKER.txt"
    marker.write_text("preserve-me\n", encoding="utf-8")
    before = marker.read_text(encoding="utf-8")

    result = installer.install_adapters(
        ["codex"],
        repo=_REPO,
        install_root=install_root,
    )
    assert result["verdict"] == "pass"
    assert "codex" in result["installed"]
    assert marker.read_text(encoding="utf-8") == before
    assert (install_root / "codex" / ".codex-plugin" / "plugin.json").is_file()


def test_r44_unexpected_settings_change_aborts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    before = installer.snapshot_settings(_REPO)
    calls = {"n": 0}

    def flaky_snapshot(root: Path):
        calls["n"] += 1
        if calls["n"] == 1:
            return before
        return {key: f"mutated-{digest}" for key, digest in before.items()}

    monkeypatch.setattr(installer, "snapshot_settings", flaky_snapshot)
    with pytest.raises(installer.InstallerError, match="settings change"):
        installer.install_adapters(["codex"], repo=_REPO, install_root=tmp_path / "adapters")


def test_r45_duplicate_skill_keeps_core_projection(tmp_path: Path) -> None:
    install_root = tmp_path / "adapters"
    for adapter in ("codex", "opencode"):
        skill_dir = install_root / adapter / "skills" / "memory"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(f"stale body from {adapter}\n", encoding="utf-8")
    actions = installer.resolve_duplicate_skills(
        _REPO,
        {
            "codex": install_root / "codex",
            "opencode": install_root / "opencode",
        },
    )
    assert actions
    assert all(a["action"] in {"removed_stale_body", "wrote_core_ref"} for a in actions)
    assert not (install_root / "codex" / "skills" / "memory" / "SKILL.md").exists()
    assert not (install_root / "opencode" / "skills" / "memory" / "SKILL.md").exists()
    assert (install_root / "codex" / "skills" / "memory" / "SKILL.ref.json").is_file()


def test_prd352_r9_native_claude_skill_survives_codex_install(tmp_path: Path) -> None:
    """PRD 352 R9 — native claude-code SKILL.md must survive a later codex install.

    Pins the defect where resolve_duplicate_skills during install_adapters(['codex'])
    unlinks native skill bodies under claude-code/skills/<id>/ when the skill id
    overlaps a core skill (e.g. memory). Expected red until R7/R8 land.
    """
    install_root = tmp_path / "adapters"
    skill_id = "memory"
    native = install_root / "claude-code" / "skills" / skill_id
    native.mkdir(parents=True)
    body = "# Native Claude skill body — must survive codex install\n"
    (native / "SKILL.md").write_text(body, encoding="utf-8")

    result = installer.install_adapters(
        ["codex"],
        repo=_REPO,
        install_root=install_root,
    )
    assert result["verdict"] == "pass"
    assert (native / "SKILL.md").is_file(), (
        "native claude-code SKILL.md was removed during codex install/dedupe"
    )
    assert (native / "SKILL.md").read_text(encoding="utf-8") == body
