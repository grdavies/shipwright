"""Unit tests for claims_audit_lib (PRD 064 R3/R4)."""
from __future__ import annotations

from pathlib import Path

import claims_audit_lib as lib


TASKS_SNIPPET = """
### 6. Adversarial completion-claims audit (Workstream A)

- [x] 6.1 Add a claims-audit agent (R3)
  - **File:** `core/skills/verification-gate/SKILL.md`
  - **Expected:** claims-audit integration documented; fail-closed overlay wired.
- [ ] 6.2 Reuse at deliver collect (R4)
  - **File:** `core/skills/deliver/SKILL.md`
  - **Expected:** collect-time audit documented.
"""


def test_parse_phase_subtasks_extracts_expected():
    rows = lib.parse_phase_subtasks(TASKS_SNIPPET, "6")
    assert len(rows) == 2
    assert rows[0]["ref"] == "6.1"
    assert rows[0]["checked"] is True
    assert "verification-gate" in rows[0]["files"][0]
    assert "claims-audit" in rows[0]["expected"]


def test_completed_claims_only_checked():
    claims = lib.completed_claims(TASKS_SNIPPET, "6")
    assert [c["ref"] for c in claims] == ["6.1"]


def test_merge_claim_results_fails_without_agent_for_expected(tmp_path: Path):
    claims = lib.completed_claims(TASKS_SNIPPET, "6")
    mechanical = [{
        "ref": "6.1",
        "verdict": "pass",
        "dimension": "mechanical",
        "reason": "ok",
    }]
    result = lib.merge_claim_results(mechanical, [], claims=claims)
    assert result["verdict"] == "fail"


def test_apply_verification_overlay_fail_closed():
    verdict = {"verdict": "verified", "reason": "ok", "evidence": {}}
    out = lib.apply_verification_overlay(verdict, {"verdict": "fail", "claims": []})
    assert out["verdict"] == "inconclusive"
    assert out["inconclusiveClass"] == "missing-required"


WIRED_TASKS_SNIPPET = """
### 1. Credential backend wiring (R16)

- [x] 1.1 Add foo backend (R16)
  - **File:** `scripts/credentials/backends/foo.py`
  - **Expected:** adds a new backend/adapter registration function
  - **Wired:** `scripts/credentials/resolver.py`
"""


def test_reachability_findings_gap_when_callsite_missing_reference(tmp_path: Path):
    resolver = tmp_path / "scripts/credentials/resolver.py"
    backend = tmp_path / "scripts/credentials/backends/foo.py"
    resolver.parent.mkdir(parents=True)
    backend.parent.mkdir(parents=True)
    resolver.write_text("# resolver without backend import\n", encoding="utf-8")
    backend.write_text("def register():\n    pass\n", encoding="utf-8")
    claims = lib.completed_claims(WIRED_TASKS_SNIPPET, "1")
    touched = {
        "scripts/credentials/resolver.py",
        "scripts/credentials/backends/foo.py",
    }
    findings = lib.reachability_findings(tmp_path, claims, touched=touched)
    assert any(f["verdict"] == "fail" and f["dimension"] == "reachability" for f in findings)


def test_reachability_findings_passes_with_genuine_reference(tmp_path: Path):
    resolver = tmp_path / "scripts/credentials/resolver.py"
    backend = tmp_path / "scripts/credentials/backends/foo.py"
    resolver.parent.mkdir(parents=True)
    backend.parent.mkdir(parents=True)
    resolver.write_text(
        "from scripts.credentials.backends import foo\n",
        encoding="utf-8",
    )
    backend.write_text("def register():\n    pass\n", encoding="utf-8")
    claims = lib.completed_claims(WIRED_TASKS_SNIPPET, "1")
    touched = {
        "scripts/credentials/resolver.py",
        "scripts/credentials/backends/foo.py",
    }
    findings = lib.reachability_findings(tmp_path, claims, touched=touched)
    assert findings and all(f["verdict"] == "pass" for f in findings)


def test_build_agent_brief_includes_reachability_verdict(tmp_path: Path):
    resolver = tmp_path / "scripts/credentials/resolver.py"
    backend = tmp_path / "scripts/credentials/backends/foo.py"
    resolver.parent.mkdir(parents=True)
    backend.parent.mkdir(parents=True)
    resolver.write_text("# no reference\n", encoding="utf-8")
    backend.write_text("pass\n", encoding="utf-8")
    claims = lib.completed_claims(WIRED_TASKS_SNIPPET, "1")
    touched = {
        "scripts/credentials/resolver.py",
        "scripts/credentials/backends/foo.py",
    }
    brief = lib.build_agent_brief(claims, diff_paths=touched, root=tmp_path)
    assert brief.get("reachabilityVerdict") == "fail"
    assert brief.get("reachabilityFindings")


