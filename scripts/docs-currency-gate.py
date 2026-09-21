#!/usr/bin/env python3
"""Hard-block when living-doc ledger drifts from durable deliver state for the current run (R50). """
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from datetime import date
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from _sw.cli import run_module_main

# Documentation artifacts that must ship in the same release as the code they describe (PRD 081 R21/R24).
# Consumed by phase-18 fixtures (`scripts/unit_tests/docs/test_docs_currency_081.py`).
COMMAND_DOC_CURRENCY_ARTIFACTS: tuple[dict[str, object], ...] = (
    {
        "id": "sw-doc",
        "doc": "core/commands/sw-doc.md",
        "code": (
            "scripts/doc_loop.py",
            "scripts/wave_spec_seed.py",
            "scripts/docs_worktree.py",
            "scripts/docs_pr.py",
        ),
        "needles": (
            "sw-doc-runs",
            "Durable doc-run driver",
            "Publication path by store mode",
            "UNREACHABLE_PUBLICATION_STAGES",
            "docs_pr.py",
        ),
    },
    {
        "id": "sw-tasks",
        "doc": "core/commands/sw-tasks.md",
        "code": ("scripts/doc_loop.py", "scripts/check_frozen_lib.py"),
        "needles": ("noFreeze", "Freeze ownership", "related-work", "doc-loop"),
    },
    {
        "id": "sw-freeze",
        "doc": "core/commands/sw-freeze.md",
        "code": ("scripts/check_frozen_lib.py", "scripts/check-frozen.py", "scripts/planning_store.py"),
        "needles": (
            "Freeze receipt",
            "durabilityState",
            "driverInvoked",
            "durability-not-verified",
        ),
    },
    {
        "id": "sw-deliver",
        "doc": "core/commands/sw-deliver.md",
        "code": (
            "scripts/wave_deliver.py",
            "scripts/wave_terminal.py",
            "scripts/wave_run_adopt.py",
            "scripts/wave_deliver_loop.py",
        ),
        "needles": (
            "list, resume, finalize",
            "Resume cardinality",
            "Drain-budget",
            "Run finalization vs",
            "finalize:merge-unverified",
        ),
    },
)


def enumerate_command_doc_currency_artifacts() -> tuple[dict[str, object], ...]:
    """Return the canonical command-documentation currency artifact set."""
    return COMMAND_DOC_CURRENCY_ARTIFACTS


INTERNAL_ARTIFACT_CURRENCY_CHECKS: tuple[str, ...] = (
    "release-guide-artifacts",
    "memory-doc-currency",
    "planning-doc-currency",
    "command-documentation-currency",
)

PROFILE_PLUGIN_SELF = "plugin-self"
PROFILE_CONSUMER = "consumer"


def artifact_currency_skip_reasons(
    *, consumer_repo: bool, skip_artifact_currency: bool
) -> tuple[str, ...]:
    reasons: list[str] = []
    if consumer_repo:
        reasons.append("consumer-repo")
    if skip_artifact_currency:
        reasons.append("skip-artifact-currency")
    return tuple(reasons)


def resolve_r24_posture_verdict(root: Path) -> dict[str, object]:
    """Return authoritative R24 posture verdict; fail closed on ambiguity."""
    from repository_context import detect_repository_posture

    try:
        verdict = detect_repository_posture(root)
    except Exception as exc:
        return {"ready": False, "reason": str(exc)}
    return {
        "ready": True,
        "posture": verdict.posture,
        "reason": verdict.reason,
        "sentinelPresent": verdict.sentinel_present,
        "heuristicMarkersPresent": verdict.heuristic_markers_present,
    }


