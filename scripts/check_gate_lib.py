"""CI readiness gate computation — shared library for check-gate (PRD 042 phase 3)."""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TypedDict

from _sw import jsonio, logging_setup, proc

SCRIPT_DIR = Path(__file__).resolve().parent

PENDING_STATES = frozenset(
    {"PENDING", "QUEUED", "IN_PROGRESS", "REQUESTED", "WAITING", "EXPECTED"}
)

VERDICT_EXIT = {"green": 0, "yellow": 10, "red": 20, "blocked": 30}


GATE_MANIFEST_CACHE_REL = Path(".cursor/sw-gate-cache/pr-test-plan.manifest.json")


def manifest_sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def persist_gate_manifest_snapshot(root: Path, manifest: Any) -> dict[str, str]:
    """Persist manifest under repo-root cache (R8 — outside ephemeral worktrees)."""
    cache_dir = root / ".cursor" / "sw-gate-cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / "pr-test-plan.manifest.json"
    canonical = json.dumps(manifest, sort_keys=True, separators=(",", ":"))
    written = (canonical + "\n").encode("utf-8")
    cache_path.write_bytes(written)
    rel = str(cache_path.relative_to(root))
    return {"manifestPath": rel, "manifestSha256": manifest_sha256(written)}


def slim_pr_test_plan_gate(
    root: Path,
    pr_test_plan: Any,
    required_jobs: list[str],
    advisory_jobs: list[str],
) -> dict[str, Any] | None:
    if pr_test_plan is None:
        return None
    refs = persist_gate_manifest_snapshot(root, pr_test_plan)
    return {
        **refs,
        "requiredJobs": required_jobs,
        "advisoryJobs": advisory_jobs,
    }


def validate_pr_test_plan_gate(root: Path, pr_test_plan_gate: Any) -> str | None:
    """Fail-closed validation for slim or embedded prTestPlan refs (R8)."""
    if pr_test_plan_gate is None:
        return None
    if not isinstance(pr_test_plan_gate, dict):
        return "invalid-prTestPlan"
    if "manifest" in pr_test_plan_gate:
        return None
    path_rel = pr_test_plan_gate.get("manifestPath")
    expected_sha = pr_test_plan_gate.get("manifestSha256")
    if not path_rel or not expected_sha:
        return "slim-manifest-incomplete"
    path = root / str(path_rel)
    if not path.is_file():
        return "manifest-missing"
    content = path.read_bytes()
    if manifest_sha256(content) != str(expected_sha):
        return "manifest-hash-mismatch"
    try:
        json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return "manifest-invalid-json"
    return None


RESILIENCE_VERIFY_SCOPE = "resilience"
RESILIENCE_RUNNER_REL = Path("scripts/test/_runner.py")


def validate_effective_config_drift(root: Path) -> str | None:
    """Fail-closed when generated effective-config/doc projection drifts (PRD 279 R15)."""
    gen = root / "scripts" / "effective_config_gen.py"
    config_path = root / "core" / "sw-reference" / "generated" / "effective-config.json"
    if not gen.is_file() or not config_path.is_file():
        return None
    try:
        from effective_config_gen import check_drift
    except ImportError:
        return None
    errors = check_drift(root)
    if not errors:
        return None
    return errors[0]


def validate_documented_defaults_drift(root: Path) -> str | None:
    """Fail-closed when documented operator defaults drift from effective config (PRD 330 R2)."""
    checker = root / "scripts" / "documented_defaults_check.py"
    if not checker.is_file():
        return None
    try:
        from documented_defaults_check import validate_documented_defaults
    except ImportError:
        return None
    return validate_documented_defaults(root)


def validate_resilience_verify_scope(root: Path, cfg: dict[str, Any]) -> str | None:
    """Fail-closed readiness check for resilience verify scope wiring (PRD 323 R22)."""
    runner = root / RESILIENCE_RUNNER_REL
    if not runner.is_file():
        return None
    text = runner.read_text(encoding="utf-8", errors="replace")
    if RESILIENCE_VERIFY_SCOPE not in text:
        return "runner-missing-resilience-scope"
    if "run_resilience_verify" not in text:
        return "runner-missing-resilience-handler"
    resilience_dir = root / "scripts/unit_tests/resilience"
    if not resilience_dir.is_dir():
        return "resilience-suite-missing"
    configured = cfg_value(cfg, "verify", "resilienceTest")
    if configured is not None:
        cmd = str(configured)
        if f"--scope {RESILIENCE_VERIFY_SCOPE}" not in cmd:
            return "verify.resilienceTest-mismatch"
    return None


def resolve_plugin_root(script_dir: Path | None = None) -> Path:
    """Resolve plugin content root (mirrors sw-resolve-plugin-root.py)."""
    script_dir = script_dir or SCRIPT_DIR
    parent = script_dir.parent
    if (parent / "providers").is_dir() or (parent / "commands").is_dir():
        return parent
    if (parent / "core" / "providers").is_dir():
        return parent / "core"
    return parent


def git_root(start: Path | None = None) -> Path:
    start = start or Path.cwd()
    completed = proc.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=str(start),
    )
    if completed.returncode == 0 and completed.stdout.strip():
        return Path(completed.stdout.strip())
    return start


def load_workflow_config(root: Path) -> dict[str, Any]:
    from shipwright_paths import load_workflow_config as _load_workflow_config

    return _load_workflow_config(root)
def cfg_bool(cfg: dict[str, Any], key: str, default: bool) -> bool:
    checks = cfg.get("checks")
    if not isinstance(checks, dict):
        return default
    value = checks
    for part in key.split("."):
        if not isinstance(value, dict) or part not in value:
            return default
        value = value[part]
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in ("true", "1", "yes")
    return default


def cfg_value(cfg: dict[str, Any], *path: str, default: Any = None) -> Any:
    value: Any = cfg
    for part in path:
        if not isinstance(value, dict) or part not in value:
            return default
        value = value[part]
    return value


def host_verb(root: Path, *args: str) -> dict[str, Any]:
    host_py = SCRIPT_DIR / "host.py"
    completed = proc.run(
        [sys.executable, str(host_py), "--root", str(root), *args],
        cwd=str(root),
        child_env=proc.host_transport_child_env(),
    )
    try:
        return json.loads(completed.stdout.strip() or "{}")
    except json.JSONDecodeError:
        return {"verdict": "fail", "reason": completed.stderr.strip() or "invalid host output"}


def host_data(root: Path, *args: str) -> Any:
    payload = host_verb(root, *args)
    if payload.get("verdict") == "ok":
        return payload.get("data")
    return None


class ChecksEvidenceEnvelope(TypedDict, total=False):
    evidenceValidity: str
    transportClass: str
    reasonCode: str
    checks: list[dict[str, Any]]


