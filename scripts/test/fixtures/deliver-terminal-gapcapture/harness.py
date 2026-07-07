#!/usr/bin/env python3
"""Terminal gap-capture fixture (PRD 057 R19, gap-032).

Proves, fully offline and deterministically:

1. **Suppressed on fail/aborted verdicts** — a deliver run that did not land
   green never mints gap units, regardless of how much pain it surfaced.
2. **Dedup against open gap titles, not only signal ids** — a candidate whose
   title matches an already-open gap (seeded independently, with an
   unrelated signal id) is skipped as a duplicate rather than minting a
   second unit.
3. **Substantial-vs-noise heuristic** — a low-severity, non-recurring,
   non-critical-category item is treated as noise and never captured or
   queued; a high-severity/critical-category/recurring item is substantial.
4. **Human confirmation gate** — a substantial item is never auto-captured;
   it lands in ``pending`` until its signal id is explicitly confirmed.
5. **Per-run cap** — confirmed substantial items beyond ``max_captures``
   land in ``pending`` (``cap-reached``) instead of being written.
6. **``wave_terminal.derive_terminal_pain_items``** turns run-log friction
   (repeated ack-pending halts, resume-reconcile demotions) and loop-health
   metrics (reopened phases, post-merge reverts, stabilize re-entries) into
   pain-item candidates for the engine above.
7. **``run_terminal_gap_capture`` end-to-end** — the `/sw-deliver` terminal
   entry point wires run-log + loop-health scanning into
   ``planning_gap_capture.terminal_capture`` and never raises even against a
   malformed run log (best-effort, non-gating, PRD 057 R19).

No network, no live issue store, no live orchestrator run-state required.
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

import planning_gap_capture as pgc  # noqa: E402
import wave_terminal as wt  # noqa: E402


def _seed_repo(root: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=str(root), check=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=str(root), check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=str(root), check=True)
    (root / ".cursor").mkdir(parents=True, exist_ok=True)
    (root / ".cursor" / "workflow.config.json").write_text(
        json.dumps({"planning": {"store": {"backend": "in-repo-public"}}}, indent=2) + "\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "-A"], cwd=str(root), check=True)
    subprocess.run(["git", "commit", "-q", "-m", "seed"], cwd=str(root), check=True)


def _seed_open_gap(root: Path, unit_id: str, title: str, *, status: str = "open") -> None:
    gap_dir = root / "docs" / "planning" / "gap" / unit_id
    gap_dir.mkdir(parents=True, exist_ok=True)
    (gap_dir / f"{unit_id}.md").write_text(
        "\n".join(
            [
                "---",
                f"id: {unit_id}",
                "type: gap",
                f"status: {status}",
                f"title: {title}",
                "visibility: public",
                "---",
                "",
                f"# {title}",
                "",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def check_suppressed_on_fail() -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _seed_repo(root)
        items = [{"signalId": "s1", "title": "Some pain", "category": "watchdog-halt", "severity": "critical"}]
        result = pgc.terminal_capture(root, verdict="fail", pain_items=items)
    ok = result["verdict"] == "suppressed" and result["captured"] == [] and result["pending"] == []
    return {"name": "suppressed-on-fail", "ok": ok, "detail": result}


def check_suppressed_on_aborted() -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _seed_repo(root)
        items = [{"signalId": "s1", "title": "Some pain", "category": "watchdog-halt", "severity": "critical"}]
        result = pgc.terminal_capture(root, verdict="aborted", pain_items=items)
    ok = result["verdict"] == "suppressed"
    return {"name": "suppressed-on-aborted", "ok": ok, "detail": result}


def check_dedup_against_open_gap_title() -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _seed_repo(root)
        _seed_open_gap(root, "gap-100-existing-revert-pain", "Deliver run required a post-merge revert")
        items = [
            {
                "signalId": "unrelated-signal-id",
                "title": "Deliver run required a post-merge revert",
                "category": "post-merge-revert",
                "severity": "critical",
                "confirmed": True,
            }
        ]
        result = pgc.terminal_capture(root, verdict="pass", pain_items=items)
    ok = (
        result["captured"] == []
        and len(result["skippedDuplicate"]) == 1
        and result["skippedDuplicate"][0]["existingUnitId"] == "gap-100-existing-revert-pain"
    )
    return {"name": "dedup-against-open-gap-title", "ok": ok, "detail": result}


def check_noise_skipped() -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _seed_repo(root)
        items = [
            {
                "signalId": "s-noise",
                "title": "A single low-severity blip",
                "category": "misc",
                "severity": "low",
                "recurrence": 1,
                "confirmed": True,
            }
        ]
        result = pgc.terminal_capture(root, verdict="pass", pain_items=items)
    ok = result["captured"] == [] and result["pending"] == [] and len(result["skippedNoise"]) == 1
    return {"name": "noise-skipped-never-captured", "ok": ok, "detail": result}


def check_substantial_requires_confirmation() -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _seed_repo(root)
        items = [
            {
                "signalId": "s-substantial",
                "title": "Deliver run reopened previously green phases",
                "category": "reopened-phases",
                "severity": "high",
            }
        ]
        result = pgc.terminal_capture(root, verdict="pass", pain_items=items)
    ok = (
        result["captured"] == []
        and len(result["pending"]) == 1
        and result["pending"][0]["reason"] == "awaiting-human-confirmation"
    )
    return {"name": "substantial-requires-confirmation", "ok": ok, "detail": result}


def check_confirmed_substantial_captured() -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _seed_repo(root)
        items = [
            {
                "signalId": "s-confirmed",
                "title": "Deliver run reopened previously green phases",
                "category": "reopened-phases",
                "severity": "high",
            }
        ]
        result = pgc.terminal_capture(
            root, verdict="pass", pain_items=items, confirmed_signal_ids={"s-confirmed"}
        )
    ok = (
        len(result["captured"]) == 1
        and result["captured"][0]["signalId"] == "s-confirmed"
        and not result["captured"][0]["deduped"]
        and result["pending"] == []
    )
    return {"name": "confirmed-substantial-captured", "ok": ok, "detail": result}


def check_cap_reached_moves_to_pending() -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _seed_repo(root)
        items = [
            {
                "signalId": f"s{i}",
                "title": f"Distinct substantial pain {i}",
                "category": "watchdog-halt",
                "severity": "critical",
            }
            for i in range(3)
        ]
        confirmed = {f"s{i}" for i in range(3)}
        result = pgc.terminal_capture(root, verdict="pass", pain_items=items, max_captures=1, confirmed_signal_ids=confirmed)
    ok = (
        len(result["captured"]) == 1
        and len(result["pending"]) == 2
        and all(p["reason"] == "cap-reached" for p in result["pending"])
    )
    return {"name": "cap-reached-moves-to-pending", "ok": ok, "detail": result}


def check_classify_pain_item_heuristic() -> dict:
    cases = [
        ({"severity": "low", "category": "misc", "recurrence": 1}, "noise"),
        ({"severity": "high", "category": "misc", "recurrence": 1}, "substantial"),
        ({"severity": "low", "category": "post-merge-revert", "recurrence": 1}, "substantial"),
        ({"severity": "low", "category": "misc", "recurrence": 2}, "substantial"),
        ({}, "noise"),
    ]
    mismatches = [
        (item, expected, pgc.classify_pain_item(item))
        for item, expected in cases
        if pgc.classify_pain_item(item) != expected
    ]
    return {"name": "classify-pain-item-heuristic", "ok": not mismatches, "detail": mismatches or "all-match"}


def _seed_run_log(root: Path, entries: list[dict]) -> None:
    log_path = root / ".cursor" / "sw-deliver-runs" / "run.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "w", encoding="utf-8") as f:
        for entry in entries:
            f.write(json.dumps(entry) + "\n")


def _seed_deliver_state(root: Path, state: dict) -> None:
    state_path = root / ".cursor" / "sw-deliver-runs" / "sw-deliver-state.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")


def check_derive_terminal_pain_items_from_run_log_and_loop_health() -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _seed_repo(root)
        _seed_run_log(
            root,
            [
                {"event": "ack-pending", "cadence": 2, "mergesSinceAck": 2},
                {"event": "ack-pending", "cadence": 2, "mergesSinceAck": 4},
                {"event": "resume-reconcile", "promoted": [], "demoted": ["phase-a"]},
            ],
        )
        _seed_deliver_state(
            root,
            {
                "reopenedPhases": 2,
                "postMergeReverts": 1,
                "reviewRounds": 4,
                "benefitMetric": {"stabilizeReentries": [1, 2, 3]},
            },
        )
        items = wt.derive_terminal_pain_items(root, {})
    categories = {item["category"] for item in items}
    expected = {"ack-pending", "resume-reconcile", "reopened-phases", "post-merge-revert", "stabilize-reentry"}
    ok = expected.issubset(categories)
    return {"name": "derive-terminal-pain-items", "ok": ok, "detail": sorted(categories)}


def check_run_terminal_gap_capture_end_to_end() -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _seed_repo(root)
        _seed_run_log(
            root,
            [
                {"event": "resume-reconcile", "promoted": [], "demoted": ["phase-a", "phase-b"]},
            ],
        )
        _seed_deliver_state(root, {"postMergeReverts": 1})
        result = wt.run_terminal_gap_capture(root, verdict="pass")
    pending_titles = {p["title"] for p in result.get("pending") or []}
    ok = (
        "Deliver resume repeatedly demoted unpushed phase merges" in pending_titles
        and "Deliver run required a post-merge revert" in pending_titles
    )
    return {"name": "run-terminal-gap-capture-end-to-end", "ok": ok, "detail": result}


def check_run_terminal_gap_capture_never_raises_on_malformed_log() -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _seed_repo(root)
        log_path = root / ".cursor" / "sw-deliver-runs" / "run.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text("{not valid json\n", encoding="utf-8")
        try:
            out = wt.terminal_gap_capture_best_effort(root, verdict="pass")
            ok = True
        except Exception:  # noqa: BLE001 — this is exactly what must never happen
            out = None
            ok = False
    return {"name": "best-effort-never-raises-on-malformed-log", "ok": ok, "detail": out}


def check_suppressed_verdict_skips_run_terminal_gap_capture() -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _seed_repo(root)
        _seed_deliver_state(root, {"postMergeReverts": 3})
        result = wt.run_terminal_gap_capture(root, verdict="blocked")
    ok = result.get("verdict") == "suppressed"
    return {"name": "run-terminal-gap-capture-honors-suppression", "ok": ok, "detail": result}


def main() -> int:
    checks = [
        check_suppressed_on_fail(),
        check_suppressed_on_aborted(),
        check_dedup_against_open_gap_title(),
        check_noise_skipped(),
        check_substantial_requires_confirmation(),
        check_confirmed_substantial_captured(),
        check_cap_reached_moves_to_pending(),
        check_classify_pain_item_heuristic(),
        check_derive_terminal_pain_items_from_run_log_and_loop_health(),
        check_run_terminal_gap_capture_end_to_end(),
        check_run_terminal_gap_capture_never_raises_on_malformed_log(),
        check_suppressed_verdict_skips_run_terminal_gap_capture(),
    ]
    failures = [c for c in checks if not c["ok"]]
    verdict = "pass" if not failures else "fail"
    report = {
        "fixture": "deliver-terminal-gapcapture",
        "rid": "R19",
        "verdict": verdict,
        "checks": checks,
        "failures": failures,
    }
    print(json.dumps(report, ensure_ascii=False))
    return 0 if verdict == "pass" else 20


if __name__ == "__main__":
    raise SystemExit(main())