def resolve_r28_dist_trust_readiness(root: Path, posture: str) -> dict[str, object]:
    """Return R28 dist-trust readiness for profile rollout (PRD 338 R31)."""
    from sw_scripts_resolve import (
        dist_trust_verdict_for_install,
        is_dist_only_plugin_scripts,
        resolve_scripts_dir,
        scripts_dir_is_trusted,
    )

    if posture == PROFILE_PLUGIN_SELF:
        scripts = root / "scripts"
        if scripts_dir_is_trusted(scripts, workspace=root):
            return {"ready": True, "source": "self-repo-markers"}
        return {"ready": False, "reason": "r28-self-repo-markers-missing"}

    result = resolve_scripts_dir(root)
    if result.error:
        return {"ready": True, "source": "consumer-no-trusted-scripts"}
    if result.path is None or result.source is None:
        return {"ready": True, "source": "consumer-no-trusted-scripts"}
    if not str(result.source).endswith("-dist"):
        return {"ready": True, "source": "consumer-non-dist-scripts", "scriptsSource": result.source}
    if not is_dist_only_plugin_scripts(result.path):
        return {"ready": False, "reason": "r28-dist-source-without-dist-only-scripts"}
    try:
        verdict = dist_trust_verdict_for_install(result.path.parent, workspace=root)
    except Exception as exc:
        return {"ready": False, "reason": f"r28-dist-trust:{exc}"}
    if verdict.get("verdict") != "ok":
        return {
            "ready": False,
            "reason": "r28-dist-trust-verdict-not-ok",
            "verdict": verdict,
        }
    return {
        "ready": True,
        "source": "consumer-dist-trust",
        "scriptsSource": result.source,
        "trustDigest": verdict.get("trustDigest"),
        "anchorId": verdict.get("anchorId"),
    }


def resolve_docs_currency_profile(root: Path) -> dict[str, object]:
    """Select consumer vs plugin-self artifact profile from merged R24/R28 trust verdicts."""
    r24 = resolve_r24_posture_verdict(root)
    if not r24.get("ready"):
        return {
            "profile": None,
            "rolloutBlocked": True,
            "blockReason": "r24-not-ready",
            "r24": r24,
        }

    posture = str(r24.get("posture") or "")
    r28 = resolve_r28_dist_trust_readiness(root, posture)
    if not r28.get("ready"):
        return {
            "profile": None,
            "rolloutBlocked": True,
            "blockReason": "r28-not-ready",
            "r24": r24,
            "r28": r28,
        }

    profile = PROFILE_PLUGIN_SELF if posture == PROFILE_PLUGIN_SELF else PROFILE_CONSUMER
    return {
        "profile": profile,
        "rolloutBlocked": False,
        "consumerRepo": profile == PROFILE_CONSUMER,
        "runArtifactCurrency": profile == PROFILE_PLUGIN_SELF,
        "r24": r24,
        "r28": r28,
    }


def build_artifact_currency_skipped(
    *, consumer_repo: bool, skip_artifact_currency: bool
) -> list[dict[str, str]]:
    reasons = artifact_currency_skip_reasons(
        consumer_repo=consumer_repo,
        skip_artifact_currency=skip_artifact_currency,
    )
    if not reasons:
        return []
    return [
        {"check": check, "reason": reason}
        for check in INTERNAL_ARTIFACT_CURRENCY_CHECKS
        for reason in reasons
    ]


def _git_last_commit_epoch(root: Path, rel: str) -> int | None:
    import subprocess

    proc = subprocess.run(
        ["git", "log", "-1", "--format=%ct", "--", rel],
        cwd=str(root),
        text=True,
        capture_output=True,
    )
    if proc.returncode != 0 or not proc.stdout.strip():
        return None
    try:
        return int(proc.stdout.strip())
    except ValueError:
        return None


def check_command_documentation_currency(root: Path) -> list[dict[str, object]]:
    """Fail when a listed command doc is missing, needle-incomplete, or older than its code surface."""
    drift: list[dict[str, object]] = []
    for entry in COMMAND_DOC_CURRENCY_ARTIFACTS:
        doc_rel = str(entry["doc"])
        doc_path = root / doc_rel
        artifact_id = str(entry.get("id") or doc_rel)
        if not doc_path.is_file():
            drift.append({"kind": "command-doc-missing", "artifact": artifact_id, "doc": doc_rel})
            continue
        text = doc_path.read_text(encoding="utf-8")
        for needle in entry.get("needles") or ():
            if str(needle) not in text:
                drift.append(
                    {
                        "kind": "command-doc-needle-missing",
                        "artifact": artifact_id,
                        "doc": doc_rel,
                        "needle": needle,
                    }
                )
        doc_epoch = _git_last_commit_epoch(root, doc_rel)
        code_paths = [str(p) for p in entry.get("code") or () if (root / str(p)).is_file()]
        code_epochs = [e for p in code_paths if (e := _git_last_commit_epoch(root, p)) is not None]
        if doc_epoch is not None and code_epochs and doc_epoch < max(code_epochs):
            drift.append(
                {
                    "kind": "command-doc-stale",
                    "artifact": artifact_id,
                    "doc": doc_rel,
                    "docCommitEpoch": doc_epoch,
                    "codePaths": code_paths,
                    "maxCodeCommitEpoch": max(code_epochs),
                }
            )
        drift.extend(_command_doc_downstream_drift(root, entry))
    return drift