def test_shared_cause_evidence_is_bound_and_fail_closed(tmp_path):
    import hashlib
    import copy
    for name in ("consumer.ts", "shared.ts", "regression.ts"):
        (tmp_path / name).write_text(name)
    claim = {"ref": "1.2", "files": ["consumer.ts"], "expected": "repair common inference"}
    digest = lambda name: hashlib.sha256((tmp_path / name).read_bytes()).hexdigest()
    proof = {
        "expectedSha256": hashlib.sha256(claim["expected"].encode()).hexdigest(),
        "unchangedFiles": {"consumer.ts": digest("consumer.ts")},
        "changedFiles": {"shared.ts": digest("shared.ts")},
        "verificationFiles": {"regression.ts": digest("regression.ts")},
        "reason": "Shared inference repair satisfies the unchanged consumer contract; regression verifies it.",
    }
    reviewer = {"ref": "1.2", "verdict": "pass", "sharedCauseEvidence": proof}
    touched = {"shared.ts", "regression.ts"}
    check = lambda row: lib.mechanical_claim_results([claim], touched, tmp_path, agent_claims=[row])[0]["verdict"]
    assert check(reviewer) == "pass"
    assert lib.mechanical_claim_results([claim], touched, tmp_path, agent_claims=[reviewer, reviewer])[0]["verdict"] == "fail"
    for invalid in (None, [], "reviewed", 7):
        assert check({"ref": "1.2", "verdict": "pass", "sharedCauseEvidence": invalid}) == "fail"
    assert check({"ref": "1.2", "verdict": "pass"}) == "fail"
    for field in proof:
        broken = copy.deepcopy(reviewer)
        del broken["sharedCauseEvidence"][field]
        assert check(broken) == "fail"
    for field in ("unchangedFiles", "changedFiles", "verificationFiles"):
        broken = copy.deepcopy(reviewer)
        key = next(iter(proof[field]))
        broken["sharedCauseEvidence"][field][key] = "0" * 64
        assert check(broken) == "fail"
    broken = copy.deepcopy(reviewer)
    broken["verdict"] = "fail"
    assert check(broken) == "fail"
    broken = copy.deepcopy(reviewer)
    broken["sharedCauseEvidence"]["changedFiles"] = {"consumer.ts": digest("consumer.ts")}
    assert check(broken) == "fail"
    (tmp_path / "consumer.ts").unlink()
    assert check(reviewer) == "fail"


def test_normalize_retains_shared_cause_evidence():
    proof = {"reason": "reviewed"}
    row = lib.normalize_agent_claims([{"ref": "1.2", "verdict": "pass", "sharedCauseEvidence": proof}])[0]
    assert row["sharedCauseEvidence"] == proof


def test_audit_collect_revalidates_original_shared_cause_proof(tmp_path, monkeypatch):
    import hashlib
    expected = "repair common inference"
    task = tmp_path / "tasks.md"
    task.write_text(f"### 1. Repair\n\n- [x] 1.2 Repair\n  - **File:** `consumer.ts`\n  - **Expected:** {expected}\n")
    files = {name: name.encode() for name in ("consumer.ts", "shared.ts", "regression.ts")}
    for name, data in files.items():
        (tmp_path / name).write_bytes(data)
    proof = {"expectedSha256": hashlib.sha256(expected.encode()).hexdigest(), "reason": "Independent shared cause and regression review"}
    for field, name in zip(("unchangedFiles", "changedFiles", "verificationFiles"), files):
        proof[field] = {name: hashlib.sha256(files[name]).hexdigest()}
    import subprocess
    def git(*args):
        return subprocess.check_output(["git", "-C", str(tmp_path), *args], text=True).strip()
    git("init", "-q")
    git("config", "user.email", "test@example.com")
    git("config", "user.name", "Test")
    git("add", "consumer.ts")
    git("commit", "-qm", "base")
    base = git("rev-parse", "HEAD")
    git("add", "shared.ts", "regression.ts")
    tree = git("write-tree")
    status = lib.audit_phase_claims(tmp_path, tasks_path=task, phase_id="1", diff_base=base, head=tree, agent_claims=[{"ref": "1.2", "verdict": "pass", "dimension": "agent", "sharedCauseEvidence": proof}])
    assert status["verdict"] == "pass"
    assert status["completionClaims"][0]["sharedCauseEvidence"] == proof
    collect = lambda: lib.collect_audit_from_status(tmp_path, status, tasks_path=task, phase_id="1", phase_branch=base)
    assert collect()["verdict"] == "pass"
    (tmp_path / "shared.ts").write_text("changed after review")
    assert collect()["verdict"] == "fail"
    # Rehashing dirty bytes cannot substitute for the audited staged tree.
    proof["changedFiles"]["shared.ts"] = hashlib.sha256((tmp_path / "shared.ts").read_bytes()).hexdigest()
    assert collect()["verdict"] == "fail"
    proof["changedFiles"]["shared.ts"] = hashlib.sha256(files["shared.ts"]).hexdigest()
    (tmp_path / "shared.ts").write_bytes(files["shared.ts"])
    task.write_text(task.read_text().replace(expected, "different expected contract"))
    assert collect()["verdict"] == "fail"
