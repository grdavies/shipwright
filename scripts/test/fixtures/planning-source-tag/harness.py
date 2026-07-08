#!/usr/bin/env python3
"""Product source-tag scoping fixture (PRD 057 R12).

Proves, fully offline and deterministically:

1. **File-store discovery populates `source`** — a unit whose frontmatter
   carries a `source: <owner>/<repo>` hint is discovered with that value on
   its `PlanningUnit`; an untagged unit discovers with `source == ""`.
2. **Default scope hides nothing** — with no explicit scope configured,
   `filter_units_by_source` is a no-op over both tagged and untagged units.
3. **Explicit scope keeps matches + never hides untagged units** — scoping to
   one `<owner>/<repo>` keeps units tagged for that source and every untagged
   unit, and drops units tagged for a different source.
4. **`resolve_source_scope` precedence** — the `SW_PLANNING_SOURCE_SCOPE` env
   override wins over `planning.store.sourceScope` in committed config, and
   an unset env + unset config resolves to the empty (unscoped) default.
5. **Scheduler `next` threads the scope through** — `planning_scheduler`'s
   file-path frontier drops out-of-scope units (while keeping untagged ones)
   and reports the resolved `sourceScope` on the payload.
6. **`sw:source-missing` doctor advisory** — `planning-doctor.py` surfaces an
   advisory (never fail) finding naming every untagged unit, and stays silent
   once all discovered units carry a source tag.

No network, no live issue store required.
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parents[3]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import planning_discover as pdisc  # noqa: E402
import planning_index_gen as pig  # noqa: E402
import planning_scheduler as psched  # noqa: E402

_UNIT_FRONTMATTER = """---
id: {unit_id}
type: prd
status: proposed
title: {title}{source_line}
---

