"""PRD 081 R20/R21 — release-guide documentation currency fixtures."""
from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import patch

import pytest

SCRIPT_DIR = Path(__file__).resolve().parents[2]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from docs_currency_081 import RELEASE_GUIDE_ARTIFACTS, check_release_guide_artifacts
from agent_instruction_compiler import COMPILED_ARTIFACT_REL, check_command_doc_instruction_currency


def _load_docs_currency_gate():
    spec = importlib.util.spec_from_file_location(
        "docs_currency_gate",
        SCRIPT_DIR / "docs-currency-gate.py",
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    (root / ".sw").mkdir(parents=True)
    (root / "docs" / "guides").mkdir(parents=True)
    (root / "scripts").mkdir(parents=True)
    for binding in RELEASE_GUIDE_ARTIFACTS:
        for rel in binding["sources"]:
            src = root / rel
            src.parent.mkdir(parents=True, exist_ok=True)
            src.write_text(f"# source for {binding['id']}\n", encoding="utf-8")
    time.sleep(0.02)
    for binding in RELEASE_GUIDE_ARTIFACTS:
        doc = root / str(binding["doc"])
        doc.parent.mkdir(parents=True, exist_ok=True)
        doc.write_text("\n".join(binding["markers"]) + "\n", encoding="utf-8")
    return root


def test_release_guide_currency_passes_when_current(repo: Path) -> None:
    assert check_release_guide_artifacts(repo) == []


def test_release_guide_currency_fails_when_doc_stale(repo: Path) -> None:
    binding = RELEASE_GUIDE_ARTIFACTS[0]
    source = repo / str(binding["sources"][0])
    time.sleep(0.02)
    source.write_text("# touched\n", encoding="utf-8")
    drift = check_release_guide_artifacts(repo)
    assert any(row.get("kind") == "guide-stale" and row.get("id") == binding["id"] for row in drift)


def test_release_guide_currency_fails_when_marker_missing(repo: Path) -> None:
    doc = repo / ".shipwright/layout.md"
    doc.write_text("# incomplete\n", encoding="utf-8")
    drift = check_release_guide_artifacts(repo)
    assert any(row.get("kind") == "guide-marker-missing" for row in drift)


def test_docs_currency_gate_imports_release_guide_check() -> None:
    text = (SCRIPT_DIR / "docs-currency-gate.py").read_text(encoding="utf-8")
    assert "from docs_currency_081 import check_release_guide_artifacts" in text
    assert "check_release_guide_artifacts(root)" in text


def test_regen_command_doc_chain_order_and_no_build_chain_check() -> None:
    gate = _load_docs_currency_gate()
    root = Path("/tmp/repo")
    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        calls.append(list(cmd))
        class _Proc:
            returncode = 0
            stdout = ""
            stderr = ""

        return _Proc()

    with patch("subprocess.run", side_effect=fake_run):
        payload = gate.regen_command_doc_currency_downstream(root)
    assert payload["verdict"] == "pass"
    joined = "\n".join(" ".join(c) for c in calls)
    assert "agent_instruction_compiler.py" in joined
    assert "sw generate cursor" in joined or " generate cursor" in joined
    assert "sw generate claude-code" in joined or " generate claude-code" in joined
    assert "snapshot-tree.py" in joined
    assert "ship-build-chain-check" not in joined
    compiler_cmds = [c for c in calls if "agent_instruction_compiler.py" in " ".join(c)]
    assert compiler_cmds
    assert all("--check" not in " ".join(c) for c in compiler_cmds)
    generate_cmds = [c for c in calls if " generate " in " ".join(c)]
    snapshot_cmds = [c for c in calls if "snapshot-tree.py" in " ".join(c)]
    assert calls.index(compiler_cmds[0]) < calls.index(generate_cmds[0])
    assert calls.index(generate_cmds[-1]) < calls.index(snapshot_cmds[0])


def test_instruction_compiler_check_is_not_currency_green(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    (root / "core" / "commands").mkdir(parents=True)
    doc = root / "core/commands/sw-doc.md"
    doc.write_text("---\nname: sw-doc\ndescription: Use when doc.\n---\n# body\n", encoding="utf-8")
    (root / "core" / "sw-reference").mkdir(parents=True)
    (root / COMPILED_ARTIFACT_REL).write_text('{"artifacts": []}\n', encoding="utf-8")
    drift = check_command_doc_instruction_currency(root, doc_rel="core/commands/sw-doc.md")
    assert any(row.get("kind") == "command-doc-instruction-artifact-stale" for row in drift)


def _mini_command_doc_compile_root(repo_root: Path, tmp_path: Path) -> Path:
    root = tmp_path / "mini"
    for rel in (
        "core/commands/sw-doc.md",
        "core/commands/sw-tasks.md",
        "core/commands/sw-freeze.md",
        "core/commands/sw-deliver.md",
        COMPILED_ARTIFACT_REL,
        ".cursor/workflow.config.json",
    ):
        src = repo_root / rel
        dst = root / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
    return root


def test_instruction_compiler_check_does_not_write_artifact_or_clear_currency(
    repo_root: Path, tmp_path: Path
) -> None:
    root = _mini_command_doc_compile_root(repo_root, tmp_path)
    artifact = root / COMPILED_ARTIFACT_REL
    stale_body = '{"artifacts": []}\n'
    artifact.write_text(stale_body, encoding="utf-8")
    assert check_command_doc_instruction_currency(root)

    check_proc = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_DIR / "agent_instruction_compiler.py"),
            "--check",
            "--root",
            str(root),
        ],
        cwd=str(root),
        capture_output=True,
        text=True,
    )
    assert check_proc.returncode != 0
    assert artifact.read_text(encoding="utf-8") == stale_body
    assert check_command_doc_instruction_currency(root)

    write_proc = subprocess.run(
        [sys.executable, str(SCRIPT_DIR / "agent_instruction_compiler.py"), "--root", str(root)],
        cwd=str(root),
        capture_output=True,
        text=True,
    )
    assert write_proc.returncode == 0
    assert check_command_doc_instruction_currency(root) == []


