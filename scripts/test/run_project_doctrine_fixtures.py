#!/usr/bin/env python3
"""Integrated ProjectDoctrine adoption acceptance (PRD 330 R2, R6, R11, R13, R14).

One suite exercises default-truth parity, schema validation, brownfield draft synthesis,
conflict preservation, explicit promote, accept/reject, self-leakage rejection, and no new
command registration.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
SCRIPTS = SCRIPT_DIR.parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from _sw.cli import run_module_main
from _sw.vendor_paths import repo_root
from documented_defaults_check import run_check
from project_baseline import synthesize_baseline, validate_baseline as validate_baseline_struct
from project_doctrine import (
    accept_doctrine,
    load_doctrine,
    promote_baseline,
    reject_adoption,
    validate_baseline,
    validate_doctrine,
    write_baseline_draft,
)
from project_doctrine_leakage import evaluate_doctrine

COMMANDS_DIRS = (
    Path("core/commands"),
    Path("commands"),
    Path("dist/cursor/commands"),
    Path("dist/claude-code/commands"),
)
FORBIDDEN_COMMAND_STEMS = frozenset({"sw-explore", "sw-codebase-design"})


def _obs(key: str, claim: str, uri: str, *, confidence: str = "high") -> dict:
    return {
        "key": key,
        "claim": claim,
        "confidence": confidence,
        "sourceEvidence": {"uri": uri},
    }


def _minimal_doctrine(**overrides: object) -> dict:
    doc: dict = {
        "id": "consumer-doctrine",
        "version": "ProjectDoctrine@v1",
        "provenance": {
            "createdAt": "2026-08-24T00:00:00Z",
            "source": "operator-review",
        },
        "confidence": "high",
        "sourceRefs": [{"uri": "file://repo/README.md"}],
    }
    doc.update(overrides)
    return doc


def _tmp_git_repo() -> Path:
    tmp = Path(tempfile.mkdtemp(prefix="sw-project-doctrine-"))
    repo = tmp / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "sw-test@example.com"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Shipwright Test"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    (repo / "README.md").write_text("fixture\n", encoding="utf-8")
    (repo / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    return repo


def scenario_default_truth_parity(root: Path) -> None:
    result = run_check(root)
    if result.get("verdict") != "pass":
        raise AssertionError(f"documented defaults drift: {result}")


def scenario_schema_validation(root: Path) -> None:
    doctrine = _minimal_doctrine()
    d_verdict = validate_doctrine(doctrine, root)
    if d_verdict.get("verdict") != "pass":
        raise AssertionError(f"doctrine schema fail: {d_verdict}")
    baseline = synthesize_baseline(
        [
            _obs(
                "runtime.primary",
                "Primary runtime appears to be Python.",
                "file://repo/pyproject.toml",
            )
        ],
        created_at="2026-08-25T00:00:00Z",
    )
    b_verdict = validate_baseline(baseline, root)
    if b_verdict.get("verdict") != "pass":
        raise AssertionError(f"baseline schema fail: {b_verdict}")
    if validate_baseline_struct(baseline):
        raise AssertionError(f"baseline structural errors: {validate_baseline_struct(baseline)}")
    bad = dict(doctrine)
    bad.pop("id")
    if validate_doctrine(bad, root).get("verdict") == "pass":
        raise AssertionError("expected missing-id doctrine to fail validation")


def scenario_brownfield_draft_and_conflicts(root: Path) -> None:
    draft = synthesize_baseline(
        [
            _obs(
                "runtime.primary",
                "Primary runtime appears to be Python.",
                "file://repo/pyproject.toml",
            ),
            _obs(
                "runtime.primary",
                "Primary runtime appears to be Node.js.",
                "file://repo/package.json",
            ),
        ],
        created_at="2026-08-25T00:00:00Z",
    )
    if draft.get("status") != "draft":
        raise AssertionError(f"expected draft status, got {draft.get('status')}")
    conflicts = draft.get("conflicts") or []
    if len(conflicts) != 1:
        raise AssertionError(f"expected one preserved conflict, got {conflicts}")
    if conflicts[0].get("status") != "open":
        raise AssertionError("conflict must remain open until review")
    claims = {obs["claim"] for obs in conflicts[0]["observations"]}
    if "Primary runtime appears to be Python." not in claims:
        raise AssertionError("python claim missing from conflict observations")
    if "Primary runtime appears to be Node.js." not in claims:
        raise AssertionError("node claim missing from conflict observations")
    if draft.get("facts"):
        raise AssertionError("contradictory observations must not collapse into facts")


def scenario_explicit_promote_accept_reject(root: Path) -> None:
    repo = _tmp_git_repo()
    try:
        agree = synthesize_baseline(
            [
                _obs(
                    "runtime.primary",
                    "Primary runtime appears to be Python.",
                    "file://repo/pyproject.toml",
                )
            ],
            created_at="2026-08-25T00:00:00Z",
        )
        written = write_baseline_draft(repo, agree, actor="synthesis")
        if written.verdict != "pass":
            raise AssertionError(f"write draft failed: {written}")
        if load_doctrine(repo) is not None:
            raise AssertionError("draft write must not create doctrine")
        refused = promote_baseline(repo, actor="operator", confirm=False)
        if refused.verdict != "refused":
            raise AssertionError(f"promote without confirm must refuse, got {refused}")
        if load_doctrine(repo) is not None:
            raise AssertionError("unconfirmed promote must leave no doctrine")
        promoted = promote_baseline(repo, actor="operator", confirm=True)
        if promoted.verdict != "pass":
            raise AssertionError(f"explicit promote failed: {promoted}")
        if load_doctrine(repo) is None:
            raise AssertionError("explicit promote must create repo-local doctrine")

        rejected = reject_adoption(repo)
        if rejected.verdict != "pass":
            raise AssertionError(f"reject failed: {rejected}")
        if load_doctrine(repo) is not None:
            raise AssertionError("reject must clear doctrine")

        accepted = accept_doctrine(repo, _minimal_doctrine(), actor="operator")
        if accepted.verdict != "pass":
            raise AssertionError(f"accept failed: {accepted}")
        if load_doctrine(repo) is None:
            raise AssertionError("accept must leave durable doctrine")
        cleared = reject_adoption(repo)
        if cleared.verdict != "pass" or load_doctrine(repo) is not None:
            raise AssertionError("post-accept reject must clear doctrine")
    finally:
        shutil.rmtree(repo.parent, ignore_errors=True)


def scenario_self_leakage_rejection() -> None:
    clean = evaluate_doctrine(_minimal_doctrine())
    if clean.get("verdict") != "pass":
        raise AssertionError(f"clean consumer doctrine must pass: {clean}")
    leaked = evaluate_doctrine(
        _minimal_doctrine(shipwrightSelf={"statements": ["Broker-only credential access"]})
    )
    if leaked.get("verdict") != "fail":
        raise AssertionError(f"self-leakage must fail: {leaked}")
    if not any(f.get("rule") == "forbidden-embed-key" for f in leaked.get("findings") or []):
        raise AssertionError(f"expected forbidden-embed-key finding: {leaked}")


def scenario_no_new_command(root: Path) -> None:
    found: list[str] = []
    for directory in COMMANDS_DIRS:
        base = root / directory
        if not base.is_dir():
            continue
        for path in base.rglob("*"):
            if not path.is_file():
                continue
            if path.stem in FORBIDDEN_COMMAND_STEMS or "sw-explore" in path.name:
                found.append(str(path.relative_to(root)))
            if "sw-codebase-design" in path.name:
                found.append(str(path.relative_to(root)))
    if found:
        raise AssertionError(f"unexpected forbidden command registration: {found}")


def main() -> int:
    root = repo_root(__file__)
    failures: list[str] = []
    scenarios = [
        ("default-truth-parity", lambda: scenario_default_truth_parity(root)),
        ("schema-validation", lambda: scenario_schema_validation(root)),
        ("brownfield-draft-and-conflicts", lambda: scenario_brownfield_draft_and_conflicts(root)),
        ("explicit-promote-accept-reject", lambda: scenario_explicit_promote_accept_reject(root)),
        ("self-leakage-rejection", scenario_self_leakage_rejection),
        ("no-new-command", lambda: scenario_no_new_command(root)),
    ]
    for name, fn in scenarios:
        try:
            fn()
            print(f"OK  {name}")
        except Exception as exc:
            print(f"FAIL {name}: {exc}")
            failures.append(name)
    if failures:
        print(json.dumps({"verdict": "fail", "failures": failures}, ensure_ascii=False))
        return 1
    print(json.dumps({"verdict": "pass", "scenarios": [n for n, _ in scenarios]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(run_module_main(main))
