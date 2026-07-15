"""PRD 069 R7 — GitHub-release shields.io badge authority checks."""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = ROOT / "scripts"
README = ROOT / "README.md"

GITHUB_RELEASE_BADGE_RE = re.compile(
    r"\[!\[[^\]]*\]\(https://img\.shields\.io/github/v/release/[^/]+/[^)]+\)\]"
    r"\(https://github\.com/[^/]+/[^/]+/releases"
)
RETIRED_VERSION_TXT_BADGE_RE = re.compile(
    r"\[!\[version\]\(https://img\.shields\.io/badge/version-[^)]+\)\]\(version\.txt\)"
)


def test_readme_uses_github_release_badge_sot() -> None:
    text = README.read_text(encoding="utf-8")
    assert GITHUB_RELEASE_BADGE_RE.search(text), "README must use shields.io GitHub-release badge"
    assert not RETIRED_VERSION_TXT_BADGE_RE.search(text), "version.txt static badge SoT is retired"


def test_readme_version_badge_check_passes() -> None:
    proc = subprocess.run(
        [sys.executable, str(SCRIPTS / "readme_version_badge.py"), "--root", str(ROOT), "check"],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout


def test_readme_version_badge_sync_is_retired_noop() -> None:
    proc = subprocess.run(
        [sys.executable, str(SCRIPTS / "readme_version_badge.py"), "--root", str(ROOT), "sync"],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
    assert "retired" in (proc.stderr or proc.stdout).lower()
