#!/usr/bin/env python3
"""Seed planning visibility profile, store backend, and privacy notice (PRD 034 R21)."""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from _sw.cli import run_module_main


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Seed planning visibility + store defaults")
    parser.add_argument("--root", type=Path, default=SCRIPT_DIR.parent)
    parser.add_argument("--config", type=Path, default=None)
    args = parser.parse_args(argv)
    root = args.root.resolve()
    config_path = (args.config or root / ".cursor/workflow.config.json").resolve()
    if not config_path.is_file():
        print(
            json.dumps({
                "verdict": "fail",
                "error": "missing-workflow-config",
                "remediation": "run /sw-init write step first",
            }),
            file=sys.stderr,
        )
        return 2

    cfg = json.loads(config_path.read_text(encoding="utf-8"))
    if not isinstance(cfg, dict):
        print(json.dumps({"verdict": "fail", "error": "invalid-workflow-config"}), file=sys.stderr)
        return 2

    planning = cfg.get("planning") if isinstance(cfg.get("planning"), dict) else {}
    store = planning.get("store") if isinstance(planning.get("store"), dict) else {}
    if not store.get("backend"):
        store["backend"] = "in-repo-public"
    planning["store"] = store
    cfg["planning"] = planning
    config_path.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")

    proc = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_DIR / "planning_visibility.py"),
            "--root",
            str(root),
            "resolve-default-profile",
            "--write",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        sys.stderr.write(proc.stdout or proc.stderr)
        return proc.returncode
    profile = json.loads(proc.stdout)

    notice_src = root / "core/sw-reference/planning-privacy-notice.md"
    notice_dst = root / ".cursor/hooks/state/planning-privacy-notice.md"
    notice_dst.parent.mkdir(parents=True, exist_ok=True)
    if notice_src.is_file():
        shutil.copy2(notice_src, notice_dst)
    else:
        notice_dst.write_text(
            "# Planning privacy notice\n\n"
            "Public origin remotes default to all-private. Acknowledge before the first tracked spec commit.\n",
            encoding="utf-8",
        )

    print(
        json.dumps(
            {
                "verdict": "ok",
                "action": "planning-init-seed",
                "visibilityProfile": profile.get("visibilityProfile"),
                "privacyAck": profile.get("privacyAck"),
                "storeBackend": store.get("backend", "in-repo-public"),
                "privacyNotice": ".cursor/hooks/state/planning-privacy-notice.md",
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    run_module_main(main)
