"""parity-compare-correctness fixture (PRD 055 R30)."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

_TEST_DIR = Path(__file__).resolve().parents[2] / "test"
if str(_TEST_DIR) not in sys.path:
    sys.path.insert(0, str(_TEST_DIR))

from parity_compare import compare_tree, file_sha256


@pytest.fixture
def parity_tree(tmp_path: Path) -> tuple[Path, Path]:
    tree = tmp_path / "tree"
    (tree / "commands").mkdir(parents=True)
    test_file = tree / "commands" / "sw-test.md"
    test_file.write_text("cmd body\n", encoding="utf-8")
    manifest = tmp_path / "tree.manifest"
    digest = file_sha256(test_file)
    manifest.write_text(f"commands/sw-test.md\t{digest}\n", encoding="utf-8")
    return tree, manifest


def test_parity_compare_happy(parity_tree: tuple[Path, Path]) -> None:
    tree, manifest = parity_tree
    code, msg = compare_tree(tree, manifest)
    assert code == 0
    assert "parity-match" in msg


def test_parity_compare_missing_file(parity_tree: tuple[Path, Path], tmp_path: Path) -> None:
    _tree, manifest = parity_tree
    empty = tmp_path / "empty"
    empty.mkdir()
    code, msg = compare_tree(empty, manifest)
    assert code == 1
    assert "missing file" in msg


def test_parity_compare_extra_file(parity_tree: tuple[Path, Path], tmp_path: Path) -> None:
    tree, manifest = parity_tree
    extra = tmp_path / "extra"
    shutil.copytree(tree, extra)
    (extra / "commands" / "extra.md").write_text("x\n", encoding="utf-8")
    code, msg = compare_tree(extra, manifest)
    assert code == 1
    assert "extra file" in msg


def test_parity_compare_hash_diff(parity_tree: tuple[Path, Path], tmp_path: Path) -> None:
    tree, manifest = parity_tree
    changed = tmp_path / "changed"
    shutil.copytree(tree, changed)
    (changed / "commands" / "sw-test.md").write_text("changed\n", encoding="utf-8")
    code, msg = compare_tree(changed, manifest)
    assert code == 1
    assert "hash diff" in msg