def command_doc_currency_doc_rels() -> frozenset[str]:
    return frozenset(str(entry["doc"]) for entry in COMMAND_DOC_CURRENCY_ARTIFACTS)


def is_command_doc_currency_artifact(artifact_rel: str) -> bool:
    normalized = artifact_rel.strip().lstrip("/")
    return normalized in command_doc_currency_doc_rels()


def _command_doc_downstream_drift(root: Path, entry: dict[str, object]) -> list[dict[str, object]]:
    """Fail closed when needles/epochs match but stamp-chain downstream artifacts lag (PRD 362 R14–R17)."""
    from agent_instruction_compiler import check_command_doc_instruction_currency
    from planning_paths import GOLDEN_MANIFEST_REL

    artifact_id = str(entry.get("id") or entry["doc"])
    doc_rel = str(entry["doc"])
    drift: list[dict[str, object]] = []

    for row in check_command_doc_instruction_currency(root, doc_rel=doc_rel):
        drift.append({**row, "artifact": artifact_id, "doc": doc_rel})

    golden = root / GOLDEN_MANIFEST_REL
    if (root / "dist" / "cursor").is_dir():
        try:
            import golden_manifest as gm
        except ImportError:
            gm = None  # type: ignore[assignment]
        if gm is not None:
            result = gm.check_staleness(root, manifest_path=golden)
            if result.get("verdict") != "pass" or result.get("stale"):
                drift.append(
                    {
                        "kind": "command-doc-golden-stale",
                        "artifact": artifact_id,
                        "doc": doc_rel,
                        "manifest": GOLDEN_MANIFEST_REL,
                        "detail": result,
                    }
                )

    for platform in ("cursor", "claude-code"):
        core_doc = root / doc_rel
        mirror = root / "dist" / platform / "commands" / Path(doc_rel).name
        if not core_doc.is_file() or not mirror.is_file():
            continue
        if hashlib.sha256(core_doc.read_bytes()).digest() != hashlib.sha256(mirror.read_bytes()).digest():
            drift.append(
                {
                    "kind": "command-doc-dist-mirror-stale",
                    "artifact": artifact_id,
                    "doc": doc_rel,
                    "platform": platform,
                    "mirror": mirror.relative_to(root).as_posix(),
                }
            )
    return drift


def touch_command_doc_currency_marker(path: Path) -> str:
    """Bump docs-currency marker on a command doc without clearing freeze state (PRD 362 R5)."""
    text = path.read_text(encoding="utf-8")
    marker = f"doc_currency_at: {date.today().isoformat()}"
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            block = text[4:end]
            lines = [line for line in block.splitlines() if not line.strip().startswith("doc_currency_at:")]
            lines.append(marker)
            text = "---\n" + "\n".join(lines) + "\n---" + text[end + 4 :]
        else:
            text = f"---\n{marker}\n---\n" + text
    else:
        text = f"---\n{marker}\n---\n" + text
    path.write_text(text, encoding="utf-8")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def regen_command_doc_currency_downstream(root: Path) -> dict[str, Any]:
    """Compiler write → platform-scoped generate → snapshot-tree (PRD 362 R5/R15/R16)."""
    from planning_paths import GOLDEN_MANIFEST_REL

    root = root.resolve()
    compiler = root / "scripts" / "agent_instruction_compiler.py"
    golden = root / GOLDEN_MANIFEST_REL
    steps: list[dict[str, object]] = []

    proc = subprocess.run(
        [sys.executable, str(compiler)],
        cwd=str(root),
        text=True,
        capture_output=True,
    )
    steps.append({"step": "agent_instruction_compiler-write", "exitCode": proc.returncode})
    if proc.returncode != 0:
        return {
            "verdict": "fail",
            "action": "regen-command-doc-currency",
            "steps": steps,
            "stderr": proc.stderr or proc.stdout,
        }

    for platform in ("cursor", "claude-code"):
        gen = subprocess.run(
            [sys.executable, "-m", "sw", "generate", platform],
            cwd=str(root),
            text=True,
            capture_output=True,
        )
        steps.append({"step": f"sw-generate-{platform}", "exitCode": gen.returncode})
        if gen.returncode != 0:
            return {
                "verdict": "fail",
                "action": "regen-command-doc-currency",
                "steps": steps,
                "stderr": gen.stderr or gen.stdout,
            }

    snap = subprocess.run(
        [
            sys.executable,
            str(root / "scripts" / "snapshot-tree.py"),
            str(golden),
            "--root",
            str(root),
        ],
        cwd=str(root),
        text=True,
        capture_output=True,
    )
    steps.append({"step": "snapshot-tree", "exitCode": snap.returncode, "manifest": GOLDEN_MANIFEST_REL})
    if snap.returncode != 0:
        return {
            "verdict": "fail",
            "action": "regen-command-doc-currency",
            "steps": steps,
            "stderr": snap.stderr or snap.stdout,
        }

    return {"verdict": "pass", "action": "regen-command-doc-currency", "steps": steps}


