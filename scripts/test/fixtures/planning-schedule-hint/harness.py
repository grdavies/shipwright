#!/usr/bin/env python3
"""Schedule-hint reconciliation fixture (PRD 057 R17, gap-049).

Proves, fully offline and deterministically:

1. **Hint normalization** — `_schedule_hint_target` extracts a comparable
   absorber-id prefix from both the legacy `PRD <NNN>[ A<n>]` label
   (`gap_backlog.schedule_label`) and the canonical `<NNN>-<slug>` unit-id
   form, and treats empty/placeholder/policy-prefixed hints (``—``,
   ``deferred: ...``, ``config: ...``) as having no absorber to reconcile.
2. **Stale hint surfaces `sw:schedule-stale`** — a gap whose `schedule:` hint
   names one absorber while a *different* unit's `absorbs` edges actually
   resolve it is flagged, naming the hint and the real absorber(s).
3. **Matching hint is silent** — a gap whose hint agrees with its actual
   absorber produces no finding.
4. **Un-absorbed hint is stale** — a hint that names an absorber but nothing
   currently absorbs the gap is flagged too (never trusted silently).
5. **`sw:gap-schedule:*` label decodes the same as the frontmatter hint** —
   issue-store discovery decodes the percent-encoded label into the same
   `schedule` value used by file-store's `schedule:` frontmatter key.
6. **`reconcile_core` surfaces `scheduleStale` end-to-end** — a tiny file-store
   corpus with a stale hint reconciles with a non-empty `scheduleStale` list
   naming the affected gap.
7. **`cmd_doctor` warnings include the stale finding** — the doctor warnings
   list carries the same `schedule-stale` cause for the same corpus.

No network, no live issue store required.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parents[3]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import planning_canonical as pc  # noqa: E402
import planning_discover as pdisc  # noqa: E402
import planning_graph as pg  # noqa: E402
import planning_reconcile as pr  # noqa: E402


class _Captured(Exception):
    def __init__(self, payload: dict) -> None:
        super().__init__("captured-emit")
        self.payload = payload


def _run_emitting(fn, *args, **kwargs) -> dict:
    """Run an `emit()`-terminated command function, capturing its payload."""
    saved = pr.emit

    def fake_emit(obj, exit_code=0):
        raise _Captured(obj)

    pr.emit = fake_emit
    try:
        fn(*args, **kwargs)
    except _Captured as exc:
        return exc.payload
    finally:
        pr.emit = saved
    return {}


def check_hint_normalization() -> dict:
    cases = {
        "PRD 057": "57",
        "PRD 057 A1": "57",
        "057-planning-store-hardening": "57",
        "056-issue-store-deliver-progress-native-links": "56",
        "": "",
        "—": "",
        "-": "",
        "deferred: waiting on infra": "",
        "config: policy-parked": "",
    }
    mismatches = {k: pr._schedule_hint_target(k) for k, v in cases.items() if pr._schedule_hint_target(k) != v}
    ok = not mismatches
    return {"name": "hint-normalization", "ok": ok, "detail": mismatches or "all-match"}


def check_stale_hint_flagged() -> dict:
    gap = pg.GraphUnit(id="gap-049-x", unit_type="gap", status="scheduled", priority=0, schedule="PRD 056")
    real_absorber = pg.GraphUnit(
        id="057-planning-store-hardening", unit_type="prd", status="in-progress", priority=0, absorbs=("gap-049-x",)
    )
    findings = pr.schedule_stale_findings([gap, real_absorber])
    ok = (
        len(findings) == 1
        and findings[0]["unit"] == "gap-049-x"
        and findings[0]["cause"] == "schedule-stale"
        and findings[0]["label"] == pc.SCHEDULE_STALE_LABEL
        and findings[0]["actualAbsorbers"] == ["057-planning-store-hardening"]
    )
    return {"name": "stale-hint-flagged", "ok": ok, "detail": findings}


def check_matching_hint_silent() -> dict:
    gap = pg.GraphUnit(id="gap-049-x", unit_type="gap", status="scheduled", priority=0, schedule="PRD 057")
    real_absorber = pg.GraphUnit(
        id="057-planning-store-hardening", unit_type="prd", status="in-progress", priority=0, absorbs=("gap-049-x",)
    )
    findings = pr.schedule_stale_findings([gap, real_absorber])
    return {"name": "matching-hint-silent", "ok": findings == [], "detail": findings}


def check_unabsorbed_hint_stale() -> dict:
    gap = pg.GraphUnit(id="gap-049-x", unit_type="gap", status="scheduled", priority=0, schedule="PRD 057")
    other = pg.GraphUnit(id="058-unrelated", unit_type="prd", status="planned", priority=0)
    findings = pr.schedule_stale_findings([gap, other])
    ok = len(findings) == 1 and findings[0]["actualAbsorbers"] == []
    return {"name": "unabsorbed-hint-stale", "ok": ok, "detail": findings}


class _FakeIssueRecord:
    def __init__(self, unit_id: str, labels: list[str]) -> None:
        self.id = f"ISSUE-{unit_id}"
        self.unit_id = unit_id
        self.artifact_type = "gap"
        self.labels = labels
        self.body = ""
        self.comments = []
        self.title = f"gap: {unit_id}"
        self.state = "open"


def check_gap_schedule_label_decodes() -> dict:
    label = pc.gap_schedule_label("PRD 056")
    record = _FakeIssueRecord("gap-049-x", ["sw:gap", label])
    unit = pdisc._issue_record_to_unit(ROOT, record)
    ok = unit is not None and unit.schedule == "PRD 056"
    return {"name": "gap-schedule-label-decodes", "ok": ok, "detail": None if unit is None else unit.schedule}


_GAP_MD = """---
id: gap-049-x
type: gap
status: scheduled
title: Stale schedule hint
visibility: public
schedule: PRD 056
---

