"""PRD 342 R15/R53 — journaled migrate semantic identity + allowlist fail-closed."""

from __future__ import annotations

import json
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2]
REPO_ROOT = SCRIPTS.parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import memory_preflight as mp  # noqa: E402
import shipwright_paths as sp  # noqa: E402
import state_root_migrate as srm  # noqa: E402

LEGACY_RUNS = ".cursor/sw-deliver-runs"
LEGACY_RULES = ".cursor/sw-memory/rules"
LEGACY_ALLOW = ".cursor/sw-memory-rule-allowlist.json"
NEW_RUNS = ".shipwright/deliver-runs"
NEW_RULES = ".shipwright/memory/rules"
NEW_ALLOW = ".shipwright/memory/rule-allowlist.json"


@pytest.fixture
def migrate_repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    dest = root / srm.INVENTORY_REL
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(REPO_ROOT / srm.INVENTORY_REL, dest)
    (root / "version.txt").write_text("1.0.0\n", encoding="utf-8")

    runs = root / LEGACY_RUNS / "run-1"
    runs.mkdir(parents=True)
    (runs / "state.json").write_text(
        json.dumps({"status": "completed", "runId": "run-1"}), encoding="utf-8"
    )
    rules = root / LEGACY_RULES
    rules.mkdir(parents=True)
    (rules / "mock-realism.md").write_text("# mock realism\nbody\n", encoding="utf-8")
    (root / LEGACY_ALLOW).write_text(json.dumps(["mock-realism"]), encoding="utf-8")
    return root


@pytest.fixture
def plugin_matched(migrate_repo: Path, tmp_path: Path) -> Path:
    plugin = tmp_path / "plugin"
    plugin.mkdir()
    dest = plugin / srm.INVENTORY_REL
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(migrate_repo / srm.INVENTORY_REL, dest)
    (plugin / "version.txt").write_text("1.0.0\n", encoding="utf-8")
    return plugin


def _seed_provider(root: Path) -> None:
    cursor = root / ".cursor"
    cursor.mkdir(parents=True, exist_ok=True)
    (cursor / "workflow.config.json").write_text(
        json.dumps({"memory": {"provider": "in-repo", "project": "test"}}),
        encoding="utf-8",
    )


def _loader(_root: Path, provider: str) -> dict:
    return {
        "ok": True,
        "provider": provider,
        "rules": [
            {"id": "mock-realism", "body": "keep"},
            {"id": "not-allowlisted", "body": "drop"},
            {"id": "extra-rule", "body": "drop"},
        ],
    }


def _patch_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        mp,
        "resolve_active_provider",
        lambda root: {"provider": "in-repo", "project": "test"},
    )
    monkeypatch.setattr(mp, "needs_reconcile_path", lambda root: root / ".no-reconcile")
    monkeypatch.setenv("SW_RULE_EFFECTIVENESS_DISABLED", "1")


def test_allowlist_missing_refuses_with_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_provider(tmp_path)
    _patch_provider(monkeypatch)
    attempted = sp.memory_rule_allowlist_path(tmp_path)
    with pytest.raises(mp.PreflightError) as excinfo:
        mp.rules_load(tmp_path, loader=_loader)
    err = excinfo.value
    assert err.cause == "allowlist-missing"
    assert err.path is not None
    assert Path(err.path) == attempted


def test_allowlist_unreadable_refuses_with_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_provider(tmp_path)
    _patch_provider(monkeypatch)
    allow = tmp_path / LEGACY_ALLOW
    allow.parent.mkdir(parents=True, exist_ok=True)
    allow.write_text('["mock-realism"]\n', encoding="utf-8")
    allow.chmod(0)
    try:
        with pytest.raises(mp.PreflightError) as excinfo:
            mp.load_allowlist(tmp_path)
        err = excinfo.value
        assert err.cause == "allowlist-unreadable"
        assert err.path is not None
        assert Path(err.path) == allow
    finally:
        allow.chmod(stat.S_IRUSR | stat.S_IWUSR)


def test_allowlist_unparseable_refuses_with_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_provider(tmp_path)
    _patch_provider(monkeypatch)
    allow = tmp_path / LEGACY_ALLOW
    allow.parent.mkdir(parents=True, exist_ok=True)
    allow.write_text("{not-json", encoding="utf-8")
    with pytest.raises(mp.PreflightError) as excinfo:
        mp.rules_load(tmp_path, loader=_loader)
    err = excinfo.value
    assert err.cause == "allowlist-unparseable"
    assert err.path is not None
    assert Path(err.path) == allow