EVIDENCE_VALID = "valid"
EVIDENCE_INVALID = "invalid"

PRIMARY_CHECKS_EVIDENCE_SOURCE = "checks-verb"

# PRD 079 R17 — known secondary CI-status sources; must not authorize merge when primary is denied.
SECONDARY_CHECKS_EVIDENCE_SOURCES: frozenset[str] = frozenset(
    {
        "github-actions-runs",
        "github-statusCheckRollup",
        "gitlab-commit-statuses",
        "gitlab-pipelines",
        "bitbucket-commit-status",
    }
)

REASON_CHECKS_OK = "checks-ok"
REASON_HOST_AUTH_REQUIRED = "host-auth-required"
REASON_CHECKS_NOT_FOUND = "checks-not-found"
REASON_CHECKS_RATE_LIMITED = "checks-rate-limited"
REASON_CHECKS_UNAVAILABLE = "checks-unavailable"
REASON_EMPTY_CHECK_SET = "empty-check-set"
REASON_CHECKS_MALFORMED = "checks-malformed"

_REASON_CODE_BY_TRANSPORT: dict[str, str] = {
    "auth-denied": REASON_HOST_AUTH_REQUIRED,
    "not-found": REASON_CHECKS_NOT_FOUND,
    "rate-limited": REASON_CHECKS_RATE_LIMITED,
    "inconclusive": REASON_CHECKS_UNAVAILABLE,
}

_RETRYABLE_REASON_CODES = frozenset({REASON_CHECKS_RATE_LIMITED, REASON_CHECKS_UNAVAILABLE})

_DEFAULT_CHECKS_REMEDIATION: dict[str, str] = {
    "github": (
        "Host token cannot read CI check status. Grant a fine-grained PAT with Checks "
        "repository permission (read access)."
    ),
    "gitlab": (
        "Host token cannot read commit statuses or pipelines. Grant an access token with "
        "API read access."
    ),
    "bitbucket": (
        "Host token cannot read commit build statuses. Grant an access token with "
        "repository read access."
    ),
    "default": (
        "Host token cannot read CI/check status. Configure a host token with check-status "
        "read capability."
    ),
}


def reason_code_for_transport_class(transport_class: str) -> str:
    return _REASON_CODE_BY_TRANSPORT.get(transport_class, REASON_CHECKS_UNAVAILABLE)


def reason_code_is_retryable(reason_code: str) -> bool:
    return reason_code in _RETRYABLE_REASON_CODES


CHECKS_READ_SCOPE_STRING = "checks:read"

_PROHIBITIVE_CHECKS_READ_MARKERS = (
    "must not",
    "invalid scope",
    "non-existent",
    "forbidden",
    "prohibited",
)


def remediation_surface_violates_checks_read(text: str) -> bool:
    """True when remediation copy improperly presents ``checks:read`` as valid scope (R13/TR8)."""
    if CHECKS_READ_SCOPE_STRING not in text:
        return False
    lowered = text.lower()
    return not any(marker in lowered for marker in _PROHIBITIVE_CHECKS_READ_MARKERS)


def gate_reason_code(gate: dict[str, Any]) -> str | None:
    code = gate.get("reasonCode")
    return str(code) if code else None


def is_checks_gate_non_retryable_halt(gate: dict[str, Any]) -> bool:
    """Stabilize/deliver treat these gate outcomes as non-retryable halts (R10/TR6)."""
    if gate.get("verdict") != "blocked":
        return False
    code = gate_reason_code(gate)
    if code:
        return not reason_code_is_retryable(code)
    return gate.get("retryable") is False


def should_halt_ci_watch_without_poll(gate: dict[str, Any]) -> bool:
    """Watch-ci must halt immediately — no poll loop or stabilize attempt (R10/R22)."""
    return gate.get("verdict") == "blocked" and gate_reason_code(gate) == REASON_HOST_AUTH_REQUIRED


def checks_gate_halt_remediation(
    gate: dict[str, Any],
    *,
    plugin_root: Path,
    provider: str,
) -> str:
    """Canonical remediation for a checks gate halt — fragment only, never host bodies (R9/R14)."""
    code = gate_reason_code(gate)
    if code in (REASON_HOST_AUTH_REQUIRED, REASON_CHECKS_NOT_FOUND):
        return load_checks_remediation(plugin_root, provider)
    reason = str(gate.get("reason") or "")
    if reason:
        return reason
    return human_reason_for_invalid_checks_evidence(
        code or REASON_CHECKS_UNAVAILABLE,
        plugin_root=plugin_root,
        provider=provider,
    )


def load_checks_remediation(plugin_root: Path, provider: str) -> str:
    """Load provider-section remediation from the canonical fragment (PRD 079 R9, R13–R14)."""
    path = plugin_root / "providers" / "host" / "remediation-checks.md"
    provider_key = str(provider or "default").strip().lower() or "default"
    if path.is_file():
        section: str | None = None
        current: str | None = None
        lines: list[str] = []
        for raw in path.read_text(encoding="utf-8").splitlines():
            if raw.startswith("## "):
                if current == provider_key and lines:
                    section = " ".join(part.strip() for part in lines if part.strip())
                    break
                current = raw[3:].strip().lower()
                lines = []
                continue
            if current == provider_key:
                lines.append(raw)
        if current == provider_key and lines:
            section = " ".join(part.strip() for part in lines if part.strip())
        if section:
            return section
    return _DEFAULT_CHECKS_REMEDIATION.get(provider_key, _DEFAULT_CHECKS_REMEDIATION["default"])


def human_reason_for_invalid_checks_evidence(
    reason_code: str,
    *,
    plugin_root: Path,
    provider: str,
) -> str:
    """Agent-facing remediation copy from the local fragment only — never host bodies (R9)."""
    if reason_code in (REASON_HOST_AUTH_REQUIRED, REASON_CHECKS_NOT_FOUND):
        return load_checks_remediation(plugin_root, provider)
    if reason_code == REASON_CHECKS_RATE_LIMITED:
        return "checks rate limited; retry after host rate-limit window"
    if reason_code == REASON_CHECKS_MALFORMED:
        return "checks evidence malformed; cannot evaluate check count"
    return "checks evidence unavailable; retry or verify host connectivity"


def checks_evidence_from_host_verb(payload: dict[str, Any]) -> ChecksEvidenceEnvelope:
    """Build a typed checks evidence envelope from a host verb payload (PRD 079 R6, R20, R21)."""
    if payload.get("verdict") == "ok":
        data = payload.get("data")
        if not isinstance(data, list):
            return {
                "evidenceValidity": EVIDENCE_INVALID,
                "transportClass": "ok",
                "reasonCode": REASON_CHECKS_MALFORMED,
                "checks": [],
            }
        return {
            "evidenceValidity": EVIDENCE_VALID,
            "transportClass": "ok",
            "reasonCode": REASON_CHECKS_OK,
            "checks": data,
        }
    transport_class = str(payload.get("transportClass") or "inconclusive")
    return {
        "evidenceValidity": EVIDENCE_INVALID,
        "transportClass": transport_class,
        "reasonCode": reason_code_for_transport_class(transport_class),
        "checks": [],
    }