def test_snapshot_tree_fails_golden_before_generate(repo: Path) -> None:
    import subprocess

    (repo / "dist" / "cursor" / "commands").mkdir(parents=True)
    core_doc = repo / "core/commands/sw-doc.md"
    core_doc.parent.mkdir(parents=True, exist_ok=True)
    core_doc.write_text("# touched core\n", encoding="utf-8")
    (repo / "dist/cursor/commands/sw-doc.md").write_text("# stale dist\n", encoding="utf-8")
    golden = repo / "scripts/test/fixtures/parity/cursor-golden.manifest"
    golden.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_DIR / "snapshot-tree.py"),
            str(golden),
            "--root",
            str(repo),
        ],
        cwd=str(repo),
        capture_output=True,
        text=True,
    )
    assert proc.returncode != 0
    assert "dist-stale-before-generate" in proc.stderr


def test_snapshot_tree_writes_golden_when_dist_mirrors_match(repo: Path) -> None:
    from planning_paths import GOLDEN_MANIFEST_REL

    core_doc = repo / "core/commands/sw-doc.md"
    core_doc.parent.mkdir(parents=True, exist_ok=True)
    body = "# aligned core\n"
    core_doc.write_text(body, encoding="utf-8")
    for platform in ("cursor", "claude-code"):
        mirror = repo / "dist" / platform / "commands" / "sw-doc.md"
        mirror.parent.mkdir(parents=True, exist_ok=True)
        mirror.write_text(body, encoding="utf-8")
    (repo / "dist" / "cursor" / "providers").mkdir(parents=True)
    golden = repo / GOLDEN_MANIFEST_REL
    proc = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_DIR / "snapshot-tree.py"),
            str(golden),
            "--root",
            str(repo),
        ],
        cwd=str(repo),
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0
    assert golden.is_file()
    assert "commands/sw-doc.md" in golden.read_text(encoding="utf-8")


def test_command_doc_dist_mirrors_stale_when_core_changes(
    repo_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    gate = _load_docs_currency_gate()
    root = _mini_command_doc_compile_root(repo_root, tmp_path)
    doc_rel = "core/commands/sw-doc.md"
    body = (root / doc_rel).read_text(encoding="utf-8")
    for platform in ("cursor", "claude-code"):
        mirror = root / "dist" / platform / "commands" / Path(doc_rel).name
        mirror.parent.mkdir(parents=True, exist_ok=True)
        mirror.write_text(body, encoding="utf-8")
    (root / doc_rel).write_text(body + "\n# mirror drift\n", encoding="utf-8")
    monkeypatch.setattr(gate, "_git_last_commit_epoch", lambda _r, _p: 100)
    drift = gate.check_command_documentation_currency(root)
    kinds = {row.get("kind") for row in drift if row.get("doc") == doc_rel}
    assert "command-doc-dist-mirror-stale" in kinds
    assert "command-doc-stale" not in kinds
    assert any(row.get("platform") == "cursor" for row in drift if row.get("kind") == "command-doc-dist-mirror-stale")
    assert any(row.get("platform") == "claude-code" for row in drift if row.get("kind") == "command-doc-dist-mirror-stale")


def test_command_doc_currency_fails_stale_downstream_with_matching_needles(
    repo_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    gate = _load_docs_currency_gate()
    root = _mini_command_doc_compile_root(repo_root, tmp_path)
    doc_rel = "core/commands/sw-doc.md"
    artifact = root / COMPILED_ARTIFACT_REL
    artifact.write_text('{"artifacts": []}\n', encoding="utf-8")
    monkeypatch.setattr(gate, "_git_last_commit_epoch", lambda _r, _p: 100)
    drift = gate.check_command_documentation_currency(root)
    assert not any(row.get("kind") == "command-doc-stale" for row in drift)
    assert not any(row.get("kind") == "command-doc-needle-missing" for row in drift)
    assert any(
        row.get("kind") == "command-doc-instruction-artifact-stale" and row.get("doc") == doc_rel
        for row in drift
    )


def test_regen_chain_ends_with_snapshot_tree_refresh(tmp_path: Path) -> None:
    gate = _load_docs_currency_gate()
    root = tmp_path / "repo"
    golden_rel = "scripts/test/fixtures/parity/cursor-golden.manifest"
    golden = root / golden_rel
    golden.parent.mkdir(parents=True, exist_ok=True)
    golden.write_text("stale-manifest\tdeadbeef\n", encoding="utf-8")
    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        calls.append(list(cmd))
        if "snapshot-tree.py" in " ".join(cmd):
            golden.write_text("commands/sw-doc.md\tfresh\n", encoding="utf-8")
        class _Proc:
            returncode = 0
            stdout = ""
            stderr = ""

        return _Proc()

    with patch("subprocess.run", side_effect=fake_run):
        payload = gate.regen_command_doc_currency_downstream(root)
    assert payload["verdict"] == "pass"
    snapshot_cmds = [c for c in calls if "snapshot-tree.py" in " ".join(c)]
    assert snapshot_cmds
    assert snapshot_cmds[-1] == calls[-1]
    assert "fresh" in golden.read_text(encoding="utf-8")
