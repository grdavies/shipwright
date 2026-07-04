#!/usr/bin/env python3
"""PRD 055 Thread E — gap capture unification + legacy backlog migration fixtures (R21–R27)."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest import mock

SCRIPT_DIR = Path(__file__).resolve().parent.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from _sw.vendor_paths import repo_root


def ok(name: str) -> None:
    print(f"OK  {name}")


def bad(name: str, detail: str = "") -> None:
    print(f"FAIL {name}")
    if detail:
        print(detail)


def init_git_repo(path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=path, check=True)


def copy_fixture_corpus(dest: Path, root: Path) -> None:
    src = root / "scripts/test/fixtures/planning-related/corpus"
    shutil.copytree(src, dest, dirs_exist_ok=True)


def scenario_gap_flip_schedule_canonical_id(root: Path) -> bool:
    with tempfile.TemporaryDirectory() as tmp:
        fix = Path(tmp)
        init_git_repo(fix)
        copy_fixture_corpus(fix, root)
        unit_id = "gap-025-deliver-advances-on-ship-green-not-phase-checklist"
        gap_dir = fix / "docs/prds/gap" / unit_id
        gap_dir.mkdir(parents=True, exist_ok=True)
        (gap_dir / f"{unit_id}.md").write_text(
            f"""---
id: {unit_id}
type: gap
status: open
title: deliver advances on ship-green
visibility: public
---

# fixture canonical gap
""",
            encoding="utf-8",
        )
        art = fix / "docs/prds/055-workflow-fidelity-gap-closure/055-prd-workflow-fidelity-gap-closure.md"
        art.parent.mkdir(parents=True, exist_ok=True)
        art.write_text(
            f"""---
frozen: true
absorbs:
  - {unit_id}
---
# PRD 055 fixture
""",
            encoding="utf-8",
        )
        proc = subprocess.run(
            [
                sys.executable,
                str(root / "scripts/gap_backlog.py"),
                "--root",
                str(fix),
                "flip",
                "--schedule",
                "--from-artifact",
                str(art.relative_to(fix)),
            ],
            cwd=fix,
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            bad("gap-flip-schedule-canonical-id", proc.stderr or proc.stdout)
            return False
        out = json.loads(proc.stdout)
        if unit_id not in out.get("flipped", []):
            bad("gap-flip-schedule-canonical-id", f"expected {unit_id} in flipped: {out}")
            return False
        body = (gap_dir / f"{unit_id}.md").read_text(encoding="utf-8")
        if "status: scheduled" not in body or "schedule: PRD 055" not in body:
            bad("gap-flip-schedule-canonical-id", f"canonical frontmatter not scheduled: {body[:200]}")
            return False
        backlog = (fix / "docs/prds/GAP-BACKLOG.md").read_text(encoding="utf-8")
        if "| GAP-025 | scheduled | PRD 055 |" in backlog:
            bad("gap-flip-schedule-canonical-id", "legacy GAP-025 row collided with canonical flip")
            return False
        ok("gap-flip-schedule-canonical-id")
        return True


def scenario_gap_backlog_migration_complete(root: Path) -> bool:
    import gap_backlog as gb

    with tempfile.TemporaryDirectory() as tmp:
        fix = Path(tmp)
        init_git_repo(fix)
        copy_fixture_corpus(fix, root)
        backlog_path = fix / "docs/prds/GAP-BACKLOG.md"
        backlog_path.write_text(
            """# Gap backlog fixture

## Index

| Status | Count |
|--------|------:|
| resolved | 1 |
| scheduled | 2 |
| open | 1 |

| ID | Status | Schedule | Title |
|----|--------|----------|-------|
| GAP-099 | open | — | Unmapped legacy row |
| GAP-100 | scheduled | deferred (evidence-gated) | Policy-tracked deferral |
| GAP-101 | scheduled | PRD 099 | Mapped via canonical unit |
| GAP-102 | resolved | — | Already closed |
""",
            encoding="utf-8",
        )
        canon = fix / "docs/prds/gap/gap-101-mapped-legacy-row"
        canon.mkdir(parents=True, exist_ok=True)
        (canon / "gap-101-mapped-legacy-row.md").write_text(
            """---
id: gap-101-mapped-legacy-row
type: gap
status: scheduled
legacy_gap_id: GAP-101
title: mapped legacy row
visibility: public
schedule: PRD 099
---

# mapped
""",
            encoding="utf-8",
        )
        gate_fail = gb.migration_gate_check(fix)
        if gate_fail.get("verdict") != "fail":
            bad("gap-backlog-migration-complete-negative", str(gate_fail))
            return False
        text = backlog_path.read_text(encoding="utf-8")
        text = text.replace("| GAP-099 | open | — |", "| GAP-099 | resolved | — |")
        backlog_path.write_text(text, encoding="utf-8")
        gate_pass = gb.migration_gate_check(fix)
        if gate_pass.get("verdict") != "pass":
            bad("gap-backlog-migration-complete-positive", str(gate_pass))
            return False
    ok("gap-backlog-migration-complete")
    return True


def scenario_gap_capture_planning_store_routing(root: Path) -> bool:
    import planning_gap_capture as pgc

    with tempfile.TemporaryDirectory() as tmp:
        fix = Path(tmp)
        init_git_repo(fix)
        (fix / ".cursor").mkdir(parents=True, exist_ok=True)
        (fix / ".cursor/workflow.config.json").write_text('{"planning":{"store":{"backend":"in-repo-public"}}}', encoding="utf-8")
        (fix / "docs/prds").mkdir(parents=True, exist_ok=True)
        calls: list[tuple[str, str, str]] = []

        class FakeBackend:
            backend_id = "in-repo-public"

            def put(self, unit_id: str, body_path: str, content: str, *, content_class: str | None = None):
                calls.append((unit_id, body_path, content))
                from planning_store import StoreResult

                return StoreResult("ok", unit_id, body_path, self.backend_id, content=content)

        with mock.patch("planning_gap_capture.ps.get_backend", return_value=FakeBackend()):
            out = pgc.capture_gap(
                fix,
                signal_id="fixture-signal",
                title="store routing test",
                dry_run=False,
            )
        if not calls:
            bad("gap-capture-planning-store-routing", "planning_store.put was not called")
            return False
        unit_id, body_path, content = calls[0]
        if not body_path.startswith("docs/prds/gap/"):
            bad("gap-capture-planning-store-routing", f"unexpected body path: {body_path}")
            return False
        if out.get("unitId") != unit_id:
            bad("gap-capture-planning-store-routing", f"unit id mismatch: {out}")
            return False
        if "status: open" not in content:
            bad("gap-capture-planning-store-routing", "content missing open status")
            return False
    ok("gap-capture-planning-store-routing")
    return True


def main(argv: list[str] | None = None) -> int:
    root = repo_root(__file__)
    fail = 0
    if not scenario_gap_flip_schedule_canonical_id(root):
        fail = 1
    if not scenario_gap_backlog_migration_complete(root):
        fail = 1
    if not scenario_gap_capture_planning_store_routing(root):
        fail = 1
    return fail


if __name__ == "__main__":
    raise SystemExit(main())