Body.
"""


def _load_doctor():
    path = SCRIPTS / "planning-doctor.py"
    spec = importlib.util.spec_from_file_location("planning_doctor_source_tag_fixture", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_unit(root: Path, unit_id: str, *, source: str = "") -> None:
    unit_dir = root / "docs" / "planning" / "prd" / unit_id
    unit_dir.mkdir(parents=True, exist_ok=True)
    source_line = f"\nsource: {source}" if source else ""
    (unit_dir / f"{unit_id}.md").write_text(
        _UNIT_FRONTMATTER.format(unit_id=unit_id, title=unit_id, source_line=source_line),
        encoding="utf-8",
    )


def _seed_scoping_corpus(root: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=str(root), check=True)
    (root / ".cursor").mkdir(parents=True, exist_ok=True)
    (root / ".cursor" / "workflow.config.json").write_text(
        json.dumps({"planning": {"store": {"backend": "in-repo-public"}}}, indent=2) + "\n",
        encoding="utf-8",
    )
    _write_unit(root, "001-tagged-acme", source="acme/widget")
    _write_unit(root, "002-tagged-other", source="other/repo")
    _write_unit(root, "003-untagged-legacy")


def check_discovery_populates_source() -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _seed_scoping_corpus(root)
        units = {u.id: u for u in pdisc.discover_units_file(root)}
    ok = (
        units["001-tagged-acme"].source == "acme/widget"
        and units["002-tagged-other"].source == "other/repo"
        and units["003-untagged-legacy"].source == ""
    )
    return {
        "name": "discovery-populates-source",
        "ok": ok,
        "detail": {uid: u.source for uid, u in units.items()},
    }


def check_default_scope_no_op() -> dict:
    tagged = pig.PlanningUnit(id="a", type="prd", status="open", title="A", visibility="", edges="", body_path="a.md", source="acme/widget")
    untagged = pig.PlanningUnit(id="b", type="prd", status="open", title="B", visibility="", edges="", body_path="b.md")
    out = pdisc.filter_units_by_source([tagged, untagged], [])
    ok = out == [tagged, untagged]
    return {"name": "default-scope-no-op", "ok": ok, "detail": [u.id for u in out]}


def check_explicit_scope_keeps_untagged() -> dict:
    acme = pig.PlanningUnit(id="a", type="prd", status="open", title="A", visibility="", edges="", body_path="a.md", source="acme/widget")
    other = pig.PlanningUnit(id="b", type="prd", status="open", title="B", visibility="", edges="", body_path="b.md", source="other/repo")
    untagged = pig.PlanningUnit(id="c", type="prd", status="open", title="C", visibility="", edges="", body_path="c.md")
    out = pdisc.filter_units_by_source([acme, other, untagged], ["acme/widget"])
    ids = [u.id for u in out]
    ok = ids == ["a", "c"]
    return {"name": "explicit-scope-keeps-untagged", "ok": ok, "detail": ids}


def check_resolve_scope_precedence() -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        subprocess.run(["git", "init", "-q"], cwd=str(root), check=True)
        (root / ".cursor").mkdir(parents=True, exist_ok=True)
        (root / ".cursor" / "workflow.config.json").write_text(
            json.dumps({"planning": {"store": {"sourceScope": ["cfg/one", "cfg/two"]}}}, indent=2) + "\n",
            encoding="utf-8",
        )
        cfg_only = pdisc.resolve_source_scope(root)

        os.environ["SW_PLANNING_SOURCE_SCOPE"] = "env/one, env/two"
        try:
            env_wins = pdisc.resolve_source_scope(root)
        finally:
            del os.environ["SW_PLANNING_SOURCE_SCOPE"]

        (root / ".cursor" / "workflow.config.json").write_text(json.dumps({}) + "\n", encoding="utf-8")
        unset_default = pdisc.resolve_source_scope(root)
    ok = (
        cfg_only == ["cfg/one", "cfg/two"]
        and env_wins == ["env/one", "env/two"]
        and unset_default == []
    )
    return {
        "name": "resolve-scope-precedence",
        "ok": ok,
        "detail": {"cfgOnly": cfg_only, "envWins": env_wins, "unsetDefault": unset_default},
    }


def check_scheduler_next_threads_scope() -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _seed_scoping_corpus(root)
        os.environ["SW_PLANNING_SOURCE_SCOPE"] = "acme/widget"
        try:
            saved = psched.runnable_task_list
            try:
                psched.runnable_task_list = lambda root_arg, unit_id: f"docs/prds/{unit_id}/tasks-{unit_id}.md"
                payload = psched.schedule_next(root)
            finally:
                psched.runnable_task_list = saved
        finally:
            del os.environ["SW_PLANNING_SOURCE_SCOPE"]
    eligible = payload.get("eligible") or []
    ok = (
        payload.get("sourceScope") == ["acme/widget"]
        and "001-tagged-acme" in eligible
        and "003-untagged-legacy" in eligible
        and "002-tagged-other" not in eligible
    )
    return {
        "name": "scheduler-next-threads-scope",
        "ok": ok,
        "detail": {"sourceScope": payload.get("sourceScope"), "eligible": eligible},
    }


def check_doctor_source_missing_advisory() -> dict:
    doctor = _load_doctor()
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _seed_scoping_corpus(root)
        with_untagged = doctor.source_missing_finding(root)

        # Backfill the source tag so nothing remains untagged (advisory clears).
        _write_unit(root, "003-untagged-legacy", source="acme/widget")
        fully_tagged = doctor.source_missing_finding(root)
    ok = (
        isinstance(with_untagged, dict)
        and with_untagged.get("check") == "sw:source-missing"
        and with_untagged.get("status") == "advisory"
        and with_untagged.get("untaggedUnits") == ["003-untagged-legacy"]
        and bool(with_untagged.get("remediation"))
        and fully_tagged is None
    )
    return {
        "name": "doctor-source-missing-advisory",
        "ok": ok,
        "detail": {"withUntagged": with_untagged, "fullyTagged": fully_tagged},
    }


def main() -> int:
    checks = [
        check_discovery_populates_source(),
        check_default_scope_no_op(),
        check_explicit_scope_keeps_untagged(),
        check_resolve_scope_precedence(),
        check_scheduler_next_threads_scope(),
        check_doctor_source_missing_advisory(),
    ]
    failures = [c for c in checks if not c["ok"]]
    verdict = "pass" if not failures else "fail"
    report = {
        "fixture": "planning-source-tag",
        "rid": "R12",
        "verdict": verdict,
        "checks": checks,
        "failures": failures,
    }
    print(json.dumps(report, ensure_ascii=False))
    return 0 if verdict == "pass" else 20


if __name__ == "__main__":
    raise SystemExit(main())
