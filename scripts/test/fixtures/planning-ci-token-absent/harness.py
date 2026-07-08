#!/usr/bin/env python3
"""Test-harness gating: skip-with-advisory when the store token is absent (PRD 057 R30).

Proves the R30 contract end to end, against the real fixture set already shipped
by earlier waves (phase 1 `planning-file-store-parity`, phase 1 `spec_union_056`)
plus the phase-5 `planning-doctor.py` classifier:

1. File-store parity checks ALWAYS run, deterministically, regardless of token
   presence — they never gate on the store token at all.
2. Issue-store-authoritative checks (the `planning-file-store-parity` issue-store
   side, and the `spec_union_056` PRD-056 union loader) degrade to
   skip-with-advisory (green, exit 0) when the store token env is unset — never a
   hard failure, never a hang, never a silent pass (an explicit
   ``store-token-absent`` reason is always present).
3. `planning-doctor.py` classifies a missing token as ``store-token-absent``
   (advisory) rather than ``probe-failed`` (fail-closed) — see
   ``scripts/planning-doctor.py::classify_issue_store_probe``.
4. The gating is deterministic: repeating the token-absent probe twice yields an
   identical verdict.

ZOMBIES: Zero (token env unset) · Interfaces (skip-with-advisory) · Exceptions
(``store-token-absent`` never ``probe-failed``) · State (deterministic green).
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import sys
import tempfile
from pathlib import Path
from types import ModuleType

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parents[3]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import planning_store

# Every env var a shipped issues provider might resolve as its token — stripped
# together so "token absent" is unambiguous regardless of which provider the
# real repo config happens to select.
_KNOWN_TOKEN_ENVS = (
    "ISSUES_GITHUB_TOKEN",
    "ISSUES_GITLAB_TOKEN",
    "ISSUES_JIRA_TOKEN",
    "GITHUB_TOKEN",
    "GITLAB_TOKEN",
)


@contextlib.contextmanager
def token_absent_env():
    """Temporarily strip every known issues-token env var, then restore it."""
    import os

    saved = {name: os.environ.pop(name, None) for name in _KNOWN_TOKEN_ENVS}
    try:
        yield
    finally:
        for name, value in saved.items():
            if value is not None:
                os.environ[name] = value


def _load_module(rel_path: str, name: str) -> ModuleType:
    path = ROOT / rel_path
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_SYNTHETIC_CFG = {
    "planning": {
        "store": {
            "backend": "issue-store",
            "issuesProvider": "github-issues",
            "projectKey": "ci-token-absent-fixture",
        }
    },
    # host.provider is set explicitly (rather than git-remote detection) so a
    # bare, remote-less temp repo still resolves a real host and the
    # issue-store-fallback-reason check below reaches the token check itself
    # instead of short-circuiting on host-provider-none.
    "host": {"provider": "github"},
}


def _synthetic_issue_store_root(tmp: str) -> Path:
    root = Path(tmp)
    cfg_path = root / ".cursor" / "workflow.config.json"
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(json.dumps(_SYNTHETIC_CFG, indent=2), encoding="utf-8")
    return root


def check_issue_store_gate_skips_on_token_absent() -> dict:
    """Synthetic issue-store config + token-absent env -> skip-advisory, never fail."""
    with tempfile.TemporaryDirectory() as tmp, token_absent_env():
        root = _synthetic_issue_store_root(tmp)
        cfg = dict(_SYNTHETIC_CFG)
        effective = planning_store.resolve_effective_backend(root, cfg)
        provider = planning_store.resolve_issues_provider(cfg).get("provider", "")
        token_env = planning_store.resolve_issues_token_env(cfg, provider)
        token_present = planning_store.token_present(token_env)
    ok = effective.get("effective") == "issue-store" and not token_present
    return {
        "name": "issue-store-gate-token-absent-detected",
        "ok": ok,
        "detail": f"effective={effective.get('effective')} tokenEnv={token_env} tokenPresent={token_present}",
    }


def check_file_store_parity_always_runs() -> dict:
    """`planning-file-store-parity` runs to green under the real repo env+config,
    with its token-absent-dependent issue-store side always either skipped with an
    explicit advisory reason or genuinely exercised — never silently omitted."""
    fsp = _load_module(
        "scripts/test/fixtures/planning-file-store-parity/harness.py",
        "_ci_token_absent_fsp",
    )
    with token_absent_env(), contextlib.redirect_stdout(io.StringIO()) as buf:
        exit_code = fsp.main()
    report = json.loads(buf.getvalue())
    file_store_checks = report.get("fileStoreChecks") or []
    issue_store = report.get("issueStore") or {}
    ok = (
        exit_code == 0
        and report.get("verdict") == "pass"
        and len(file_store_checks) > 0
        and all(c.get("ok") for c in file_store_checks)
        and (issue_store.get("skipped") is True or issue_store.get("ok") is True)
    )
    return {
        "name": "file-store-parity-always-runs",
        "ok": ok,
        "detail": f"exitCode={exit_code} verdict={report.get('verdict')} issueStore={issue_store}",
    }


def check_spec_union_056_skips_on_token_absent() -> dict:
    """`spec_union_056.load_056_union` degrades to skip-advisory under a
    synthetic issue-store config with the token stripped — the same contract
    the file-store-parity harness relies on, proven independently here."""
    spec_union_056 = _load_module("scripts/spec_union_056.py", "_ci_token_absent_su056")
    with tempfile.TemporaryDirectory() as tmp, token_absent_env():
        root = _synthetic_issue_store_root(tmp)
        cfg = dict(_SYNTHETIC_CFG)
        union = spec_union_056.load_056_union(root, cfg)
    ok = union.get("status") == "skipped" and union.get("reason") == "store-token-absent"
    return {
        "name": "spec-union-056-skips-on-token-absent",
        "ok": ok,
        "detail": f"union={union}",
    }


def check_doctor_classifies_token_absent_as_advisory() -> dict:
    """`planning-doctor.classify_issue_store_probe` maps a missing-token probe to
    the advisory `store-token-absent` finding — never a silent pass, never the
    fail-closed `probe-failed` finding."""
    doctor = _load_module("scripts/planning-doctor.py", "_ci_token_absent_doctor")
    missing_token_probe = {
        "verdict": "fail",
        "error": "missing-token",
        "provider": "github-issues",
        "tokenEnv": "ISSUES_GITHUB_TOKEN",
    }
    finding = doctor.classify_issue_store_probe(missing_token_probe)
    ok = (
        finding.get("check") == "store-token-absent"
        and finding.get("status") == "advisory"
        and "ISSUES_GITHUB_TOKEN" in (finding.get("remediation") or "")
    )
    return {
        "name": "doctor-classifies-token-absent-as-advisory",
        "ok": ok,
        "detail": f"finding={finding}",
    }


def check_doctor_distinguishes_probe_failed() -> dict:
    """A non-token probe failure (e.g. bad-credential auth failure) classifies as
    the fail-closed `probe-failed` finding, never the advisory `store-token-absent`
    finding — the two causes must never be conflated."""
    doctor = _load_module("scripts/planning-doctor.py", "_ci_token_absent_doctor2")
    auth_failed_probe = {
        "verdict": "fail",
        "error": "auth-failed",
        "provider": "github-issues",
        "httpStatus": 401,
    }
    finding = doctor.classify_issue_store_probe(auth_failed_probe)
    ok = finding.get("check") == "probe-failed" and finding.get("status") == "fail"
    return {
        "name": "doctor-distinguishes-probe-failed",
        "ok": ok,
        "detail": f"finding={finding}",
    }


def check_gate_deterministic() -> dict:
    """Repeating the token-absent gate check twice yields an identical verdict."""
    first = check_issue_store_gate_skips_on_token_absent()
    second = check_issue_store_gate_skips_on_token_absent()
    ok = first["ok"] and second["ok"] and first["detail"] == second["detail"]
    return {
        "name": "gate-deterministic-green",
        "ok": ok,
        "detail": f"first={first['detail']} second={second['detail']}",
    }


def main() -> int:
    checks = [
        check_issue_store_gate_skips_on_token_absent(),
        check_file_store_parity_always_runs(),
        check_spec_union_056_skips_on_token_absent(),
        check_doctor_classifies_token_absent_as_advisory(),
        check_doctor_distinguishes_probe_failed(),
        check_gate_deterministic(),
    ]
    failures = [c for c in checks if not c["ok"]]
    verdict = "pass" if not failures else "fail"
    report = {
        "fixture": "planning-ci-token-absent",
        "rid": "R30",
        "verdict": verdict,
        "checks": checks,
        "failures": failures,
    }
    print(json.dumps(report, ensure_ascii=False))
    return 0 if verdict == "pass" else 20


if __name__ == "__main__":
    raise SystemExit(main())