def test_allowlist_valid_injects_exactly_allowlisted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_provider(tmp_path)
    _patch_provider(monkeypatch)
    allow = tmp_path / LEGACY_ALLOW
    allow.parent.mkdir(parents=True, exist_ok=True)
    allow.write_text(json.dumps(["mock-realism"]), encoding="utf-8")
    loaded = mp.rules_load(tmp_path, loader=_loader)
    ids = {mp._rule_id(entry) for entry in loaded["rules"]}
    assert ids == {"mock-realism"}


def test_git_check_ignore_tracks_relocated_allowlist_and_rules() -> None:
    """Negation block keeps preferred .shipwright memory paths trackable (R53)."""
    probes = {
        NEW_ALLOW: False,
        f"{NEW_RULES}/mock-realism.md": False,
        ".shipwright/cache/gate/tmp": True,
    }
    created: list[Path] = []
    try:
        for rel, expect_ignored in probes.items():
            path = REPO_ROOT / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            if not path.exists():
                path.write_text("probe\n", encoding="utf-8")
                created.append(path)
            status = subprocess.run(
                ["git", "status", "--short", "--ignored", "--", rel],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            line = status.stdout.strip()
            is_ignored = line.startswith("!!")
            assert is_ignored is expect_ignored, f"{rel}: {line!r}"
    finally:
        for path in created:
            path.unlink(missing_ok=True)


def test_interrupted_migrate_resume_preserves_semantic_identity(
    migrate_repo: Path, plugin_matched: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = migrate_repo
    before_paths = [LEGACY_RUNS, LEGACY_RULES, LEGACY_ALLOW]
    before = srm.semantic_snapshot(root, before_paths)

    real = srm._relocate_one
    counter = {"n": 0}

    def interrupt_after_first(repo: Path, legacy: str, new: str) -> dict:
        counter["n"] += 1
        if counter["n"] > 1:
            raise RuntimeError("simulated-interrupt")
        return real(repo, legacy, new)

    monkeypatch.setattr(srm, "_relocate_one", interrupt_after_first)
    with pytest.raises(RuntimeError, match="simulated-interrupt"):
        srm.relocate(root, confirm=True, plugin_root=plugin_matched)
    assert srm.journal_path(root).is_file()
    assert srm.fence_held(root)

    monkeypatch.setattr(srm, "_relocate_one", real)
    resumed = srm.relocate(root, confirm=False, plugin_root=plugin_matched, resume=True)
    assert resumed["verdict"] == "pass"
    assert resumed.get("resumed") is True
    assert not srm.journal_path(root).is_file()
    assert not srm.fence_held(root)

    after = srm.semantic_snapshot(root, [NEW_RUNS, NEW_RULES, NEW_ALLOW])
    assert after[NEW_RUNS] == before[LEGACY_RUNS]
    assert after[NEW_RULES] == before[LEGACY_RULES]
    assert after[NEW_ALLOW] == before[LEGACY_ALLOW]


def test_interrupted_migrate_abort_restores_layout(
    migrate_repo: Path, plugin_matched: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = migrate_repo
    before_paths = [LEGACY_RUNS, LEGACY_RULES, LEGACY_ALLOW]
    before = srm.semantic_snapshot(root, before_paths)

    real = srm._relocate_one
    counter = {"n": 0}

    def interrupt_after_first(repo: Path, legacy: str, new: str) -> dict:
        counter["n"] += 1
        if counter["n"] > 1:
            raise RuntimeError("simulated-interrupt")
        return real(repo, legacy, new)

    monkeypatch.setattr(srm, "_relocate_one", interrupt_after_first)
    with pytest.raises(RuntimeError, match="simulated-interrupt"):
        srm.relocate(root, confirm=True, plugin_root=plugin_matched)

    aborted = srm.relocate(root, confirm=False, plugin_root=plugin_matched, abort=True)
    assert aborted["verdict"] == "pass"
    assert aborted.get("aborted") is True
    assert not srm.journal_path(root).is_file()
    assert not srm.fence_held(root)

    after = srm.semantic_snapshot(root, before_paths)
    assert after == before
    assert (root / LEGACY_RUNS / "run-1" / "state.json").is_file()
    assert not (root / NEW_RUNS).exists()