def restamp_command_doc_currency(root: Path, artifact_rel: str) -> dict[str, Any]:
    """Restamp one command doc and run the stamp-chain regen (PRD 362 R5)."""
    normalized = artifact_rel.strip().lstrip("/")
    if not is_command_doc_currency_artifact(normalized):
        return {
            "verdict": "fail",
            "action": "restamp-command-doc-currency",
            "error": "not-command-doc-currency-artifact",
            "artifact": normalized,
        }
    path = (root / normalized).resolve()
    if not path.is_file():
        return {
            "verdict": "fail",
            "action": "restamp-command-doc-currency",
            "error": "artifact-missing",
            "artifact": normalized,
        }
    revision = touch_command_doc_currency_marker(path)
    regen = regen_command_doc_currency_downstream(root)
    regen["artifact"] = normalized
    regen["revision"] = revision
    return regen


def _cmd_restamp_command_doc(argv: list[str]) -> int:
    if len(argv) < 3:
        print(json.dumps({"verdict": "fail", "error": "usage: restamp-command-doc <repo_root> <artifact_rel>"}))
        return 2
    root = Path(argv[1])
    payload = restamp_command_doc_currency(root, argv[2])
    print(json.dumps(payload))
    return 0 if payload.get("verdict") == "pass" else 20


def _cmd_regen_command_doc_chain(argv: list[str]) -> int:
    if len(argv) < 2:
        print(json.dumps({"verdict": "fail", "error": "usage: regen-command-doc-chain <repo_root>"}))
        return 2
    payload = regen_command_doc_currency_downstream(Path(argv[1]))
    print(json.dumps(payload))
    return 0 if payload.get("verdict") == "pass" else 20


def _parse_run_id(argv: list[str]) -> tuple[str | None, bool, list[str]]:
    cleaned: list[str] = []
    run_id: str | None = None
    skip_artifact_currency: bool = False
    idx = 0
    while idx < len(argv):
        token = argv[idx]
        if token == "--run-id" and idx + 1 < len(argv):
            run_id = argv[idx + 1]
            idx += 2
            continue
        if token == "--skip-artifact-currency":
            skip_artifact_currency = True
            idx += 1
            continue
        cleaned.append(token)
        idx += 1
    return run_id, skip_artifact_currency, cleaned


def resolve_plan_path(
    root: Path,
    state: dict[str, object],
    explicit_plan: Path | None = None,
    *,
    run_id: str | None = None,
) -> Path:
    """Resolve the deliver plan through the run helper when a run id is available (R18)."""
    from wave_run_paths import global_plan_path, is_repository_global_plan_path, plan_path as run_plan_path
    from wave_run_plan import resolve_run_id

    active_run_id = run_id or state.get("runId")
    if active_run_id:
        return run_plan_path(root, resolve_run_id({**state, "runId": active_run_id}))

    if state.get("planHash") and state.get("runId"):
        return run_plan_path(root, resolve_run_id(state))

    if explicit_plan is not None:
        resolved = explicit_plan.resolve()
        if is_repository_global_plan_path(root, resolved):
            return resolved
        return resolved

    return global_plan_path(root)


