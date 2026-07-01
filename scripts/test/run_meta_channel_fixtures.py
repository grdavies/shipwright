#!/usr/bin/env python3
"""PRD 041 R20/R21 meta-shipwright channel fixtures."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR.parent) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR.parent))

from _fixture_lib import FixtureContext

def seed_schemas(ctx: FixtureContext, root: Path) -> None:
    src = ctx.root / "core/sw-reference"
    dest = root / "core/sw-reference"
    dest.mkdir(parents=True, exist_ok=True)
    for name in (
        "meta-inbox-draft.schema.json",
        "failure-signature.schema.json",
    ):
        shutil.copy2(src / name, dest / name)



def run_capture(ctx: FixtureContext, tmp: Path, *extra: str) -> dict:
    proc = ctx.run_py(
        "scripts/planning_gap_capture.py",
        str(tmp),
        "capture",
        *extra,
        check=False,
    )
    if proc.returncode != 0:
        ctx.bad(f"planning_gap_capture failed: {proc.stdout} {proc.stderr}")
        return {}
    return json.loads(proc.stdout)


def main() -> int:
    ctx = FixtureContext(__file__)
    tmp = ctx.mktemp("meta-channel-")
    try:
        subprocess.run(["git", "init"], cwd=tmp, capture_output=True, check=True)
        subprocess.run(["git", "config", "user.email", "fixture@test"], cwd=tmp, check=True)
        subprocess.run(["git", "config", "user.name", "fixture"], cwd=tmp, check=True)
        (tmp / "docs/planning/gap").mkdir(parents=True)
        (tmp / ".cursor").mkdir(exist_ok=True)
        seed_schemas(ctx, tmp)

        out = run_capture(
            ctx,
            tmp,
            "--destination",
            "meta-shipwright",
            "--signal-id",
            "sig-meta-001",
            "--title",
            "Plugin routing gap",
            "--summary",
            "Dogfood signal",
        )
        inbox = tmp / ".cursor/sw-meta-inbox/sig-meta-001.json"
        if inbox.is_file():
            draft = json.loads(inbox.read_text(encoding="utf-8"))
            if (
                draft.get("destination") == "meta-shipwright"
                and draft.get("gapClass") == "plugin-self"
                and draft.get("status") == "draft"
            ):
                ctx.ok("meta-shipwright tagging + plugin-self gap class")
            else:
                ctx.bad("meta draft fields incorrect")
        else:
            ctx.bad("meta inbox draft missing")

        tracked = list((tmp / "docs/planning/gap").glob("gap-*"))
        if not tracked:
            ctx.ok("capture without confirm yields zero tracked planning gap units")
        else:
            ctx.bad(f"unexpected tracked gap units after capture-only: {tracked}")

        proc = ctx.run_py(
            "scripts/planning_gap_capture.py",
            str(tmp),
            "confirm",
            "--signal-id",
            "sig-meta-001",
            check=False,
        )
        if proc.returncode == 0:
            ctx.ok("meta confirm persisted ack")
        else:
            ctx.bad("meta confirm failed")

        proc = ctx.run_py(
            "scripts/planning_gap_capture.py",
            str(tmp),
            "materialize",
            "--signal-id",
            "sig-meta-001",
            "--title",
            "Plugin routing gap",
            check=False,
        )
        units = list((tmp / "docs/planning/gap").glob("gap-*/*.md"))
        if proc.returncode == 0 and units:
            body = units[0].read_text(encoding="utf-8")
            if "plugin-self" in body and "meta-shipwright" in body:
                ctx.ok("confirm+materialize creates plugin-self gap unit")
            else:
                ctx.bad("materialized unit missing plugin-self/meta-shipwright tags")
        else:
            ctx.bad("materialize did not create gap unit")

        draft = json.loads(inbox.read_text(encoding="utf-8"))
        if draft.get("status") == "materialized" and draft.get("materializedUnitId"):
            ctx.ok("inbox draft marked materialized")
        else:
            ctx.bad("inbox draft not marked materialized")

    finally:
        ctx.cleanup()
    return 1 if ctx.failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
