#!/usr/bin/env python3
"""Local pre-commit guard: block commits touching frozen artifacts (PRD 042 R3)."""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path


def _git(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=False)


def _is_frozen_at_head(repo: Path, path: str) -> bool:
    proc = subprocess.run(["git", "show", f"HEAD:{path}"], cwd=repo, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        return False
    in_fm = False
    for line in proc.stdout.splitlines():
        if line.strip() == "---":
            if in_fm:
                break
            in_fm = True
            continue
        if in_fm and line.startswith("frozen:") and "true" in line.split(":", 1)[-1].lower():
            return True
    return False


def _checkbox_only(repo: Path, scripts: Path, old_path: Path, new_path: Path) -> bool:
    checker = scripts / "checkbox_diff.py"
    if not checker.is_file():
        return False
    proc = subprocess.run(
        [sys.executable, str(checker), "is-checkbox-only", str(old_path), str(new_path)],
        cwd=repo, capture_output=True, text=True, check=False,
    )
    return proc.returncode == 0


def main() -> int:
    repo = Path(subprocess.check_output(["git", "rev-parse", "--show-toplevel"], text=True).strip())
    scripts = repo / "scripts"
    check = scripts / "check-frozen.sh"
    if not check.is_file():
        print("sw-freeze: check-frozen.sh missing; refusing commit", file=sys.stderr)
        return 1
    staged = _git("diff", "--cached", "--name-only", cwd=repo).stdout.splitlines()
    if not staged:
        return 0
    violations: list[str] = []
    for path in staged:
        if not path:
            continue
        if _git("cat-file", "-e", f"HEAD:{path}", cwd=repo).returncode != 0:
            continue
        if not _is_frozen_at_head(repo, path):
            continue
        if _git("diff", "--cached", "--quiet", "--", path, cwd=repo).returncode == 0:
            continue
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            old, new = tmpdir / "old", tmpdir / "new"
            subprocess.run(["git", "show", f"HEAD:{path}"], cwd=repo, stdout=old.open("w", encoding="utf-8"), check=False)
            subprocess.run(["git", "show", f":{path}"], cwd=repo, stdout=new.open("w", encoding="utf-8"), check=False)
            if _checkbox_only(repo, scripts, old, new):
                continue
        violations.append(path)
    if violations:
        print("sw-freeze: refusing commit — frozen artifact(s) modified:", file=sys.stderr)
        for item in violations:
            print(f"  {item}", file=sys.stderr)
        print("Use /sw-amend for post-freeze changes. Bypass with --no-verify (CI will still block).", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