def _resolve_argv(argv: list[str]) -> list[str]:
    if len(argv) >= 3 and argv[1] == "--state-root":
        import sys as _sys

        _sys.stderr.write(
            "DEPRECATION: docs-currency-gate.py --state-root is deprecated; "
            "use four positional args (repo_root state_root state.json plan.json) or --run-id\n"
        )
        state_root = Path(argv[2])
        state_path = state_root / ("." + "cursor") / "sw-deliver-state.json"
        if not state_path.is_file():
            matches = sorted((state_root / ("." + "cursor")).glob("sw-deliver-state.*.json"))
            state_path = matches[0] if len(matches) == 1 else state_path
        state: dict[str, object] = {}
        if state_path.is_file():
            try:
                loaded = json.loads(state_path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    state = loaded
            except json.JSONDecodeError:
                state = {}
        plan_path = resolve_plan_path(state_root, state)
        return [argv[0], str(state_root), str(state_root), str(state_path), str(plan_path)]
    return argv


def main(argv: list[str] | None = None) -> int:
    raw_argv = list(argv if argv is not None else sys.argv)
    if len(raw_argv) > 1 and raw_argv[1] == "restamp-command-doc":
        return _cmd_restamp_command_doc(raw_argv)
    if len(raw_argv) > 1 and raw_argv[1] == "regen-command-doc-chain":
        return _cmd_regen_command_doc_chain(raw_argv)
    run_id, skip_artifact_currency, stripped = _parse_run_id(raw_argv)
    resolved = _resolve_argv(stripped)
    root = Path(resolved[1])
    state_root = Path(resolved[2])
    state = json.loads(Path(resolved[3]).read_text())
    explicit_plan = Path(resolved[4]) if len(resolved) > 4 else None
    plan_file = resolve_plan_path(root, state, explicit_plan, run_id=run_id)
    plan = json.loads(plan_file.read_text(encoding="utf-8")) if plan_file.is_file() else {}

    prd = str(state.get("prd_number") or plan.get("prd_number") or "").zfill(3)
    if not prd or prd == "000":
        print(json.dumps({"verdict": "fail", "error": "prd_number missing"}))
        sys.exit(2)

    phases = state.get("phases") or {}
    from wave_living_docs import (
        derive_index_status,
        living_doc_write_banned,
        read_completion_evidence,
        read_index_status_evidence,
    )
    from wave_state import phase_complete, run_slug_from_state

    profile_resolution = resolve_docs_currency_profile(root)
    if profile_resolution.get("rolloutBlocked"):
        print(
            json.dumps(
                {
                    "verdict": "fail",
                    "action": "docs-currency-gate",
                    "prd": prd,
                    "error": "trust-not-ready",
                    "blockReason": profile_resolution.get("blockReason"),
                    "profileResolution": profile_resolution,
                }
            )
        )
        sys.exit(2)

    consumer_repo = bool(profile_resolution.get("consumerRepo"))
    profile = str(profile_resolution.get("profile") or "")
    artifact_currency_skipped = build_artifact_currency_skipped(
        consumer_repo=consumer_repo,
        skip_artifact_currency=skip_artifact_currency,
    )
    run_artifact_currency = bool(profile_resolution.get("runArtifactCurrency")) and not skip_artifact_currency

    all_green = bool(phases) and all(phase_complete((m or {}).get("status")) for m in phases.values())
    merged_main = False
    try:
        import subprocess

        proc = subprocess.run(
            [sys.executable, str(root / "scripts" / "wave_compound.py"), str(state_root), "completion", "check-merge"],
            cwd=str(state_root),
            text=True,
            capture_output=True,
        )
        if proc.returncode == 0:
            merged_main = bool(json.loads(proc.stdout).get("merged"))
    except Exception:
        pass

    expected = derive_index_status(state, merged_main)
    slug = str(run_slug_from_state(state) or plan.get("slug") or "").strip() or None

    def _index_status_from_file() -> str | None:
        index_path = root / "docs" / "prds" / "INDEX.md"
        if not index_path.is_file():
            return None
        for line in index_path.read_text(encoding="utf-8").splitlines():
            if not line.startswith("|") or line.startswith("| #") or line.startswith("|---"):
                continue
            parts = [p.strip() for p in line.strip("|").split("|")]
            if len(parts) >= 4 and parts[0].zfill(3) == prd:
                return parts[4] if len(parts) >= 5 else parts[3]
        return None

    def _completion_in_log() -> bool:
        log_path = root / "docs" / "prds" / "COMPLETION-LOG.md"
        if not log_path.is_file():
            return False
        log_text = log_path.read_text(encoding="utf-8")
        return f"| {prd.lstrip('0')} |" in log_text or f"| {prd} |" in log_text

    banned = living_doc_write_banned(root)
    use_store_evidence = banned or consumer_repo
    slug = str(run_slug_from_state(state) or "")
    file_row_status = _index_status_from_file()
    index_status = None
    if use_store_evidence:
        ev = read_index_status_evidence(root, prd, slug=slug)
        if ev:
            index_status = str(ev.get("status") or "")
        else:
            index_status = file_row_status
    else:
        index_status = file_row_status

    # When issue projection lags but tracked INDEX + deliver state say complete, reconcile (R4).
    if (
        use_store_evidence
        and all_green
        and expected == "complete"
        and index_status not in (None, expected)
        and file_row_status == expected
    ):
        index_status = file_row_status

    drift = []
    if index_status is None:
        drift.append({"kind": "index-missing-row", "prd": prd})
    elif index_status != expected:
        drift.append({"kind": "index-status", "prd": prd, "expected": expected, "actual": index_status})

    # COMPLETION-LOG / store completion events
    if all_green:
        has_completion = read_completion_evidence(root, prd) is not None if use_store_evidence else False
        if use_store_evidence and not has_completion:
            has_completion = _completion_in_log()
        elif not use_store_evidence:
            has_completion = _completion_in_log()
        if not has_completion:
            drift.append({"kind": "completion-log-missing", "prd": prd})

    # GAP-BACKLOG: unresolved rows for this PRD when it is complete (R3 / PRD 048)
    gap_path = root / "docs" / "prds" / "GAP-BACKLOG.md"
    if expected == "complete" and not banned and gap_path.is_file():
        from gap_backlog import parse_gap_backlog

        backlog = parse_gap_backlog(gap_path.read_text(encoding="utf-8"))
        prd_n = str(int(prd)) if prd.isdigit() else prd.lstrip("0") or prd
        sched_re = re.compile(
            rf"^PRD\s+0*{re.escape(str(int(prd_n))) if prd_n.isdigit() else re.escape(prd_n)}(?:\s+A\d+)?$",
            re.I,
        )
        for row in backlog.rows:
            st = row.status.lower()
            if st == "open" or (st == "scheduled" and sched_re.match(row.schedule.strip())):
                drift.append({"kind": "gap-still-open", "prd": prd, "row": row.gap_id})

    # GAP-BACKLOG index/table integrity (R54) — skip read-only separate-project shim (R4 / PRD 062)
    import subprocess

    try:
        from planning_migrate_issue_store import gap_backlog_is_readonly
    except ImportError:
        gap_backlog_is_readonly = None  # type: ignore[assignment,misc]

    gap_backlog_readonly = (
        gap_backlog_is_readonly(root) if gap_backlog_is_readonly is not None else False
    )
    if not gap_backlog_readonly:
        gb = subprocess.run(
            [sys.executable, str(root / "scripts" / "gap_backlog.py"), "--root", str(root), "check"],
            text=True,
            capture_output=True,
        )
        if gb.returncode != 0:
            try:
                payload = json.loads(gb.stdout or gb.stderr)
            except json.JSONDecodeError:
                payload = {"error": gb.stderr or gb.stdout}
            drift.append({"kind": "gap-backlog-integrity", "detail": payload})

    if run_artifact_currency:
        from docs_currency_081 import check_release_guide_artifacts
        from docs_currency_memory import check_memory_doc_currency
        from docs_currency_planning import check_planning_doc_currency

        guide_drift = check_release_guide_artifacts(root)
        if guide_drift:
            drift.extend(guide_drift)

        memory_drift = check_memory_doc_currency(root)
        if memory_drift:
            drift.extend(memory_drift)

        planning_drift = check_planning_doc_currency(root)
        if planning_drift:
            drift.extend(planning_drift)

    if drift:
        print(json.dumps({"verdict": "fail", "action": "docs-currency-gate", "prd": prd, "drift": drift}))
        sys.exit(1)

    if run_artifact_currency:
        command_doc_drift = check_command_documentation_currency(root)
        if command_doc_drift:
            print(
                json.dumps(
                    {
                        "verdict": "fail",
                        "action": "docs-currency-gate",
                        "prd": prd,
                        "drift": command_doc_drift,
                        "artifactSet": [str(e.get("id") or e.get("doc")) for e in COMMAND_DOC_CURRENCY_ARTIFACTS],
                    }
                )
            )
            sys.exit(1)

    pass_payload: dict[str, object] = {
        "verdict": "pass",
        "action": "docs-currency-gate",
        "prd": prd,
        "indexStatus": index_status,
        "expected": expected,
        "planPath": str(plan_file),
        "profile": profile,
        "profileResolution": profile_resolution,
        "artifactSet": [str(e.get("id") or e.get("doc")) for e in COMMAND_DOC_CURRENCY_ARTIFACTS],
    }
    if artifact_currency_skipped:
        pass_payload["skipped"] = artifact_currency_skipped
    print(json.dumps(pass_payload))
    return 0


if __name__ == "__main__":
    run_module_main(main)
