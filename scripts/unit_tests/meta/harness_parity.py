#!/usr/bin/env python3
"""Parity harness — pure Python compare (PRD 055 R28)."""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
_SCRIPTS_ROOT = SCRIPT_DIR.parents[1]
_TEST_DIR = _SCRIPTS_ROOT / "test"
for _entry in (str(_TEST_DIR), str(_SCRIPTS_ROOT)):
    if _entry not in sys.path:
        sys.path.insert(0, _entry)

from _sw.vendor_paths import repo_root
from parity_compare import compare_tree, file_sha256

import test_scope as ts


def _run_expect(name: str, expect_ec: int, target: Path, manifest: Path) -> bool:
    code, out = compare_tree(target, manifest)
    if code == expect_ec:
        print(f"OK  {name} exit={code}")
        return True
    print(f"FAIL {name} expected exit={expect_ec} got exit={code}")
    print(out)
    return False


def _should_run_full_dist_compare(root: Path) -> bool:
    scope = os.environ.get("SW_TEST_SCOPE", "full").strip().lower()
    if scope == "full":
        return True
    changed = ts.resolve_changed_paths(root, None)
    return ts.widen_reason(changed) is not None


def main() -> int:
    root = repo_root(__file__)
    fail = 0
    tmp_base = Path(tempfile.mkdtemp(prefix="sw-parity-fix."))

    try:
        happy = tmp_base / "happy-tree"
        (happy / "commands").mkdir(parents=True)
        test_file = happy / "commands" / "sw-test.md"
        test_file.write_text("cmd body\n", encoding="utf-8")
        manifest_happy = tmp_base / "happy.manifest"
        digest = file_sha256(test_file)
        manifest_happy.write_text(f"commands/sw-test.md\t{digest}\n", encoding="utf-8")

        if not _run_expect("happy-match", 0, happy, manifest_happy):
            fail = 1

        missing = tmp_base / "missing-tree"
        (missing / "commands").mkdir(parents=True)
        if not _run_expect("missing-file", 1, missing, manifest_happy):
            fail = 1

        extra = tmp_base / "extra-tree"
        import shutil

        shutil.copytree(happy, extra)
        (extra / "commands" / "extra.md").write_text("extra\n", encoding="utf-8")
        if not _run_expect("extra-file", 1, extra, manifest_happy):
            fail = 1

        diff = tmp_base / "diff-tree"
        shutil.copytree(happy, diff)
        (diff / "commands" / "sw-test.md").write_text("changed\n", encoding="utf-8")
        if not _run_expect("hash-diff", 1, diff, manifest_happy):
            fail = 1

        snapshot = root / "scripts" / "snapshot-tree.py"
        if snapshot.is_file():
            tmp_manifest = tmp_base / "snap1.manifest"
            tmp_manifest2 = tmp_base / "snap2.manifest"
            subprocess.run(
                [sys.executable, str(snapshot), str(tmp_manifest)],
                cwd=str(root),
                check=False,
            )
            subprocess.run(
                [sys.executable, str(snapshot), str(tmp_manifest2)],
                cwd=str(root),
                check=False,
            )
            if tmp_manifest.read_bytes() == tmp_manifest2.read_bytes():
                print("OK  snapshot-deterministic identical across two runs")
            else:
                print("FAIL snapshot-deterministic manifests differ between runs")
                fail = 1

        golden = root / "scripts" / "test" / "fixtures" / "parity" / "cursor-golden.manifest"
        if _should_run_full_dist_compare(root):
            if not golden.is_file():
                print(f"FAIL cursor-golden.manifest missing at {golden}")
                fail = 1
            else:
                code, out = compare_tree(root / "dist" / "cursor", golden)
                if code == 0:
                    print(f"OK  cursor-golden-vs-dist exit={code}")
                else:
                    print(f"FAIL cursor-golden-vs-dist expected exit=0 got exit={code}")
                    print(out)
                    fail = 1
        else:
            print("OK  cursor-golden-vs-dist skipped (scope tier-gate)")

    finally:
        import shutil

        shutil.rmtree(tmp_base, ignore_errors=True)

    return fail


if __name__ == "__main__":
    raise SystemExit(main())