Gap body.
"""

_PRD_MD = """---
id: 057-planning-store-hardening
type: prd
status: in-progress
title: Hardens the planning store
visibility: public
priority: 1
absorbs: [gap-049-x]
---

PRD body.
"""


def _seed_stale_corpus(root: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=str(root), check=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=str(root), check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=str(root), check=True)
    (root / ".cursor").mkdir(parents=True, exist_ok=True)
    (root / ".cursor" / "workflow.config.json").write_text(
        json.dumps({"planning": {"store": {"backend": "in-repo-public"}}}, indent=2) + "\n",
        encoding="utf-8",
    )
    gap_dir = root / "docs" / "planning" / "gap" / "gap-049-x"
    gap_dir.mkdir(parents=True, exist_ok=True)
    (gap_dir / "gap-049-x.md").write_text(_GAP_MD, encoding="utf-8")
    prd_dir = root / "docs" / "planning" / "prd" / "057-planning-store-hardening"
    prd_dir.mkdir(parents=True, exist_ok=True)
    (prd_dir / "057-planning-store-hardening.md").write_text(_PRD_MD, encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=str(root), check=True)
    subprocess.run(["git", "commit", "-q", "-m", "seed"], cwd=str(root), check=True)
    subprocess.run(["git", "checkout", "-q", "-b", "feat/schedule-hint-fixture"], cwd=str(root), check=True)


def check_reconcile_core_surfaces_stale() -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _seed_stale_corpus(root)
        result = pr.reconcile_core(root, dry_run=True)
    stale = result.get("scheduleStale") or []
    ok = any(f.get("unit") == "gap-049-x" for f in stale)
    return {"name": "reconcile-core-surfaces-stale", "ok": ok, "detail": stale}


def check_doctor_warnings_include_stale() -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _seed_stale_corpus(root)
        payload = _run_emitting(pr.cmd_doctor, root, [])
    warnings = payload.get("warnings") or []
    ok = any(isinstance(w, dict) and w.get("cause") == "schedule-stale" and w.get("unit") == "gap-049-x" for w in warnings)
    return {"name": "doctor-warnings-include-stale", "ok": ok, "detail": warnings}


def main() -> int:
    checks = [
        check_hint_normalization(),
        check_stale_hint_flagged(),
        check_matching_hint_silent(),
        check_unabsorbed_hint_stale(),
        check_gap_schedule_label_decodes(),
        check_reconcile_core_surfaces_stale(),
        check_doctor_warnings_include_stale(),
    ]
    failures = [c for c in checks if not c["ok"]]
    verdict = "pass" if not failures else "fail"
    report = {
        "fixture": "planning-schedule-hint",
        "rid": "R17",
        "verdict": verdict,
        "checks": checks,
        "failures": failures,
    }
    print(json.dumps(report, ensure_ascii=False))
    return 0 if verdict == "pass" else 20


if __name__ == "__main__":
    raise SystemExit(main())
