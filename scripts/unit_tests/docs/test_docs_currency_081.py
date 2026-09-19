"""PRD 081 R20/R21 — release-guide documentation currency fixtures."""
from __future__ import annotations

import importlib.util
import json
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
    assert calls.index([c for c in calls if "agent_instruction_compiler.py" in " ".join(c)][0]) < calls.index(
        [c for c in calls if "snapshot-tree.py" in " ".join(c)][0]
    )


def test_instruction_compiler_check_is_not_currency_green(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    (root / "core" / "commands").mkdir(parents=True)
    doc = root / "core/commands/sw-doc.md"
    doc.write_text("---\nname: sw-doc\ndescription: Use when doc.\n---\n# body\n", encoding="utf-8")
    (root / "core" / "sw-reference").mkdir(parents=True)
    (root / COMPILED_ARTIFACT_REL).write_text('{"artifacts": []}\n', encoding="utf-8")
    drift = check_command_doc_instruction_currency(root, doc_rel="core/commands/sw-doc.md")
    assert any(row.get("kind") == "command-doc-instruction-artifact-stale" for row in drift)


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