def host_checks_evidence(root: Path, *args: str) -> ChecksEvidenceEnvelope:
    return checks_evidence_from_host_verb(host_verb(root, *args))


def may_consult_secondary_checks_evidence(primary: ChecksEvidenceEnvelope) -> bool:
    """Return whether secondary CI-status sources may be consulted (PRD 079 R17)."""
    if primary.get("evidenceValidity") != EVIDENCE_VALID:
        return False
    # Policy pinned: no secondary fallback until a separate decision record exists.
    return False


def checks_evidence_from_secondary_sources(
    root: Path,
    *,
    provider: str,
    head_sha: str,
    pr: str | None = None,
) -> ChecksEvidenceEnvelope | None:
    """Optional secondary checks evidence — disabled under R17 until policy record."""
    _ = (root, provider, head_sha, pr)
    return None


def resolve_checks_evidence_for_gate(
    root: Path,
    *,
    pr: str | None = None,
    sha: str | None = None,
) -> ChecksEvidenceEnvelope:
    """Resolve primary checks evidence; never fall back when primary is invalid (R17)."""
    args: list[str] = []
    if pr:
        args.extend(["--number", str(pr)])
    if sha:
        args.extend(["--sha", str(sha)])
    primary = host_checks_evidence(root, "checks", *args)
    if not may_consult_secondary_checks_evidence(primary):
        return primary
    secondary = checks_evidence_from_secondary_sources(
        root,
        provider="",
        head_sha=sha or "",
        pr=pr,
    )
    if secondary is not None and secondary.get("evidenceValidity") == EVIDENCE_VALID:
        return secondary
    return primary


def blocked_reason_code_for_verdict(
    verdict: str,
    *,
    check_count: int,
    blocking: list[str],
    actionable: int,
) -> str | None:
    if verdict != "blocked":
        return None
    if actionable > 0:
        return None
    if blocking:
        return None
    if check_count == 0:
        return REASON_EMPTY_CHECK_SET
    return None


def gate_blocked_for_invalid_checks_evidence(
    envelope: ChecksEvidenceEnvelope,
    *,
    plugin_root: Path | None = None,
    provider: str = "",
    head_sha: str = "",
    pr: int | None = None,
    source: str | None = None,
) -> tuple[int, dict[str, Any]]:
    """Short-circuit gate when checks evidence is invalid — never erase via ``or []`` (R7, R20)."""
    reason_code = str(envelope.get("reasonCode") or REASON_CHECKS_UNAVAILABLE)
    transport_class = str(envelope.get("transportClass") or "inconclusive")
    retryable = reason_code_is_retryable(reason_code)
    root = plugin_root or resolve_plugin_root(SCRIPT_DIR)
    reason = human_reason_for_invalid_checks_evidence(
        reason_code,
        plugin_root=root,
        provider=provider,
    )
    payload: dict[str, Any] = {
        "verdict": "blocked",
        "reason": reason,
        "reasonCode": reason_code,
        "evidenceValidity": EVIDENCE_INVALID,
        "transportClass": transport_class,
        "retryable": retryable,
    }
    if head_sha:
        payload["head"] = head_sha
    if pr is not None:
        payload["pr"] = pr
    if source is not None:
        payload["source"] = source
    jsonio.emit(payload)
    return (37 if retryable else 30), payload


def load_pr_test_plan(root: Path, cfg: dict[str, Any]) -> tuple[Any, list[str], list[str]]:
    manifest_path = root / "core/sw-reference/pr-test-plan.manifest.json"
    manifest_cfg = cfg_value(cfg, "ci", "prTestPlanManifest") or cfg_value(
        cfg, "verify", "prTestPlanManifest"
    )
    if manifest_cfg:
        candidate = root / str(manifest_cfg)
        if candidate.is_file():
            manifest_path = candidate
    pr_test_plan: Any = None
    advisory_jobs: list[str] = []
    required_jobs: list[str] = []
    if manifest_path.is_file():
        try:
            pr_test_plan = json.loads(manifest_path.read_text(encoding="utf-8"))
            fixtures = pr_test_plan.get("fixtures") if isinstance(pr_test_plan, dict) else []
            if isinstance(fixtures, list):
                for item in fixtures:
                    if not isinstance(item, dict):
                        continue
                    name = item.get("ciJobName")
                    if not name:
                        continue
                    if item.get("classification") == "advisory":
                        advisory_jobs.append(str(name))
                    elif item.get("classification") == "required":
                        required_jobs.append(str(name))
        except json.JSONDecodeError:
            pr_test_plan = None
    return pr_test_plan, advisory_jobs, required_jobs




DEFAULT_STALE_IN_PROGRESS_TTL_SECONDS = 600


def _parse_iso8601(value: str) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def stale_in_progress_ttl_seconds(cfg: dict[str, Any]) -> int:
    override = os.environ.get("SW_STALE_IN_PROGRESS_TTL_SECONDS", "").strip()
    if override:
        try:
            return max(0, int(override))
        except ValueError:
            pass
    raw = cfg_value(cfg, "checks", "staleInProgressTtlSeconds", default=DEFAULT_STALE_IN_PROGRESS_TTL_SECONDS)
    try:
        return max(0, int(raw))
    except (TypeError, ValueError):
        return DEFAULT_STALE_IN_PROGRESS_TTL_SECONDS


