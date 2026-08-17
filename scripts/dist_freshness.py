#!/usr/bin/env python3
"""Side-effect-free scripts↔dist drift detection (PRD 274 R8/R9/R15)."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from _sw.cli import run_module_main

CANONICAL_REGEN_COMMAND = "python3 -m sw generate --all"


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def detect_drift(root: Path | None = None) -> list[dict[str, str]]:
    """Return drift rows when scripts sources disagree with dist mirrors."""
    from dist_regeneration_082 import check_distribution_freshness

    base = root or repo_root()
    return check_distribution_freshness(base)


def format_drift_message(drift: list[dict[str, str]]) -> str:
    lines = ["dist-freshness: scripts↔dist drift detected"]
    for row in drift[:20]:
        kind = row.get("kind", "drift")
        path = row.get("path", "")
        target = row.get("target", "")
        suffix = f" ({target})" if target else ""
        lines.append(f"  - {kind}: {path}{suffix}")
    if len(drift) > 20:
        lines.append(f"  - … and {len(drift) - 20} more")
    lines.append(f"regen: {CANONICAL_REGEN_COMMAND}")
    return "\n".join(lines)


def detect_is_side_effect_free(root: Path | None = None) -> bool:
    """Prove detect path does not mutate tracked/untracked dist state."""
    import subprocess

    base = root or repo_root()
    before = subprocess.run(
        ["git", "-C", str(base), "status", "--porcelain", "--", "dist/"],
        capture_output=True,
        text=True,
        check=False,
    ).stdout
    detect_drift(base)
    after = subprocess.run(
        ["git", "-C", str(base), "status", "--porcelain", "--", "dist/"],
        capture_output=True,
        text=True,
        check=False,
    ).stdout
    return before == after


def cmd_detect(root: Path) -> int:
    drift = detect_drift(root)
    if drift:
        print(format_drift_message(drift), file=sys.stderr)
        return 20
    print("dist-freshness detect: OK")
    return 0


def cmd_json(root: Path) -> int:
    drift = detect_drift(root)
    payload = {
        "verdict": "pass" if not drift else "fail",
        "drift": drift,
        "regenCommand": CANONICAL_REGEN_COMMAND,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if not drift else 20


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Detect scripts↔dist drift without mutation")
    parser.add_argument(
        "command",
        nargs="?",
        default="detect",
        choices=("detect", "json"),
        help="detect: fail closed on drift; json: machine-readable report",
    )
    parser.add_argument("--root", type=Path, default=None, help="repo root (default: auto)")
    args = parser.parse_args(argv)
    root = args.root or repo_root()
    if args.command == "json":
        return cmd_json(root)
    return cmd_detect(root)


if __name__ == "__main__":
    run_module_main(main)
