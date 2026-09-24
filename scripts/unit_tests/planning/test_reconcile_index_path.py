from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]
SHIPWRIGHT_SCRIPTS = REPO_ROOT / "scripts"
CANDIDATE = SHIPWRIGHT_SCRIPTS / "reconcile_lib.py"

if str(SHIPWRIGHT_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SHIPWRIGHT_SCRIPTS))

spec = importlib.util.spec_from_file_location("candidate_reconcile_lib", CANDIDATE)
assert spec and spec.loader
rl = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rl)


@pytest.fixture(autouse=True)
def clear_require_merge(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SW_RECONCILE_REQUIRE_MERGE", raising=False)


def init_repo(root: Path, branch: str = "feature/test") -> None:
    subprocess.run(["git", "init", "-q", "-b", branch, str(root)], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(root),
            "-c",
            "user.name=Shipwright Test",
            "-c",
            "user.email=shipwright@example.invalid",
            "commit",
            "-q",
            "--allow-empty",
            "-m",
            "fixture init",
        ],
        check=True,
    )


def write_config(root: Path, **overrides: Any) -> None:
    path = root / ".shipwright/workflow.config.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps({"defaultBaseBranch": "main", **overrides}),
        encoding="utf-8",
    )


def canonical_index(status: str = "not-started") -> str:
    return (
        "<!-- planning-index:structural begin -->\n"
        "| id | type | title | status | visibility | edges |\n"
        "| --- | --- | --- | --- | --- | --- |\n"
        f"| 019-prd-billing-provider-integration-paddle | prd | Paddle | {status} | public | |\n"
        "<!-- planning-index:structural end -->\n"
    )


def test_set_status_uses_explicit_planning_dir_and_canonical_row(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    init_repo(tmp_path)
    write_config(
        tmp_path,
        planningDir=".project_docs/planning",
        prdsDir=".project_docs/planning/prd",
        tasksDir=".project_docs/planning/prd",
    )
    canonical = tmp_path / ".project_docs/planning/INDEX.md"
    canonical.parent.mkdir(parents=True)
    canonical.write_text(canonical_index(), encoding="utf-8")
    legacy = tmp_path / "docs/prds/INDEX.md"
    legacy.parent.mkdir(parents=True)
    legacy.write_text("sentinel\n", encoding="utf-8")
    monkeypatch.setattr(rl, "_refuse_banned_living_doc_write", lambda *_a, **_k: None)

    result = rl.set_index_status(tmp_path, "19", "in-progress")

    assert result["verdict"] == "pass"
    assert "| 019-prd-billing-provider-integration-paddle | prd | Paddle | in-progress |" in canonical.read_text(
        encoding="utf-8"
    )
    assert legacy.read_text(encoding="utf-8") == "sentinel\n"


def test_reconcile_derives_and_updates_tierforge_layout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    init_repo(tmp_path, branch="feat/prd-19-paddle-adoption")
    write_config(
        tmp_path,
        planningDir="custom/planning",
        prdsDir="custom/prds",
        tasksDir="custom/prds",
        planning={"store": {"backend": "in-repo-public"}},
    )
    canonical = tmp_path / "custom/planning/INDEX.md"
    canonical.parent.mkdir(parents=True)
    canonical.write_text(canonical_index(), encoding="utf-8")
    tasks = tmp_path / "custom/prds/019-prd-billing-provider-integration-paddle/tasks-019-prd-19-paddle-adoption.md"
    tasks.parent.mkdir(parents=True)
    tasks.write_text("- [x] restore typed baseline\n- [ ] continue adoption\n", encoding="utf-8")
    monkeypatch.setattr(rl, "host_pr_list", lambda _root: [])

    result = rl.reconcile_prd_index(tmp_path, allow_default=True)

    assert result == {"verdict": "reconciled", "updated": ["019"]}
    assert "| 019-prd-billing-provider-integration-paddle | prd | Paddle | in-progress |" in canonical.read_text(
        encoding="utf-8"
    )
    derived = rl.derive_prd_status(tmp_path)["prds"]
    assert derived[0]["taskFile"].endswith("tasks-019-prd-19-paddle-adoption.md")


def test_canonical_in_progress_is_not_downgraded_without_naming_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    init_repo(tmp_path, branch="feature/unrelated")
    write_config(tmp_path, planningDir="custom/planning", prdsDir="custom/prds", tasksDir="custom/prds")
    canonical = tmp_path / "custom/planning/INDEX.md"
    canonical.parent.mkdir(parents=True)
    canonical.write_text(canonical_index(status="in-progress"), encoding="utf-8")
    monkeypatch.setattr(rl, "host_pr_list", lambda _root: [])

    derived = rl.derive_prd_status(tmp_path)["prds"]

    assert derived[0]["status"] == "in-progress"


@pytest.mark.parametrize("structural_status", ["complete", "superseded"])
def test_canonical_terminal_status_semantics_are_preserved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, structural_status: str
) -> None:
    init_repo(tmp_path, branch="feature/unrelated")
    write_config(tmp_path, planningDir="custom/planning", prdsDir="custom/prds", tasksDir="custom/prds")
    canonical = tmp_path / "custom/planning/INDEX.md"
    canonical.parent.mkdir(parents=True)
    canonical.write_text(canonical_index(status=structural_status), encoding="utf-8")
    monkeypatch.setattr(rl, "host_pr_list", lambda _root: [])

    derived = rl.derive_prd_status(tmp_path)["prds"]

    assert derived[0]["status"] == "complete"