def reconcile_stale_in_progress_checks(
    checks: list[dict[str, Any]],
    *,
    ttl_seconds: int,
    now: datetime | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Settle IN_PROGRESS checks whose conclusion is already SUCCESS (R11).

    A definitive ``conclusion=SUCCESS`` is authoritative immediately — do not wait for
    ``ttl_seconds``. The ``ttl_seconds`` / ``now`` parameters are retained for call-site
    compatibility and for future workflow-level signals that lack a per-check conclusion.
    """
    _ = (ttl_seconds, now)
    settled: list[str] = []
    out: list[dict[str, Any]] = []
    for item in checks:
        if not isinstance(item, dict):
            continue
        row = dict(item)
        state = str(row.get("state") or "").upper()
        conclusion = str(row.get("conclusion") or "").upper()
        if state in PENDING_STATES and conclusion == "SUCCESS":
            row["state"] = "SUCCESS"
            row["staleInProgressSettled"] = True
            settled.append(str(row.get("name") or "check"))
        out.append(row)
    return out, settled

def classify_checks(
    checks: list[dict[str, Any]],
    *,
    neutral_pass: bool,
    allowlist: list[str],
) -> list[dict[str, Any]]:
    classified: list[dict[str, Any]] = []
    for item in checks:
        if not isinstance(item, dict):
            continue
        state = str(item.get("state", ""))
        name = str(item.get("name", ""))
        if state in ("SUCCESS", "SKIPPED"):
            klass = "pass"
        elif state == "NEUTRAL":
            klass = "pass" if neutral_pass or name in allowlist else "block"
        elif state in PENDING_STATES:
            klass = "pending"
        else:
            klass = "fail"
        classified.append({"name": name, "state": state, "class": klass})
    return classified


def split_failing(
    failing: list[str],
    advisory_jobs: list[str],
) -> tuple[list[str], list[str]]:
    advisory_set = set(advisory_jobs)
    required = [name for name in failing if name not in advisory_set]
    advisory = [name for name in failing if name in advisory_set]
    return required, advisory


def compute_verdict(
    *,
    required_failing: list[str],
    blocking: list[str],
    pending: list[str],
    cr_landed: bool,
    check_count: int,
    actionable: int,
) -> str:
    if required_failing:
        return "red"
    if blocking:
        return "blocked"
    if pending:
        return "yellow"
    if not cr_landed:
        return "yellow"
    if check_count == 0:
        return "blocked"
    if actionable > 0:
        return "blocked"
    return "green"


def build_reason(
    verdict: str,
    *,
    pending: list[str],
    required_failing: list[str],
    advisory_failing: list[str],
    actionable: int,
    cr_landed: bool,
    cr_state: str,
    head_sha: str,
    review_provider: str,
    check_count: int = 0,
    blocking: list[str] | None = None,
) -> str:
    blocking = blocking or []
    if verdict == "yellow":
        if not cr_landed:
            short = head_sha[:8] if head_sha else ""
            return (
                f"review not yet landed for head {short} "
                f"(state={cr_state} provider={review_provider})"
            )
        return f"checks pending: {','.join(pending)}"
    if verdict == "red":
        return f"failing checks: {','.join(required_failing)}"
    if verdict == "blocked":
        if actionable > 0:
            return f"{actionable} unresolved actionable review thread(s)"
        if blocking:
            return f"blocking/neutral checks: {','.join(blocking)}"
        if check_count == 0:
            return "empty check set"
        return "blocking check outcome"
    if advisory_failing:
        return (
            f"required checks pass; advisory failing (non-blocking): "
            f"{','.join(advisory_failing)}"
        )
    if cr_state == "off":
        return "all checks pass; review gating off; 0 actionable threads"
    if cr_state == "unconfigured":
        return (
            "all checks pass; review off by default — never configured; "
            "0 actionable threads"
        )
    if cr_state == "skipped":
        short = head_sha[:8] if head_sha else ""
        return f"all checks pass; review skipped head {short}; 0 actionable threads"
    short = head_sha[:8] if head_sha else ""
    return f"all checks pass; review landed for head {short}; 0 actionable threads"


def attach_quality_context(root: Path, cfg: dict, payload: dict) -> tuple[int, dict]:
    from quality_config_freeze import load_pin_from_deliver_state, validate_pin
    pin = load_pin_from_deliver_state(root)
    freeze = validate_pin(pin, cfg)
    if freeze.get("verdict") == "fail":
        blocked = {
            "verdict": "blocked",
            "reason": freeze.get("reason", "quality-config-mutation"),
            "qualityConfigFreeze": freeze,
        }
        jsonio.emit(blocked)
        return 30, blocked
    import subprocess
    proc = subprocess.run([sys.executable, str(SCRIPT_DIR / "quality_provider.py")], capture_output=True, text=True, cwd=str(root))
    signal = {}
    try:
        signal = json.loads(proc.stdout.strip() or "{}")
    except json.JSONDecodeError:
        signal = {"verdict": "none", "provider": "unknown", "skipped": True}
    payload = dict(payload)
    payload["qualityAdvisory"] = signal
    return 0, payload



TRIAGE_TIER_RANK = {"quick": 0, "standard": 1, "full": 2}
QUALITY_BLOCKING_CHECK = "quality-harness:poor"


def resolve_change_triage_tier(root: Path) -> str | None:
    env = os.environ.get("SW_TRIAGE_TIER") or os.environ.get("SW_CHANGE_TIER")
    if env:
        tier = str(env).strip().lower()
        if tier in TRIAGE_TIER_RANK:
            return tier
    run_dir = os.environ.get("SW_RUN_DIR")
    candidates: list[Path] = []
    if run_dir:
        candidates.append(Path(run_dir) / "status.json")
    phase = os.environ.get("SW_PHASE_SLUG")
    if phase:
        candidates.append(root / ".cursor" / "sw-deliver-runs" / phase / "status.json")
    for cand in candidates:
        if not cand.is_file():
            continue
        try:
            data = json.loads(cand.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            for key in ("triageTier", "changeTier", "tier"):
                val = data.get(key)
                if isinstance(val, str) and val.lower() in TRIAGE_TIER_RANK:
                    return val.lower()
    return None


def apply_quality_blocking_promotion(
    cfg: dict[str, Any],
    payload: dict[str, Any],
    *,
    verdict: str,
    required_failing: list[str],
    reason: str,
) -> tuple[str, list[str], str, dict[str, Any]]:
    """Promote poor quality signal to blocking when triage tier >= quality.blockingTier."""
    payload = dict(payload)
    quality_cfg = cfg.get("quality") if isinstance(cfg.get("quality"), dict) else {}
    blocking_tier = quality_cfg.get("blockingTier")
    if not blocking_tier:
        return verdict, required_failing, reason, payload
    floor = str(blocking_tier).strip().lower()
    if floor not in TRIAGE_TIER_RANK:
        return verdict, required_failing, reason, payload
    change_tier = resolve_change_triage_tier(Path.cwd())
    if change_tier is None:
        return verdict, required_failing, reason, payload
    if TRIAGE_TIER_RANK[change_tier] < TRIAGE_TIER_RANK[floor]:
        return verdict, required_failing, reason, payload
    signal = payload.get("qualityAdvisory")
    if not isinstance(signal, dict) or str(signal.get("verdict")) != "poor":
        return verdict, required_failing, reason, payload
    req = list(required_failing)
    if QUALITY_BLOCKING_CHECK not in req:
        req.append(QUALITY_BLOCKING_CHECK)
    new_verdict = "red" if verdict in ("green", "yellow") else verdict
    if new_verdict == "red" and verdict != "red":
        reason = f"quality harness poor at triage tier {change_tier} (blockingTier={floor})"
    payload["qualityBlockingPromotion"] = {
        "applied": True,
        "changeTier": change_tier,
        "blockingTier": floor,
        "check": QUALITY_BLOCKING_CHECK,
    }
    return new_verdict, req, reason, payload


def run_pin_validity_gate(root: Path, payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    """Run the workflow pin-validity checker and annotate the payload (PRD 083 R10).

    Confirmed-invalid pins → returns non-zero exit with a blocked payload.
    Transient lookup errors → exit 0, warning annotated in payload (fail-open).
    """
    try:
        import workflow_pin_validity_check_lib as pv_lib
        pin_exit, pin_result = pv_lib.run_check(root, skip_api=True)
    except Exception:
        # If the library itself cannot be imported or crashes, fail open.
        return 0, payload

    payload = dict(payload)
    payload["pinValidityCheck"] = pin_result

    if pin_result.get("verdict") == "fail":
        blocked: dict[str, Any] = {
            "verdict": "blocked",
            "reason": "workflow-pin-validity: invalid action pins detected",
            "pinValidityCheck": pin_result,
        }
        jsonio.emit(blocked)
        return 30, blocked

    return 0, payload


def run_deferred_placeholder_lint_gate(root: Path, payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    """Run deferred-placeholder lint — untracked deferral markers fail closed (PRD 085 R17)."""
    completed = proc.run(
        [sys.executable, str(SCRIPT_DIR / "deferred-placeholder-lint.py"), "--check"],
        cwd=str(root),
    )
    lint_result: dict[str, Any] = {}
    try:
        lint_result = json.loads(completed.stdout.strip() or "{}")
    except json.JSONDecodeError:
        lint_result = {"verdict": "fail", "error": "deferred-placeholder-lint-invalid-output"}
    payload = dict(payload)
    payload["deferredPlaceholderLint"] = lint_result
    if lint_result.get("verdict") != "pass":
        blocked: dict[str, Any] = {
            "verdict": "blocked",
            "reason": "deferred-placeholder-lint: untracked deferral marker(s)",
            "deferredPlaceholderLint": lint_result,
        }
        jsonio.emit(blocked)
        return 30, blocked
    return 0, payload


def run_architecture_assessment_gate(root: Path, cfg: dict[str, Any], payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    """Evaluate opt-in architecture doctrine assessment (PRD 326 R15)."""
    mode = str(cfg_value(cfg, "architecture", "assessment", "mode", default="off") or "off").strip().lower()
    if mode == "off":
        return 0, payload
    completed = proc.run(
        [sys.executable, str(SCRIPT_DIR / "architecture_assessment.py"), "--root", str(root), "evaluate"],
        cwd=str(root),
    )
    result: dict[str, Any] = {}
    try:
        result = json.loads(completed.stdout.strip() or "{}")
    except json.JSONDecodeError:
        result = {"verdict": "fail", "error": "architecture-assessment-invalid-output"}
    payload = dict(payload)
    payload["architectureAssessment"] = result
    if mode == "advisory":
        return 0, payload
    if completed.returncode == 20 or result.get("verdict") == "fail":
        blocked: dict[str, Any] = {
            "verdict": "blocked",
            "reason": "architecture-assessment:blocking-fail",
            "architectureAssessment": result,
        }
        jsonio.emit(blocked)
        return 30, blocked
    return 0, payload


def finalize_gate_payload(
    root: Path,
    cfg: dict[str, Any],
    payload: dict[str, Any],
    *,
    verdict: str,
    required_failing: list[str],
    reason: str,
) -> tuple[int, dict[str, Any]]:
    ec, payload = attach_quality_context(root, cfg, payload)
    if ec != 0:
        return ec, payload
    ec, payload = run_pin_validity_gate(root, payload)
    if ec != 0:
        return ec, payload
    ec, payload = run_deferred_placeholder_lint_gate(root, payload)
    if ec != 0:
        return ec, payload
    ec, payload = run_architecture_assessment_gate(root, cfg, payload)
    if ec != 0:
        return ec, payload
    verdict, required_failing, reason, payload = apply_quality_blocking_promotion(
        cfg,
        payload,
        verdict=verdict,
        required_failing=required_failing,
        reason=reason,
    )
    payload["verdict"] = verdict
    payload["reason"] = reason
    payload["requiredFailingChecks"] = required_failing
    if verdict in payload.get("failingChecks", []) or QUALITY_BLOCKING_CHECK in required_failing:
        failing = list(payload.get("failingChecks") or [])
        if QUALITY_BLOCKING_CHECK not in failing and QUALITY_BLOCKING_CHECK in required_failing:
            failing.append(QUALITY_BLOCKING_CHECK)
            payload["failingChecks"] = failing
    if verdict == "red":
        try:
            import failure_signature_record_lib as fsr
            import failure_signature_escalate_lib as fse

            fsr.maybe_record_gate(root, payload, reason=reason)
            fse.maybe_escalate_threshold(root, cfg, failure_text=reason)
        except Exception:
            pass
    jsonio.emit(payload)
    return VERDICT_EXIT.get(verdict, 1), payload


def build_gate_payload(
    root: Path,
    *,
    verdict: str,
    reason: str,
    head_sha: str,
    review_provider: str,
    cr_reviewed_head: str,
    cr_status: str,
    cr_state: str,
    cr_landed: bool,
    cr_marker: bool,
    cr_skipped: bool,
    mins_since: int,
    unresolved: int,
    actionable: int,
    failing: list[str],
    required_failing: list[str],
    advisory_failing: list[str],
    pr_test_plan: Any,
    required_jobs: list[str],
    advisory_jobs: list[str],
    pending: list[str],
    blocking: list[str],
    check_count: int,
    deprecations: list[str],
    quality_advisory: Any | None = None,
    pr: int | None = None,
    branch: str | None = None,
    source: str | None = None,
    reason_code: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "verdict": verdict,
        "reason": reason,
        "head": head_sha,
        "reviewProvider": review_provider,
        "deprecations": deprecations,
        "coderabbitReviewedHead": cr_reviewed_head or None,
        "coderabbitReviewedCurrentHead": bool(
            cr_reviewed_head and cr_reviewed_head == head_sha
        ),
        "coderabbitStatus": cr_status,
        "coderabbitState": cr_state,
        "coderabbitLanded": cr_landed,
        "coderabbitSkipped": cr_skipped,
        "coderabbitInProgressMarker": cr_marker,
        "minutesSinceHeadPush": mins_since,
        "unresolvedThreads": unresolved,
        "unresolvedActionable": actionable,
        "failingChecks": failing,
        "requiredFailingChecks": required_failing,
        "advisoryFailingChecks": advisory_failing,
        "pendingChecks": pending,
        "blockingNeutral": blocking,
        "checkCount": check_count,
    }
    if reason_code:
        payload["reasonCode"] = reason_code
    if quality_advisory is not None:
        payload["qualityAdvisory"] = quality_advisory
    if pr is not None:
        payload["pr"] = pr
    if branch is not None:
        payload["branch"] = branch
    if source is not None:
        payload["source"] = source
    if pr_test_plan is not None:
        payload["prTestPlan"] = slim_pr_test_plan_gate(
            root,
            pr_test_plan,
            required_jobs,
            advisory_jobs,
        )
    else:
        payload["prTestPlan"] = None
    return payload


def resolve_review_state(
    root: Path,
    plugin_root: Path,
    cfg: dict[str, Any],
    *,
    pr: str,
    head_sha: str,
    owner: str,
    repo: str,
    owner_repo: str,
    checks_file: Path,
    issue_comments_file: Path,
    grace_min: int,
) -> tuple[dict[str, Any], list[str]]:
    from review_synthesize import resolve_review_providers, synthesize_gate_adapters

    review = cfg.get("review") if isinstance(cfg.get("review"), dict) else {}
    review_provider_set = "provider" in review or "providers" in review
    provider_ids = resolve_review_providers(review)
    review_enabled = True
    if "enabled" in review:
        review_enabled = bool(review.get("enabled"))

    deprecations: list[str] = []
    if review_enabled is False:
        deprecations.append('review.enabled is deprecated; use review.provider:"none"')
        logging_setup.warning(
            "review.enabled is deprecated; use review.provider:\"none\""
        )

    review_provider = ",".join(provider_ids) if provider_ids else str(review.get("provider") or "none")

    for pid in provider_ids:
        if not re.fullmatch(r"[a-z0-9-]*", pid):
            return (
                {
                    "error": True,
                    "payload": {
                        "verdict": "blocked",
                        "reason": f"invalid review provider: {pid}",
                    },
                    "exit_code": 30,
                },
                deprecations,
            )

    cr_state = "off"
    cr_landed = True
    cr_reviewed_head = ""
    cr_status = "off"
    cr_marker = False
    cr_skipped = False
    mins_since = 0
    review_landed = True
    review_state = "off"

    if review_enabled is False or (review_provider_set and (not provider_ids or provider_ids == ["none"])):
        pass
    elif not review_provider_set and not provider_ids:
        cr_state = "unconfigured"
        cr_status = "unconfigured"
        review_state = "unconfigured"
        review_landed = True
    elif provider_ids == ["none"] or (len(provider_ids) == 1 and provider_ids[0] == "none"):
        pass
    else:
        active_ids = [p for p in provider_ids if p and p != "none"]
        states: list[tuple[str, dict[str, Any]]] = []
        env_parent = dict(os.environ)
        env_parent.update(
            {
                "SW_PR": str(pr),
                "SW_HEAD_SHA": head_sha,
                "SW_OWNER": owner,
                "SW_REPO": repo,
                "SW_OWNER_REPO": owner_repo,
                "SW_ROOT": str(root),
                "SW_CHECKS_FILE": str(checks_file),
                "SW_ISSUE_COMMENTS_FILE": str(issue_comments_file),
                "SW_GRACE_MIN": str(grace_min),
            }
        )
        sw_context_keys = (
            "SW_PR",
            "SW_HEAD_SHA",
            "SW_OWNER",
            "SW_REPO",
            "SW_OWNER_REPO",
            "SW_ROOT",
            "SW_CHECKS_FILE",
            "SW_ISSUE_COMMENTS_FILE",
            "SW_GRACE_MIN",
        )
        for pid in active_ids:
            adapter = plugin_root / "providers" / "review" / f"{pid}.py"
            if not adapter.is_file():
                return (
                    {
                        "error": True,
                        "payload": {
                            "verdict": "blocked",
                            "reason": f"unknown review provider: {pid}",
                        },
                        "exit_code": 30,
                    },
                    deprecations,
                )
            completed = proc.run(
                [sys.executable, str(adapter)],
                cwd=str(root),
                child_env=proc.HookVerifyEnv(
                    declared_context_keys=sw_context_keys,
                    parent=env_parent,
                ),
            )
            try:
                review_json = json.loads(completed.stdout.strip() or "{}")
            except json.JSONDecodeError:
                review_json = {}
            states.append((pid, review_json))

        merged = synthesize_gate_adapters(states)
        review_landed = bool(merged.get("reviewLanded"))
        review_state = str(merged.get("reviewState") or "in-flight")
        cr_state = review_state
        cr_landed = review_landed
        cr_reviewed_head = str(merged.get("reviewedHead") or "")
        cr_status = str((states[0][1].get("statusContext") if states else "absent") or "absent")
        cr_marker = any(bool(st.get("inProgressMarker")) for _, st in states)
        cr_skipped = all(bool(st.get("skipped")) for _, st in states) if states else False
        mins_since = max(int(st.get("minutesSinceHeadPush", 0) or 0) for _, st in states) if states else 0
        if states and not all(bool((st.get("capabilities") or {}).get("perHeadState")) for _, st in states):
            cr_state = "in-flight"
            cr_landed = False
            review_landed = False
            review_state = "in-flight"

    return (
        {
            "error": False,
            "review_provider": review_provider,
            "cr_state": cr_state,
            "cr_landed": cr_landed,
            "cr_reviewed_head": cr_reviewed_head,
            "cr_status": cr_status,
            "cr_marker": cr_marker,
            "cr_skipped": cr_skipped,
            "mins_since": mins_since,
            "review_landed": review_landed,
            "review_state": review_state,
        },
        deprecations,
    )


def scripts_touch_advisory(root: Path, pr_view: dict[str, Any], head_sha: str, reason: str) -> str:
    base_ref = pr_view.get("baseRefName") if isinstance(pr_view, dict) else None
    if not base_ref:
        return reason
    proc.run(["git", "-C", str(root), "fetch", "-q", "origin", str(base_ref)], cwd=str(root))
    merge_base = proc.run(
        ["git", "-C", str(root), "merge-base", f"origin/{base_ref}", head_sha],
        cwd=str(root),
    )
    if merge_base.returncode != 0 or not merge_base.stdout.strip():
        return reason
    diff = proc.run(
        ["git", "-C", str(root), "diff", "--name-only", merge_base.stdout.strip(), head_sha],
        cwd=str(root),
    )
    if diff.returncode == 0 and any(
        line.startswith("scripts/") for line in diff.stdout.splitlines()
    ):
        return f"{reason}; advisory: PR touches scripts/ — consider python3 scripts/build-chain-sync.py"
    return reason


def run_local_evidence_gate(root: Path, cfg: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    head_proc = proc.run(["git", "-C", str(root), "rev-parse", "HEAD"], cwd=str(root))
    head_sha = head_proc.stdout.strip() if head_proc.returncode == 0 else ""
    branch_proc = proc.run(
        ["git", "-C", str(root), "branch", "--show-current"],
        cwd=str(root),
    )
    branch = branch_proc.stdout.strip() if branch_proc.returncode == 0 else ""
    if not head_sha:
        payload = {
            "verdict": "blocked",
            "reason": "not a git repository",
            "source": "local-evidence",
        }
        jsonio.emit(payload)
        return 30, payload

    neutral_pass = bool(cfg_value(cfg, "checks", "treatNeutralAsPass", default=True))
    allowlist = cfg_value(cfg, "checks", "neutralAllowlist", default=[]) or []
    if not isinstance(allowlist, list):
        allowlist = []
    from review_synthesize import resolve_review_providers

    review_cfg = cfg.get("review") if isinstance(cfg.get("review"), dict) else {}
    ids = resolve_review_providers(review_cfg)
    review_provider = ",".join(ids) if ids else str(cfg_value(cfg, "review", "provider", default="none") or "none")
    pr_test_plan, advisory_jobs, required_jobs = load_pr_test_plan(root, cfg)
    slim_ref = slim_pr_test_plan_gate(root, pr_test_plan, required_jobs, advisory_jobs) if pr_test_plan is not None else None
    manifest_err = validate_pr_test_plan_gate(root, slim_ref)
    if manifest_err:
        payload = {
            "verdict": "blocked",
            "reason": f"prTestPlan:{manifest_err}",
            "source": "local-evidence",
        }
        jsonio.emit(payload)
        return 30, payload

    effective_config_err = validate_effective_config_drift(root)
    if effective_config_err:
        payload = {
            "verdict": "blocked",
            "reason": f"effectiveConfig:{effective_config_err}",
            "source": "local-evidence",
        }
        jsonio.emit(payload)
        return 30, payload

    documented_defaults_err = validate_documented_defaults_drift(root)
    if documented_defaults_err:
        payload = {
            "verdict": "blocked",
            "reason": f"documentedDefaults:{documented_defaults_err}",
            "source": "local-evidence",
        }
        jsonio.emit(payload)
        return 30, payload

    resilience_err = validate_resilience_verify_scope(root, cfg)
    if resilience_err:
        payload = {
            "verdict": "blocked",
            "reason": f"resilienceVerify:{resilience_err}",
            "source": "local-evidence",
        }
        jsonio.emit(payload)
        return 30, payload

    if not re.fullmatch(r"[a-z0-9-]*", review_provider):
        payload = {
            "verdict": "blocked",
            "reason": f"invalid review.provider: {review_provider}",
        }
        jsonio.emit(payload)
        return 30, payload

    repo_meta = host_data(root, "repo-meta") or {}
    owner_repo = str(repo_meta.get("nameWithOwner") or "local/repo")
    checks_envelope = resolve_checks_evidence_for_gate(root, sha=head_sha)
    if checks_envelope.get("evidenceValidity") != EVIDENCE_VALID:
        return gate_blocked_for_invalid_checks_evidence(
            checks_envelope,
            plugin_root=resolve_plugin_root(SCRIPT_DIR),
            provider=str(cfg_value(cfg, "host", "provider", default="") or ""),
            head_sha=head_sha,
            source="local-evidence",
        )
    checks_raw = checks_envelope.get("checks") or []
    ttl = stale_in_progress_ttl_seconds(cfg)
    checks_raw, _stale_settled = reconcile_stale_in_progress_checks(
        checks_raw,
        ttl_seconds=ttl,
    )

    classified = classify_checks(checks_raw, neutral_pass=neutral_pass, allowlist=allowlist)
    failing = [c["name"] for c in classified if c["class"] == "fail"]
    pending = [c["name"] for c in classified if c["class"] == "pending"]
    blocking = [c["name"] for c in classified if c["class"] == "block"]
    required_failing, advisory_failing = split_failing(failing, advisory_jobs)
    verdict = compute_verdict(
        required_failing=required_failing,
        blocking=blocking,
        pending=pending,
        cr_landed=True,
        check_count=len(classified),
        actionable=0,
    )
    reason = verdict
    if verdict == "yellow":
        reason = f"checks pending: {','.join(pending)}"
    elif verdict == "red":
        reason = f"failing checks: {','.join(required_failing)}"
    elif verdict == "blocked":
        reason = "empty check set" if len(classified) == 0 else "blocking check outcome"
    elif verdict == "green":
        reason = (
            "local-evidence: all local checks pass; review gating off; "
            "0 actionable threads"
        )

    payload = build_gate_payload(
        root,
        verdict=verdict,
        reason=reason,
        head_sha=head_sha,
        review_provider=review_provider,
        cr_reviewed_head="",
        cr_status="off",
        cr_state="off",
        cr_landed=True,
        cr_marker=False,
        cr_skipped=False,
        mins_since=0,
        unresolved=0,
        actionable=0,
        failing=failing,
        required_failing=required_failing,
        advisory_failing=advisory_failing,
        pr_test_plan=pr_test_plan,
        required_jobs=required_jobs,
        advisory_jobs=advisory_jobs,
        pending=pending,
        blocking=blocking,
        check_count=len(classified),
        deprecations=[],
        branch=branch,
        source="local-evidence",
        pr=None,
        reason_code=blocked_reason_code_for_verdict(
            verdict,
            check_count=len(classified),
            blocking=blocking,
            actionable=0,
        ),
    )
    return finalize_gate_payload(
        root,
        cfg,
        payload,
        verdict=verdict,
        required_failing=required_failing,
        reason=reason,
    )


def run_gate(root: Path, pr_arg: str | None = None) -> tuple[int, dict[str, Any]]:
    """Compute gate verdict; emit JSON to stdout; return (exit_code, payload)."""
    if str(SCRIPT_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPT_DIR))

    from host_lib import resolve_provider

    cfg = load_workflow_config(root)
    plugin_root = resolve_plugin_root(SCRIPT_DIR)
    neutral_pass = bool(cfg_value(cfg, "checks", "treatNeutralAsPass", default=True))
    grace_min = int(cfg_value(cfg, "coderabbit", "reviewGraceMinutes", default=15) or 15)
    allowlist = cfg_value(cfg, "checks", "neutralAllowlist", default=[]) or []
    if not isinstance(allowlist, list):
        allowlist = []
    pr_test_plan, advisory_jobs, required_jobs = load_pr_test_plan(root, cfg)
    slim_ref = (
        slim_pr_test_plan_gate(root, pr_test_plan, required_jobs, advisory_jobs)
        if pr_test_plan is not None
        else None
    )
    manifest_err = validate_pr_test_plan_gate(root, slim_ref)
    if manifest_err:
        payload = {"verdict": "blocked", "reason": f"prTestPlan:{manifest_err}"}
        jsonio.emit(payload)
        return 30, payload

    effective_config_err = validate_effective_config_drift(root)
    if effective_config_err:
        payload = {"verdict": "blocked", "reason": f"effectiveConfig:{effective_config_err}"}
        jsonio.emit(payload)
        return 30, payload

    documented_defaults_err = validate_documented_defaults_drift(root)
    if documented_defaults_err:
        payload = {"verdict": "blocked", "reason": f"documentedDefaults:{documented_defaults_err}"}
        jsonio.emit(payload)
        return 30, payload

    resilience_err = validate_resilience_verify_scope(root, cfg)
    if resilience_err:
        payload = {"verdict": "blocked", "reason": f"resilienceVerify:{resilience_err}"}
        jsonio.emit(payload)
        return 30, payload

    resolved = resolve_provider(root)
    host_provider = str(resolved.get("provider") or "")
    if host_provider == "none":
        return run_local_evidence_gate(root, cfg)

    pr = pr_arg
    if not pr:
        items = host_data(root, "resolve-pr-for-branch") or []
        if isinstance(items, list) and items:
            pr = str(items[0].get("number") or "")
    if not pr:
        payload = {"verdict": "blocked", "reason": "no open PR for current branch"}
        jsonio.emit(payload)
        return 30, payload

    pr_view = host_data(root, "pr-view", "--number", pr) or {}
    head_sha = str(pr_view.get("headRefOid") or "")
    mergeable = str(pr_view.get("mergeable") or "")
    merge_state = str(pr_view.get("mergeStateStatus") or "")
    repo_meta = host_data(root, "repo-meta") or {}
    owner_repo = str(repo_meta.get("nameWithOwner") or "")
    if not head_sha or not owner_repo:
        payload = {"verdict": "blocked", "reason": "incomplete host metadata (head or repo)"}
        jsonio.emit(payload)
        return 30, payload
    if mergeable == "CONFLICTING" or merge_state == "DIRTY":
        payload = {
            "verdict": "blocked",
            "reason": "merge-conflict",
            "mergeable": mergeable,
            "mergeStateStatus": merge_state,
            "recommendedCommand": "/sw-stabilize",
        }
        jsonio.emit(payload)
        return 30, payload

    owner = owner_repo.split("/", 1)[0] if "/" in owner_repo else owner_repo
    repo = owner_repo.split("/", 1)[1] if "/" in owner_repo else owner_repo

    checks_envelope = resolve_checks_evidence_for_gate(root, pr=pr, sha=head_sha)
    if checks_envelope.get("evidenceValidity") != EVIDENCE_VALID:
        return gate_blocked_for_invalid_checks_evidence(
            checks_envelope,
            plugin_root=plugin_root,
            provider=host_provider,
            head_sha=head_sha,
            pr=int(pr),
        )
    checks_raw = checks_envelope.get("checks") or []
    ttl = stale_in_progress_ttl_seconds(cfg)
    checks_raw, stale_settled = reconcile_stale_in_progress_checks(
        checks_raw,
        ttl_seconds=ttl,
    )
    classified = classify_checks(checks_raw, neutral_pass=neutral_pass, allowlist=allowlist)
    failing = [c["name"] for c in classified if c["class"] == "fail"]
    pending = [c["name"] for c in classified if c["class"] == "pending"]
    blocking = [c["name"] for c in classified if c["class"] == "block"]
    required_failing, advisory_failing = split_failing(failing, advisory_jobs)

    threads = host_data(root, "review-threads", "--number", pr) or {}
    unresolved = int(threads.get("unresolved", 0) or 0) if isinstance(threads, dict) else 0
    actionable = int(threads.get("actionable", 0) or 0) if isinstance(threads, dict) else 0

    with tempfile.NamedTemporaryFile(prefix="sw-gate-checks.", delete=False) as checks_f:
        checks_path = Path(checks_f.name)
        checks_f.write(json.dumps(checks_raw).encode("utf-8"))
    with tempfile.NamedTemporaryFile(prefix="sw-gate-comments.", delete=False) as comments_f:
        comments_path = Path(comments_f.name)

    try:
        review_result, deprecations = resolve_review_state(
            root,
            plugin_root,
            cfg,
            pr=pr,
            head_sha=head_sha,
            owner=owner,
            repo=repo,
            owner_repo=owner_repo,
            checks_file=checks_path,
            issue_comments_file=comments_path,
            grace_min=grace_min,
        )
    finally:
        checks_path.unlink(missing_ok=True)
        comments_path.unlink(missing_ok=True)

    if review_result.get("error"):
        payload = review_result["payload"]
        jsonio.emit(payload)
        return int(review_result.get("exit_code", 30)), payload

    verdict = compute_verdict(
        required_failing=required_failing,
        blocking=blocking,
        pending=pending,
        cr_landed=bool(review_result.get("review_landed", review_result["cr_landed"])),
        check_count=len(classified),
        actionable=actionable,
    )
    reason = build_reason(
        verdict,
        pending=pending,
        required_failing=required_failing,
        advisory_failing=advisory_failing,
        actionable=actionable,
        cr_landed=bool(review_result.get("review_landed", review_result["cr_landed"])),
        cr_state=str(review_result["cr_state"]),
        head_sha=head_sha,
        review_provider=str(review_result["review_provider"]),
        check_count=len(classified),
        blocking=blocking,
    )
    if verdict == "green" and pr and head_sha:
        reason = scripts_touch_advisory(root, pr_view, head_sha, reason)

    payload = build_gate_payload(
        root,
        verdict=verdict,
        reason=reason,
        head_sha=head_sha,
        review_provider=str(review_result["review_provider"]),
        cr_reviewed_head=str(review_result["cr_reviewed_head"]),
        cr_status=str(review_result["cr_status"]),
        cr_state=str(review_result["cr_state"]),
        cr_landed=bool(review_result["cr_landed"]),
        cr_marker=bool(review_result["cr_marker"]),
        cr_skipped=bool(review_result["cr_skipped"]),
        mins_since=int(review_result["mins_since"]),
        unresolved=unresolved,
        actionable=actionable,
        failing=failing,
        required_failing=required_failing,
        advisory_failing=advisory_failing,
        pr_test_plan=pr_test_plan,
        required_jobs=required_jobs,
        advisory_jobs=advisory_jobs,
        pending=pending,
        blocking=blocking,
        check_count=len(classified),
        deprecations=deprecations,
        pr=int(pr),
        reason_code=blocked_reason_code_for_verdict(
            verdict,
            check_count=len(classified),
            blocking=blocking,
            actionable=actionable,
        ),
    )
    return finalize_gate_payload(
        root,
        cfg,
        payload,
        verdict=verdict,
        required_failing=required_failing,
        reason=reason,
    )
