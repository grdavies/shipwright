"""PRD 095 R7 — unit/integration tests for orphan-worktree cleanup (tasks 4.1–4.5)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

import cleanup_lib
from cleanup_lib import (
    Item,
    Report,
    _classify_orphan,
    apply_report,
    can_autonomous_apply,
    enumerate_cleanup,
    enumerate_orphan_worktrees,
)


def _mk_orphan_layout(root: Path) -> dict[str, Path]:
    """Create ghost/park/husk dirs under .sw-worktrees (no git registration)."""
    sw = root / ".sw-worktrees"
    sw.mkdir(parents=True, exist_ok=True)

    ghost = sw / "feat-ghost-orphan"
    ghost.mkdir()
    (ghost / "README.md").write_text("ghost\n", encoding="utf-8")

    park = sw / "feat-foo.park-1785776936"
    park.mkdir()
    (park / ".git").write_text("gitdir: /nonexistent\n", encoding="utf-8")

    husk = sw / "feat-husk-orphan"
    husk.mkdir()
    (husk / ".git").write_text("gitdir: /nonexistent\n", encoding="utf-8")

    return {"ghost": ghost, "park": park, "husk": husk, "sw": sw}


# --- 4.2 Classification ordering and park regex ---


def test_classify_orphan_ghost_when_no_git(tmp_path: Path) -> None:
    d = tmp_path / "no-git"
    d.mkdir()
    assert _classify_orphan(d) == "ghost"


def test_classify_orphan_park_requires_git_and_suffix(tmp_path: Path) -> None:
    d = tmp_path / "feat-foo.park-1785776936"
    d.mkdir()
    (d / ".git").write_text("gitdir: x\n", encoding="utf-8")
    assert _classify_orphan(d) == "park"


def test_classify_orphan_park_regex_rejects_non_numeric_suffix(tmp_path: Path) -> None:
    bad_abc = tmp_path / "feat-foo.park-abc"
    bad_abc.mkdir()
    (bad_abc / ".git").write_text("gitdir: x\n", encoding="utf-8")
    assert _classify_orphan(bad_abc) == "husk"

    bad_trailing = tmp_path / ".park-123foo"
    bad_trailing.mkdir()
    (bad_trailing / ".git").write_text("gitdir: x\n", encoding="utf-8")
    assert _classify_orphan(bad_trailing) == "husk"


def test_classify_orphan_ordering_ghost_before_park(tmp_path: Path) -> None:
    """Ghost wins when no .git even if name matches park suffix."""
    d = tmp_path / "feat-foo.park-1785776936"
    d.mkdir()
    assert _classify_orphan(d) == "ghost"


def test_classify_orphan_husk_when_git_without_park(tmp_path: Path) -> None:
    d = tmp_path / "feat-husk"
    d.mkdir()
    (d / ".git").mkdir()
    assert _classify_orphan(d) == "husk"


# --- 4.1 Enumerate fixtures ---


def test_enumerate_orphan_missing_sw_worktrees_returns_empty(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    with patch.object(cleanup_lib, "parse_worktrees", return_value=[]):
        with patch.object(cleanup_lib, "resolve_deliver_state") as rds:
            rds.return_value = MagicMock(state={})
            assert enumerate_orphan_worktrees(root) == []


def test_enumerate_orphan_classifies_ghost_park_husk(tmp_git_repo: Path) -> None:
    paths = _mk_orphan_layout(tmp_git_repo)
    with patch.object(cleanup_lib, "parse_worktrees", return_value=[]):
        with patch.object(cleanup_lib, "resolve_deliver_state") as rds:
            rds.return_value = MagicMock(state={})
            found = {p.name: cls for p, cls in enumerate_orphan_worktrees(tmp_git_repo)}
    assert found[paths["ghost"].name] == "ghost"
    assert found[paths["park"].name] == "park"
    assert found[paths["husk"].name] == "husk"


def test_enumerate_orphan_skips_registered(tmp_git_repo: Path) -> None:
    paths = _mk_orphan_layout(tmp_git_repo)
    registered = [{"path": str(paths["husk"].resolve()), "branch": "feat/husk"}]
    with patch.object(cleanup_lib, "parse_worktrees", return_value=registered):
        with patch.object(cleanup_lib, "resolve_deliver_state") as rds:
            rds.return_value = MagicMock(state={})
            names = {p.name for p, _ in enumerate_orphan_worktrees(tmp_git_repo)}
    assert paths["husk"].name not in names
    assert paths["ghost"].name in names
    assert paths["park"].name in names


def test_enumerate_orphan_skips_symlink(tmp_git_repo: Path) -> None:
    sw = tmp_git_repo / ".sw-worktrees"
    sw.mkdir(parents=True, exist_ok=True)
    target = tmp_git_repo / "outside-target"
    target.mkdir()
    link = sw / "symlink-orphan"
    link.symlink_to(target)
    real = sw / "real-ghost"
    real.mkdir()
    with patch.object(cleanup_lib, "parse_worktrees", return_value=[]):
        with patch.object(cleanup_lib, "resolve_deliver_state") as rds:
            rds.return_value = MagicMock(state={})
            names = {p.name for p, _ in enumerate_orphan_worktrees(tmp_git_repo)}
    assert "symlink-orphan" not in names
    assert "real-ghost" in names


def test_enumerate_orphan_oserror_volume_inaccessible(tmp_git_repo: Path) -> None:
    sw = tmp_git_repo / ".sw-worktrees"
    sw.mkdir(parents=True, exist_ok=True)
    real_iterdir = Path.iterdir

    def guarded_iterdir(self: Path):
        if self.resolve() == sw.resolve():
            raise OSError("volume offline")
        return real_iterdir(self)

    with patch.object(cleanup_lib, "parse_worktrees", return_value=[]):
        with patch.object(cleanup_lib, "resolve_deliver_state") as rds:
            rds.return_value = MagicMock(state={})
            with patch.object(Path, "iterdir", guarded_iterdir):
                with pytest.raises(OSError, match="volume offline"):
                    enumerate_orphan_worktrees(tmp_git_repo)


# --- 4.3 enumerate_cleanup integration ---


def test_enumerate_cleanup_includes_orphan_items(tmp_git_repo: Path) -> None:
    orphans = [
        (tmp_git_repo / ".sw-worktrees" / "ghost-a", "ghost"),
        (tmp_git_repo / ".sw-worktrees" / "husk-a", "husk"),
    ]
    with patch.object(cleanup_lib, "enumerate_orphan_worktrees", return_value=orphans):
        with patch.object(cleanup_lib, "list_local_branches", return_value=["main"]):
            with patch.object(cleanup_lib, "list_remote_branches", return_value=[]):
                with patch.object(cleanup_lib, "parse_worktrees", return_value=[]):
                    with patch.object(cleanup_lib, "deliver_inflight", return_value=(False, "")):
                        with patch.object(cleanup_lib, "resolve_deliver_state") as rds:
                            rds.return_value = MagicMock(state={}, stale_roots=[])
                            with patch.object(cleanup_lib, "enumerate_refusal_ledger"):
                                report = enumerate_cleanup(tmp_git_repo)
    orphan_items = [i for i in report.would_remove if i.kind == "orphan-worktree"]
    assert len(orphan_items) == 2
    assert {i.reason for i in orphan_items} == {"ghost", "husk"}
    assert all(i.detail.startswith("classification=") for i in orphan_items)


def test_enumerate_cleanup_oserror_surfaces_volume_inaccessible(tmp_git_repo: Path) -> None:
    with patch.object(
        cleanup_lib,
        "enumerate_orphan_worktrees",
        side_effect=OSError("disk gone"),
    ):
        with patch.object(cleanup_lib, "list_local_branches", return_value=["main"]):
            with patch.object(cleanup_lib, "list_remote_branches", return_value=[]):
                with patch.object(cleanup_lib, "parse_worktrees", return_value=[]):
                    with patch.object(cleanup_lib, "deliver_inflight", return_value=(False, "")):
                        with patch.object(cleanup_lib, "resolve_deliver_state") as rds:
                            rds.return_value = MagicMock(state={}, stale_roots=[])
                            with patch.object(cleanup_lib, "enumerate_refusal_ledger"):
                                report = enumerate_cleanup(tmp_git_repo)
    assert any("volume_inaccessible" in err for err in report.errors)


def test_can_autonomous_apply_blocks_park_class(tmp_git_repo: Path) -> None:
    cfg = tmp_git_repo / ".cursor" / "workflow.config.json"
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text(json.dumps({"cleanup": {"autonomy": "auto"}}), encoding="utf-8")
    report = Report(dry_run=True)
    report.would_remove.append(
        Item("orphan-worktree", str(tmp_git_repo / ".sw-worktrees" / "x.park-1"), "park", "")
    )
    with patch.object(cleanup_lib, "deliver_inflight", return_value=(False, "")):
        with patch.object(cleanup_lib, "has_indeterminate_protected", return_value=False):
            ok, reason = can_autonomous_apply(tmp_git_repo, report)
    assert ok is False
    assert "park-class" in reason


# --- 4.4 apply_report orphan handler ---


def _orphan_report(path: Path, classification: str) -> Report:
    report = Report(dry_run=False)
    report.would_remove.append(
        Item("orphan-worktree", str(path), classification, f"classification={classification}")
    )
    return report


def test_apply_husk_calls_git_prune_expire_now(tmp_git_repo: Path) -> None:
    paths = _mk_orphan_layout(tmp_git_repo)
    husk = paths["husk"]
    report = _orphan_report(husk, "husk")
    calls: list[tuple[Any, ...]] = []

    def fake_git(root: Path, *args: str):
        calls.append(args)
        return MagicMock(returncode=0, stdout="", stderr="")

    with patch.object(cleanup_lib, "parse_worktrees", return_value=[]):
        with patch.object(cleanup_lib, "git", side_effect=fake_git):
            with patch.object(cleanup_lib, "host_remote_name", return_value="origin"):
                out = apply_report(tmp_git_repo, report)
    assert any(c == ("worktree", "prune", "--expire", "now") for c in calls)
    assert any(i.name == str(husk) for i in out.removed)
    assert not husk.exists()


def test_apply_ghost_and_park_do_not_prune(tmp_git_repo: Path) -> None:
    paths = _mk_orphan_layout(tmp_git_repo)
    for classification, key in (("ghost", "ghost"), ("park", "park")):
        path = paths[key]
        report = _orphan_report(path, classification)
        calls: list[tuple[Any, ...]] = []

        def fake_git(root: Path, *args: str, _calls=calls):
            _calls.append(args)
            return MagicMock(returncode=0, stdout="", stderr="")

        with patch.object(cleanup_lib, "parse_worktrees", return_value=[]):
            with patch.object(cleanup_lib, "git", side_effect=fake_git):
                with patch.object(cleanup_lib, "host_remote_name", return_value="origin"):
                    out = apply_report(tmp_git_repo, report)
        assert not any(c[:2] == ("worktree", "prune") for c in calls)
        assert any(i.name == str(path) for i in out.removed)
        assert not path.exists()


def test_apply_race_guard_moves_late_registered_to_protected(tmp_git_repo: Path) -> None:
    paths = _mk_orphan_layout(tmp_git_repo)
    husk = paths["husk"]
    report = _orphan_report(husk, "husk")
    registered = [{"path": str(husk.resolve()), "branch": "feat/late"}]
    with patch.object(cleanup_lib, "parse_worktrees", return_value=registered):
        with patch.object(cleanup_lib, "host_remote_name", return_value="origin"):
            out = apply_report(tmp_git_repo, report)
    assert husk.exists()
    protected = [i for i in out.protected if i.kind == "orphan-worktree"]
    assert len(protected) == 1
    assert protected[0].detail == "registered-at-remove-time"
    assert out.removed == []


def test_apply_oserror_during_walk_partial_removal_error(tmp_git_repo: Path) -> None:
    paths = _mk_orphan_layout(tmp_git_repo)
    ghost = paths["ghost"]
    report = _orphan_report(ghost, "ghost")
    with patch.object(cleanup_lib, "parse_worktrees", return_value=[]):
        with patch.object(cleanup_lib, "host_remote_name", return_value="origin"):
            with patch.object(
                cleanup_lib,
                "_safe_tree_remove",
                side_effect=OSError("permission denied"),
            ):
                out = apply_report(tmp_git_repo, report)
    assert any(i.reason == "partial_removal_error" for i in out.protected)
    assert any("permission denied" in err for err in out.errors)
    assert out.removed == []


# --- 4.5 Integration against tmp repo with orphan dirs ---


@pytest.mark.git
@pytest.mark.integration
def test_integration_enumerate_cleanup_with_orphan_dirs(tmp_git_repo: Path) -> None:
    paths = _mk_orphan_layout(tmp_git_repo)
    # Also create a registered linked worktree under .sw-worktrees that must be excluded
    registered_dir = paths["sw"] / "registered-wt"
    registered_dir.mkdir()
    (registered_dir / ".git").write_text("gitdir: placeholder\n", encoding="utf-8")

    with patch.object(
        cleanup_lib,
        "parse_worktrees",
        return_value=[{"path": str(registered_dir.resolve()), "branch": "feat/reg"}],
    ):
        with patch.object(cleanup_lib, "list_local_branches", return_value=["main"]):
            with patch.object(cleanup_lib, "list_remote_branches", return_value=[]):
                with patch.object(cleanup_lib, "deliver_inflight", return_value=(False, "")):
                    with patch.object(cleanup_lib, "resolve_deliver_state") as rds:
                        rds.return_value = MagicMock(state={}, stale_roots=[])
                        with patch.object(cleanup_lib, "enumerate_refusal_ledger"):
                            report = enumerate_cleanup(tmp_git_repo)

    orphans = [i for i in report.would_remove if i.kind == "orphan-worktree"]
    names = {Path(i.name).name for i in orphans}
    assert paths["ghost"].name in names
    assert paths["park"].name in names
    assert paths["husk"].name in names
    assert "registered-wt" not in names
    assert report.errors == []


@pytest.mark.git
def test_integration_apply_removes_orphans(tmp_git_repo: Path) -> None:
    paths = _mk_orphan_layout(tmp_git_repo)
    report = Report(dry_run=True)
    for key, cls in (("ghost", "ghost"), ("park", "park"), ("husk", "husk")):
        report.would_remove.append(
            Item("orphan-worktree", str(paths[key]), cls, f"classification={cls}")
        )

    prune_calls: list[tuple[Any, ...]] = []

    real_git = cleanup_lib.git

    def tracking_git(root: Path, *args: str):
        if args[:2] == ("worktree", "prune"):
            prune_calls.append(args)
            return MagicMock(returncode=0, stdout="", stderr="")
        return real_git(root, *args)

    with patch.object(cleanup_lib, "parse_worktrees", return_value=[]):
        with patch.object(cleanup_lib, "git", side_effect=tracking_git):
            with patch.object(cleanup_lib, "host_remote_name", return_value="origin"):
                out = apply_report(tmp_git_repo, report)

    assert len(out.removed) == 3
    assert not paths["ghost"].exists()
    assert not paths["park"].exists()
    assert not paths["husk"].exists()
    assert prune_calls == [("worktree", "prune", "--expire", "now")]
    assert out.errors == []