def test_require_merge_still_refuses_in_progress_floor(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    init_repo(tmp_path, branch="feat/prd-19-paddle-adoption")
    write_config(tmp_path, planningDir="custom/planning", prdsDir="custom/prds", tasksDir="custom/prds")
    canonical = tmp_path / "custom/planning/INDEX.md"
    canonical.parent.mkdir(parents=True)
    canonical.write_text(canonical_index(status="in-progress"), encoding="utf-8")
    monkeypatch.setattr(rl, "host_pr_list", lambda _root: [])
    monkeypatch.setenv("SW_RECONCILE_REQUIRE_MERGE", "1")

    derived = rl.derive_prd_status(tmp_path)["prds"]

    assert derived[0]["status"] == "not-started"


def test_non_git_root_keeps_legacy_prds_index(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    legacy = tmp_path / "docs/prds/INDEX.md"
    legacy.parent.mkdir(parents=True)
    legacy.write_text(
        "| # | Slug | PRD | Tasks | Status |\n"
        "|---|---|---|---|---|\n"
        "| 008 | model-tier | [prd](x) | [tasks](x) | complete |\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(rl, "_refuse_banned_living_doc_write", lambda *_a, **_k: None)

    result = rl.set_index_status(tmp_path, "008", "in-progress")

    assert result["status"] == "in-progress"
    assert "| 008 | model-tier | [prd](x) | [tasks](x) | in-progress |" in legacy.read_text(encoding="utf-8")


def test_legacy_repo_keeps_prds_index_default(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    init_repo(tmp_path)
    legacy = tmp_path / "docs/prds/INDEX.md"
    legacy.parent.mkdir(parents=True)
    legacy.write_text(
        "| # | Slug | PRD | Tasks | Status |\n"
        "|---|---|---|---|---|\n"
        "| 019 | paddle | [prd](x) | [tasks](x) | not-started |\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(rl, "_refuse_banned_living_doc_write", lambda *_a, **_k: None)

    rl.set_index_status(tmp_path, "019", "in-progress")

    assert "| 019 | paddle | [prd](x) | [tasks](x) | in-progress |" in legacy.read_text(encoding="utf-8")
    assert not (tmp_path / "docs/planning/INDEX.md").exists()


def test_configured_planning_path_escape_fails_closed(tmp_path: Path) -> None:
    init_repo(tmp_path)
    write_config(tmp_path, planningDir="../outside")

    with pytest.raises(Exception, match="path traversal rejected"):
        rl.prd_index_path(tmp_path)


def test_core_reads_preferred_config_for_default_branch_guard(tmp_path: Path) -> None:
    init_repo(tmp_path, branch="develop")
    write_config(
        tmp_path,
        defaultBaseBranch="develop",
        planningDir=".project_docs/planning",
        planning={"store": {"backend": "in-repo-public"}},
    )
    index = tmp_path / ".project_docs/planning/INDEX.md"
    index.parent.mkdir(parents=True)
    index.write_text(canonical_index(), encoding="utf-8")
    core_scripts = REPO_ROOT / "core/scripts"
    code = (
        "from pathlib import Path\n"
        "import reconcile_lib as rl\n"
        "rl._refuse_banned_living_doc_write = lambda *_a, **_k: None\n"
        "root = Path(__import__('sys').argv[1])\n"
        "result = rl.set_index_status(root, '019', 'in-progress')\n"
        "assert result['verdict'] == 'fail', result\n"
        "assert result['branch'] == 'develop', result\n"
    )

    subprocess.run(
        [sys.executable, "-c", code, str(tmp_path)],
        check=True,
        env={**os.environ, "PYTHONPATH": str(core_scripts)},
    )
    assert "| 019-prd-billing-provider-integration-paddle | prd | Paddle | not-started |" in index.read_text(
        encoding="utf-8"
    )
