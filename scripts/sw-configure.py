#!/usr/bin/env python3
"""Single per-repo configurator for /sw-init (PRD 018 R29/R30/R32).

PRD 342 R22: dry-run enumerates repository-scope and machine-scope writes before
any write occurs.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))


from _sw.cli import run_module_main
from init_credential_migration import (
    apply_guided_single_identity,
    build_credential_checklist,
    build_init_plan,
    credential_patch_for_draft,
    offer_ci_env_declaration,
    offer_example_env_file,
    offer_legacy_migration,
    selector_add,
)
from host_lib import default_base_branch
from init_ci_stub import STUB_WORKFLOW_REL, apply_ci_stub, plan_ci_stub
from init_profile_report import (
    classify_profile,
    derive_interview_priorities,
    greenfield_curated_patch,
    interview_reuse_bundle,
    load_config_schema,
    load_workflow_config,
    render_classification_markdown,
)
from init_scripts_facade import (
    PRIORITY_ZERO_SURFACES,
    record_priority_zero_surface,
    validate_priority_zero_coverage,
)
import project_baseline as _project_baseline
import project_doctrine as _project_doctrine
from project_doctrine_leakage import evaluate_doctrine as _evaluate_doctrine_leakage
from wave_preflight import CI_PRESENCE_SATISFIED, scan_ci_workflows

# UX side-channel keys — never persisted to workflow.config.json (PRD 324 R11).
DRAFT_SIDE_CHANNEL_KEYS = frozenset({"verifyGaps", "projectTypeDetection"})

# Consent-gated ProjectDoctrine adoption (PRD 330 R6/R11/R12/R14) — decline marker only.
DOCTRINE_DECLINE_REL = Path(".cursor/sw-init-project-doctrine.json")
# Future /sw-explore handoff surface — never registered as a command in this PRD.
FUTURE_EXPLORE_HANDOFF = {
    "command": "/sw-explore",
    "status": "not-shipped",
    "prd": "331",
    "consumes": _project_baseline.SYNTHESIS_INTERFACE_VERSION,
    "registersCommands": [],
}


def _plugin_root() -> Path:
    from sw_resolve_plugin_root import resolve_plugin_root

    return Path(resolve_plugin_root(SCRIPT_DIR))


def schema_path(root: Path) -> Path:
    plugin_root = _plugin_root()
    for candidate in (
        root / ".sw/config.schema.json",
        root / "core/sw-reference/config.schema.json",
        plugin_root / "core/sw-reference/config.schema.json",
        Path(os.environ.get("CURSOR_PLUGIN_ROOT", "")) / "core/sw-reference/config.schema.json",
        Path(os.environ.get("CURSOR_PLUGIN_ROOT", "")) / ".sw/config.schema.json",
    ):
        if candidate.is_file():
            return candidate
    return root / ".sw/config.schema.json"


def shipwright_version(root: Path) -> str:
    for candidate in (
        root / "version.txt",
        Path(os.environ.get("CURSOR_PLUGIN_ROOT", "")) / "version.txt",
    ):
        if candidate.is_file():
            return candidate.read_text(encoding="utf-8").strip()
    return "unknown"


def schema_version(root: Path) -> str:
    path = schema_path(root)
    if not path.is_file():
        return "unknown"
    return hashlib.sha256(path.read_bytes()).hexdigest()[:12]


def cmd_drift_check(root: Path, config: str) -> int:
    from shipwright_paths import workflow_config_write_path

    config_path = config or str(workflow_config_write_path(root))
    sw_ver = shipwright_version(root)
    sch_ver = schema_version(root)
    stale = False
    configured: dict = {}
    if config_path and Path(config_path).is_file():
        cfg = json.loads(Path(config_path).read_text(encoding="utf-8"))
        configured = cfg.get("configuredWith") or {}
        if configured.get("shipwrightVersion") != sw_ver or configured.get("schemaVersion") != sch_ver:
            stale = True
    print(
        json.dumps(
            {
                "stale": stale,
                "configuredWith": configured,
                "current": {"shipwrightVersion": sw_ver, "schemaVersion": sch_ver},
                "notice": "config may be stale; run /sw-init to refresh" if stale else None,
            },
            indent=2,
        )
    )
    return 0


def _deep_merge(base: dict, patch: dict) -> dict:
    merged = dict(base)
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(dict(merged[key]), value)
        else:
            merged[key] = value
    return merged


def _credential_argv(rest: list[str]) -> tuple[str, list[str]]:
    if not rest:
        return "", []
    return rest[0], rest[1:]


def cmd_ci_stub(root: Path, subcmd: str, rest: list[str]) -> int:
    confirm = "--confirm" in rest
    wire_verify = "--wire-verify" in rest
    config_root = root
    i = 0
    while i < len(rest):
        token = rest[i]
        if token == "--root" and i + 1 < len(rest):
            config_root = Path(rest[i + 1]).expanduser().resolve()
            i += 2
            continue
        i += 1
    wire: str = "on" if wire_verify else "off"
    if subcmd in ("", "plan"):
        payload = plan_ci_stub(config_root, wire_verify=wire)
        print(json.dumps(payload, indent=2))
        return 0
    if subcmd == "apply":
        payload = apply_ci_stub(config_root, confirm=confirm, wire_verify=wire)
        print(json.dumps(payload, indent=2))
        if payload.get("verdict") == "fail":
            return 2
        return 0
    print(json.dumps({"verdict": "fail", "error": f"unknown ci-stub command: {subcmd}"}), file=sys.stderr)
    return 2


def cmd_credential(root: Path, subcmd: str, rest: list[str]) -> int:
    confirm = "--confirm" in rest
    selector_path = ""
    xdg_base = ""
    config_root = Path.cwd()
    i = 0
    while i < len(rest):
        token = rest[i]
        if token == "--root" and i + 1 < len(rest):
            config_root = Path(rest[i + 1]).expanduser().resolve()
            i += 2
            continue
        if token == "--selector-path" and i + 1 < len(rest):
            selector_path = rest[i + 1]
            i += 2
            continue
        if token == "--xdg-base" and i + 1 < len(rest):
            xdg_base = rest[i + 1]
            i += 2
            continue
        i += 1
    selector = Path(selector_path) if selector_path else None
    xdg = Path(xdg_base) if xdg_base else None
    plan = build_init_plan(config_root, selector_path=selector, xdg_base=xdg)

    if subcmd == "plan":
        payload = plan.to_public_dict()
        payload["checklist"] = build_credential_checklist(
            config_root,
            plan,
            selector_path=selector,
            xdg_base=xdg,
        ).to_public_dict()
        print(json.dumps(payload, indent=2))
        return 0
    if subcmd == "checklist":
        checklist = build_credential_checklist(
            config_root,
            plan,
            selector_path=selector,
            xdg_base=xdg,
        )
        print(json.dumps(checklist.to_public_dict(), indent=2))
        return 0
    if subcmd == "example-env":
        token_env = ""
        j = 0
        while j < len(rest):
            token = rest[j]
            if token == "--token-env" and j + 1 < len(rest):
                token_env = rest[j + 1]
                j += 2
                continue
            j += 1
        if not token_env.strip():
            print(json.dumps({"verdict": "fail", "error": "--token-env required"}), file=sys.stderr)
            return 2
        result = offer_example_env_file(config_root, token_env=token_env.strip(), confirm=confirm)
        print(json.dumps(result, indent=2))
        return 0 if result.get("verdict") in {"ok", "confirm-required"} else 1
    if subcmd == "apply":
        result = apply_guided_single_identity(
            config_root,
            plan,
            confirm=confirm,
            selector_path=selector,
            xdg_base=xdg,
        )
        print(json.dumps(result, indent=2))
        return 0 if result.get("verdict") in {"ok", "confirm-required"} else 1
    if subcmd == "migrate":
        result = offer_legacy_migration(
            config_root,
            plan,
            confirm=confirm,
            selector_path=selector,
            xdg_base=xdg,
        )
        print(json.dumps(result, indent=2))
        return 0 if result.get("verdict") in {"ok", "confirm-required", "noop"} else 1
    if subcmd == "declare-ci":
        result = offer_ci_env_declaration(config_root, plan, confirm=confirm)
        print(json.dumps(result, indent=2))
        return 0 if result.get("verdict") in {"ok", "confirm-required"} else 1
    if subcmd == "selector-add":
        values: dict[str, str] = {}
        j = 0
        while j < len(rest):
            token = rest[j]
            if token.startswith("--") and j + 1 < len(rest):
                values[token.removeprefix("--").replace("-", "_")] = rest[j + 1]
                j += 2
                continue
            j += 1
        required = (
            "ref",
            "backend",
            "provider",
            "hostname",
            "account",
            "allowed_repo",
            "allowed_project_id",
            "allowed_endpoint",
        )
        missing = [key for key in required if not values.get(key)]
        if missing:
            print(json.dumps({"verdict": "fail", "missing": missing}), file=sys.stderr)
            return 2
        result = selector_add(
            ref=values["ref"],
            backend=values["backend"],
            provider=values["provider"],
            hostname=values["hostname"],
            account=values["account"],
            allowed_repo=values["allowed_repo"],
            allowed_project_id=values["allowed_project_id"],
            allowed_endpoint=values["allowed_endpoint"],
            selector_path=selector,
            xdg_base=xdg,
        )
        print(json.dumps(result, indent=2))
        return 0
    print(json.dumps({"verdict": "fail", "error": f"unknown credential command: {subcmd}"}), file=sys.stderr)
    return 2


def _strip_draft_side_channel(draft: dict) -> dict:
    """Return a schema-persistable copy without UX-only side-channel keys."""
    return {key: value for key, value in draft.items() if key not in DRAFT_SIDE_CHANNEL_KEYS}


def _validate_config_document(root: Path, document: dict) -> list[str]:
    """Validate against config.schema.json when jsonschema is available."""
    path = schema_path(root)
    if not path.is_file():
        return []
    try:
        import jsonschema
    except ImportError:
        return []
    schema = json.loads(path.read_text(encoding="utf-8"))
    validator = jsonschema.Draft7Validator(schema)
    return [err.message for err in validator.iter_errors(document)]


def _detect_project_type(root: Path) -> dict:
    return json.loads(
        subprocess.check_output(
            [sys.executable, str(SCRIPT_DIR / "detect-project-type.py"), "--root", str(root), "--propose"],
            text=True,
        )
    )


def build_findings_report(root: Path, *, markdown: bool = False) -> dict:
    """Consolidated init findings — profile classification + CI presence (PRD 324 R8/R10)."""
    config = load_workflow_config(root)
    profile = classify_profile(root, config=config)
    default_branch = default_base_branch(root)
    ci_scan = scan_ci_workflows(root, default_branch)
    detect = _detect_project_type(root)
    warnings: list[dict] = []
    if ci_scan.get("presence") != CI_PRESENCE_SATISFIED:
        warnings.append(
            {
                "code": "ci-presence",
                "message": "deliver will refuse until a PR workflow exists",
                "remediation": "python3 scripts/sw-configure.py ci-stub plan",
                "scan": ci_scan,
            }
        )
    verify_gaps = detect.get("verifyGaps") or []
    if verify_gaps and not config.get("verify"):
        warnings.append(
            {
                "code": "verify-gaps",
                "message": (
                    "detected verify gaps — persist schema-valid verify.* with "
                    "python3 scripts/sw-configure.py write-draft --accept-defaults --write-verify"
                ),
                "verifyGaps": verify_gaps,
            }
        )
    payload: dict = {
        "verdict": "pass" if profile.get("verdict") == "pass" else "fail",
        "profile": profile,
        "ciPresence": ci_scan,
        "projectTypeDetection": {
            "matches": detect.get("matches", []),
            "ambiguous": detect.get("ambiguous", False),
            "verifyGaps": verify_gaps,
        },
        "warnings": warnings,
    }
    if markdown:
        sections = [
            "## Init findings report",
            "",
            render_classification_markdown(profile),
        ]
        if warnings:
            sections.extend(["### Warnings", ""])
            for warning in warnings:
                sections.append(f"- **{warning['code']}**: {warning['message']}")
                if warning.get("remediation"):
                    sections.append(f"  - remediation: `{warning['remediation']}`")
            sections.append("")
        payload["markdown"] = "\n".join(sections)
    return payload


def cmd_findings_report(root: Path, *, markdown: bool) -> int:
    payload = build_findings_report(root, markdown=markdown)
    if markdown and payload.get("markdown"):
        print(payload["markdown"])
    else:
        print(json.dumps(payload, indent=2))
    return 0 if payload.get("verdict") == "pass" else 1


def cmd_write_draft(root: Path, *, accept: bool, write_verify: bool, config: str) -> int:
    out_path = config or "/tmp/sw-init-draft.json"
    detect = _detect_project_type(root)
    draft: dict = {
        "doc": {"afterTasks": "confirm"},
        "compound": {"autonomy": "supervised"},
        "guardrails": {"enforceBeforeSubmit": True, "requireRuleClass": False},
        "review": {"provider": "none"},
        "memory": {"provider": "in-repo", "sourceOfTruth": "auto"},
        "configuredWith": {
            "shipwrightVersion": shipwright_version(root),
            "schemaVersion": schema_version(root),
        },
    }
    draft.update(greenfield_curated_patch())
    draft = _deep_merge(draft, credential_patch_for_draft(root))
    comm_defaults_path = root / "core/sw-reference/communication-routing.defaults.json"
    if comm_defaults_path.is_file():
        try:
            comm_defaults = json.loads(comm_defaults_path.read_text(encoding="utf-8"))
            if isinstance(comm_defaults, dict):
                draft["communication"] = comm_defaults
        except json.JSONDecodeError:
            pass
    side_channel: dict = {}
    write_verify_routing: str | None = None
    if accept:
        side_channel["verifyGaps"] = detect.get("verifyGaps") or []
        side_channel["projectTypeDetection"] = {
            "matches": detect.get("matches", []),
            "ambiguous": detect.get("ambiguous", False),
        }
        if side_channel["verifyGaps"] and not write_verify:
            write_verify_routing = (
                "detected verify gaps — re-run with --write-verify to persist schema-valid verify.* commands"
            )
    if write_verify:
        verify = {}
        for key, meta in (detect.get("proposals") or {}).items():
            if meta.get("safe") and meta.get("command"):
                verify[key] = meta["command"]
        if verify:
            draft["verify"] = verify
    persistable = _strip_draft_side_channel(draft)
    validation_errors = _validate_config_document(root, persistable)
    if validation_errors:
        print(
            json.dumps(
                {
                    "verdict": "fail",
                    "error": "draft-fails-schema-validation",
                    "validationErrors": validation_errors[:8],
                },
                indent=2,
            ),
            file=sys.stderr,
        )
        return 2
    Path(out_path).write_text(json.dumps(persistable, indent=2) + "\n", encoding="utf-8")
    response: dict = {
        "verdict": "pass",
        "path": out_path,
        "verifyWritten": bool(persistable.get("verify")),
    }
    if side_channel:
        response["sideChannel"] = side_channel
    if write_verify_routing:
        response["writeVerifyRouting"] = write_verify_routing
    print(json.dumps(response, indent=2))
    return 0


def _doctrine_flag(rest: list[str], name: str) -> bool:
    return name in rest


def _doctrine_opt(rest: list[str], name: str, default: str = "") -> str:
    i = 0
    while i < len(rest):
        if rest[i] == name and i + 1 < len(rest):
            return rest[i + 1]
        i += 1
    return default


def _doctrine_config_root(root: Path, rest: list[str]) -> Path:
    override = _doctrine_opt(rest, "--root")
    if override:
        return Path(override).expanduser().resolve()
    return root.resolve()


def load_doctrine_decline(root: Path) -> dict | None:
    path = root / DOCTRINE_DECLINE_REL
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def record_doctrine_decline(root: Path, *, reason: str = "operator-decline") -> dict:
    path = root / DOCTRINE_DECLINE_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "declined": True,
        "reason": reason,
        "authoritative": False,
        "promoted": False,
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return {
        "verdict": "pass",
        "action": "decline",
        "declined": True,
        "authoritative": False,
        "promoted": False,
        "declinePath": DOCTRINE_DECLINE_REL.as_posix(),
        "reason": reason,
    }


def clear_doctrine_decline(root: Path) -> None:
    path = root / DOCTRINE_DECLINE_REL
    if path.is_file():
        path.unlink()


def _confirm_required(action: str) -> dict:
    return {
        "verdict": "confirm-required",
        "action": action,
        "cause": "confirm-required",
        "authoritative": False,
        "promoted": False,
        "remediation": f"Re-run with --confirm to proceed ({action}).",
    }


def _clear_draft_artifacts(root: Path) -> bool:
    removed = False
    for path in (
        _project_doctrine.baseline_draft_path(root),
        _project_baseline.draft_path(root),
    ):
        if path.is_file():
            path.unlink()
            removed = True
    return removed


def build_doctrine_discover(root: Path) -> dict:
    """Read-only doctrine discovery for /sw-init (never writes doctrine)."""
    observations = _project_baseline.discover_observations(root)
    status = _project_doctrine.status_report(root)
    decline = load_doctrine_decline(root)
    declined = bool(decline and decline.get("declined"))
    mode = "greenfield"
    if observations:
        mode = "brownfield"
    elif status.get("hasDoctrine"):
        mode = "existing"
    return {
        "verdict": "pass",
        "action": "plan",
        "authoritative": False,
        "promoted": False,
        "writesDoctrine": False,
        "mode": mode,
        "observationCount": len(observations),
        "observations": observations,
        "status": status,
        "declined": declined,
        "declineRecord": decline,
        "offers": {
            "skip": "python3 scripts/sw-configure.py doctrine skip",
            "decline": "python3 scripts/sw-configure.py doctrine decline",
            "greenfieldScaffold": (
                "python3 scripts/sw-configure.py doctrine greenfield-scaffold --confirm"
            ),
            "brownfieldSynthesize": (
                "python3 scripts/sw-configure.py doctrine brownfield-synthesize --confirm"
            ),
            "review": "python3 scripts/sw-configure.py doctrine review",
            "acceptPromote": (
                "python3 scripts/sw-configure.py doctrine accept-promote --confirm"
            ),
            "acceptDoctrine": (
                "python3 scripts/sw-configure.py doctrine accept-doctrine --confirm"
            ),
            "reject": "python3 scripts/sw-configure.py doctrine reject",
        },
        "autoPromote": False,
        "futureExploreHandoff": FUTURE_EXPLORE_HANDOFF,
        "synthesisInterface": _project_baseline.interface_contract(),
    }


def _synthesize_brownfield_draft(root: Path, *, actor: str) -> dict:
    baseline = _project_baseline.synthesize_from_root(root, actor=actor)
    advisory = _project_baseline.write_draft(root, baseline)
    lifecycle = _project_doctrine.write_baseline_draft(root, baseline, actor=actor)
    ok = advisory.get("verdict") == "pass" and lifecycle.verdict == "pass"
    return {
        "verdict": "pass" if ok else "fail",
        "action": "brownfield-synthesize",
        "authoritative": False,
        "promoted": False,
        "status": "draft",
        "autoPromote": False,
        "advisoryDraft": advisory,
        "lifecycleDraft": lifecycle.to_dict(),
        "baseline": baseline,
        "remediation": (
            "Review with doctrine review, then accept-promote --confirm — never auto-promotes."
        ),
        "futureExploreHandoff": FUTURE_EXPLORE_HANDOFF,
    }


def _accept_doctrine_document(root: Path, doc: dict, *, actor: str, action: str) -> dict:
    leakage = _evaluate_doctrine_leakage(doc)
    if leakage.get("verdict") != "pass":
        return {
            "verdict": "fail",
            "action": action,
            "cause": "leakage-not-green",
            "authoritative": False,
            "promoted": False,
            "leakage": leakage,
        }
    result = _project_doctrine.accept_doctrine(root, doc, actor=actor)
    if result.verdict == "pass":
        clear_doctrine_decline(root)
    return {
        **result.to_dict(),
        "action": action,
        "authoritative": result.verdict == "pass",
        "promoted": result.verdict == "pass",
        "leakage": leakage,
    }


def cmd_doctrine(root: Path, subcmd: str, rest: list[str]) -> int:
    """Consent-gated ProjectDoctrine adoption surface for /sw-init (PRD 330 R6/R11/R12/R14)."""
    config_root = _doctrine_config_root(root, rest)
    confirm = _doctrine_flag(rest, "--confirm")
    actor = _doctrine_opt(rest, "--actor", "operator") or "operator"
    file_opt = _doctrine_opt(rest, "--file")
    reason = _doctrine_opt(rest, "--reason", "operator-decline") or "operator-decline"

    aliases = {
        "": "plan",
        "discover": "plan",
        "status": "plan",
        "synthesize-draft": "brownfield-synthesize",
        "scaffold-greenfield": "greenfield-scaffold",
        "promote": "accept-promote",
        "accept": "accept-doctrine",
    }
    action = aliases.get(subcmd, subcmd)

    if action == "plan":
        payload = build_doctrine_discover(config_root)
        print(json.dumps(payload, indent=2))
        return 0

    if action == "review":
        status = _project_doctrine.status_report(config_root)
        draft = _project_doctrine.load_baseline_draft(config_root)
        doctrine = _project_doctrine.load_doctrine(config_root)
        candidate = doctrine
        if candidate is None and file_opt:
            candidate = _project_doctrine.load_json(Path(file_opt))
        leakage = (
            _evaluate_doctrine_leakage(candidate) if isinstance(candidate, dict) else None
        )
        payload = {
            "verdict": "pass",
            "action": "review",
            "authoritative": False,
            "promoted": bool(status.get("hasDoctrine")),
            "status": status,
            "baselineDraft": draft,
            "doctrine": doctrine,
            "leakage": leakage,
            "choices": ["accept-promote", "accept-doctrine", "reject", "decline", "skip"],
            "autoPromote": False,
            "futureExploreHandoff": FUTURE_EXPLORE_HANDOFF,
        }
        print(json.dumps(payload, indent=2))
        return 0

    if action == "skip":
        payload = record_doctrine_decline(config_root, reason=reason or "operator-skip")
        payload["action"] = "skip"
        print(json.dumps(payload, indent=2))
        return 0

    if action in ("decline", "reject"):
        removed = _project_doctrine.reject_adoption(config_root)
        draft_removed = _clear_draft_artifacts(config_root)
        decline = record_doctrine_decline(config_root, reason=reason)
        payload = {
            "verdict": "pass" if removed.verdict == "pass" else removed.verdict,
            "action": action,
            "authoritative": False,
            "promoted": False,
            "doctrineRemoved": removed.verdict == "pass",
            "draftRemoved": draft_removed,
            "decline": decline,
        }
        print(json.dumps(payload, indent=2))
        return 0 if payload["verdict"] == "pass" else 1

    if action == "greenfield-scaffold":
        if not confirm:
            print(json.dumps(_confirm_required(action), indent=2))
            return 1
        clear_doctrine_decline(config_root)
        result = _project_doctrine.scaffold_greenfield(
            config_root, actor=actor, confirm=True
        )
        doctrine = _project_doctrine.load_doctrine(config_root)
        leakage = (
            _evaluate_doctrine_leakage(doctrine)
            if isinstance(doctrine, dict)
            else {"verdict": "fail", "findings": [{"rule": "missing-doctrine"}]}
        )
        payload = {
            **result.to_dict(),
            "action": action,
            "authoritative": result.verdict == "pass",
            "promoted": False,
            "leakage": leakage,
        }
        if result.verdict == "pass" and leakage.get("verdict") != "pass":
            _project_doctrine.reject_adoption(config_root)
            payload["verdict"] = "fail"
            payload["cause"] = "leakage-not-green"
            payload["authoritative"] = False
        print(json.dumps(payload, indent=2))
        return 0 if payload.get("verdict") == "pass" else 1

    if action == "brownfield-synthesize":
        if not confirm:
            print(json.dumps(_confirm_required(action), indent=2))
            return 1
        payload = _synthesize_brownfield_draft(config_root, actor=actor)
        print(json.dumps(payload, indent=2))
        return 0 if payload["verdict"] == "pass" else 1

    if action == "accept-promote":
        if not confirm:
            print(json.dumps(_confirm_required(action), indent=2))
            return 1
        result = _project_doctrine.promote_baseline(
            config_root, actor=actor, confirm=True
        )
        doctrine = _project_doctrine.load_doctrine(config_root)
        leakage = (
            _evaluate_doctrine_leakage(doctrine)
            if isinstance(doctrine, dict)
            else {"verdict": "fail", "findings": [{"rule": "missing-doctrine"}]}
        )
        payload = {
            **result.to_dict(),
            "action": action,
            "authoritative": result.verdict == "pass",
            "promoted": result.verdict == "pass",
            "leakage": leakage,
        }
        if result.verdict == "pass" and leakage.get("verdict") != "pass":
            _project_doctrine.reject_adoption(config_root)
            payload["verdict"] = "fail"
            payload["cause"] = "leakage-not-green"
            payload["authoritative"] = False
            payload["promoted"] = False
        elif result.verdict == "pass":
            clear_doctrine_decline(config_root)
        print(json.dumps(payload, indent=2))
        return 0 if payload.get("verdict") == "pass" else 1

    if action == "accept-doctrine":
        if not confirm:
            print(json.dumps(_confirm_required(action), indent=2))
            return 1
        if file_opt:
            doc = _project_doctrine.load_json(Path(file_opt))
        else:
            doc = _project_doctrine.load_doctrine(config_root)
        if doc is None:
            print(
                json.dumps(
                    {
                        "verdict": "fail",
                        "action": action,
                        "cause": "missing-input",
                        "authoritative": False,
                        "promoted": False,
                        "remediation": "Pass --file <reviewed-doctrine.json> or accept-promote first.",
                    },
                    indent=2,
                )
            )
            return 1
        payload = _accept_doctrine_document(
            config_root, doc, actor=actor, action=action
        )
        print(json.dumps(payload, indent=2))
        return 0 if payload.get("verdict") == "pass" else 1

    print(
        json.dumps(
            {
                "verdict": "fail",
                "error": f"unknown doctrine command: {subcmd}",
                "allowed": [
                    "plan",
                    "review",
                    "skip",
                    "decline",
                    "greenfield-scaffold",
                    "brownfield-synthesize",
                    "accept-promote",
                    "accept-doctrine",
                    "reject",
                ],
            }
        ),
        file=sys.stderr,
    )
    return 2


# Alias kept for callers / docs that say project-doctrine.
cmd_project_doctrine = cmd_doctrine


def cmd_portability_check(root: Path, config: str) -> int:
    from shipwright_paths import workflow_config_write_path

    config_path = config or str(workflow_config_write_path(root))
    subprocess.run(
        [sys.executable, str(SCRIPT_DIR / "verify-unconfigured.py"), "--config", config_path or "/nonexistent", "--json"],
        cwd=str(root),
        check=False,
    )
    detect_raw = subprocess.run(
        [sys.executable, str(SCRIPT_DIR / "detect-project-type.py"), "--root", str(root), "--propose"],
        capture_output=True,
        text=True,
        cwd=str(root),
    )
    detect = json.loads(detect_raw.stdout or "{}")
    drift = json.loads(
        subprocess.check_output([sys.executable, str(SCRIPT_DIR / "sw-configure.py"), "drift-check", "--config", config_path], text=True)
    )
    host_proc = subprocess.run(
        [sys.executable, str(SCRIPT_DIR / "host-doctor.py"), "--root", str(root)],
        cwd=str(root),
        capture_output=True,
    )
    if host_proc.returncode == 0:
        gh = "present"
    elif subprocess.run(["which", "gh"], capture_output=True).returncode == 0:
        gh = "available"
    else:
        gh = "missing"
    lines = []
    if detect.get("verifyGaps"):
        lines.append(f"verify gaps: {', '.join(detect['verifyGaps'])}")
    lines.append(f"gh: {gh}")
    if drift.get("stale"):
        lines.append(drift.get("notice", "config stale"))
    if gh == "missing":
        lines.append("warning: host token missing — set host.tokenEnv for CI-readiness gate")
    print(json.dumps({"summary": lines, "gh": gh, "drift": drift}, indent=2))
    return 0



def enumerate_write_scope(
    root: Path,
    *,
    integration: str,
    machine_dest: Path,
    dist_source: Path,
    accept_ci_stub: bool = True,
) -> dict[str, Any]:
    """Enumerate repo-scope and machine-scope writes before any write (R22).

    Repository scope covers ``.shipwright/`` content, emitter-produced host files
    (none for zero-footprint consumer configure), and the operator-accepted CI stub.
    Machine scope covers the declared install root (every path the mirror would write).
    """
    from shipwright_paths import STATE_ROOT_PRIMARY, workflow_config_write_path

    import install as install_mod

    root = root.resolve()
    machine_dest = machine_dest.resolve()
    config_rel = workflow_config_write_path(root).relative_to(root).as_posix()

    repo_shipwright = [config_rel]
    # Consumer configure stays zero-footprint for host-convention trees; emitters
    # write host-required files into the machine plugin tree, not the consumer repo.
    repo_host_files: list[str] = []
    repo_ci: list[str] = []
    if accept_ci_stub:
        plan = plan_ci_stub(root, wire_verify="off")
        if plan.get("needed"):
            repo_ci = [STUB_WORKFLOW_REL.as_posix()]

    machine_paths = install_mod.plan_machine_write_paths(dist_source, machine_dest)

    return {
        "repoScope": {
            "stateRoot": STATE_ROOT_PRIMARY,
            "shipwright": repo_shipwright,
            "hostFiles": repo_host_files,
            "ciStub": repo_ci,
        },
        "machineScope": {
            "integration": integration,
            "installRoot": str(machine_dest),
            "paths": machine_paths,
        },
        "allPaths": sorted(
            {
                *{str((root / p).resolve()) for p in repo_shipwright},
                *{str((root / p).resolve()) for p in repo_host_files},
                *{str((root / p).resolve()) for p in repo_ci},
                *machine_paths,
            }
        ),
    }


def _build_packaged_draft(root: Path) -> dict[str, Any]:
    """Build an accept-defaults draft matching write-draft --accept-defaults --write-verify."""
    detect = _detect_project_type(root)
    draft: dict[str, Any] = {
        "doc": {"afterTasks": "confirm"},
        "compound": {"autonomy": "supervised"},
        "guardrails": {"enforceBeforeSubmit": True, "requireRuleClass": False},
        "review": {"provider": "none"},
        "memory": {"provider": "in-repo", "sourceOfTruth": "auto"},
        "configuredWith": {
            "shipwrightVersion": shipwright_version(root),
            "schemaVersion": schema_version(root),
        },
    }
    draft.update(greenfield_curated_patch())
    draft = _deep_merge(draft, credential_patch_for_draft(root))
    comm_defaults_path = root / "core/sw-reference/communication-routing.defaults.json"
    if comm_defaults_path.is_file():
        try:
            comm_defaults = json.loads(comm_defaults_path.read_text(encoding="utf-8"))
            if isinstance(comm_defaults, dict):
                draft["communication"] = comm_defaults
        except json.JSONDecodeError:
            pass
    verify: dict[str, str] = {}
    for key, meta in (detect.get("proposals") or {}).items():
        if meta.get("safe") and meta.get("command"):
            verify[key] = meta["command"]
    if verify:
        draft["verify"] = verify
    return _strip_draft_side_channel(draft)


def apply_packaged_configure(
    root: Path,
    *,
    accept_ci_stub: bool = True,
) -> dict[str, Any]:
    """Write repo-scope configuration for packaged init (existing spine only)."""
    from shipwright_paths import workflow_config_write_path

    root = root.resolve()
    draft = _build_packaged_draft(root)
    validation_errors = _validate_config_document(root, draft)
    if validation_errors:
        return {
            "verdict": "fail",
            "error": "draft-fails-schema-validation",
            "validationErrors": validation_errors[:8],
        }

    config_path = workflow_config_write_path(root)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps(draft, indent=2) + "\n", encoding="utf-8")
    written = [config_path.relative_to(root).as_posix()]

    ci_payload: dict[str, Any] | None = None
    if accept_ci_stub:
        ci_payload = apply_ci_stub(root, confirm=True, wire_verify="off")
        if ci_payload.get("written"):
            written.append(STUB_WORKFLOW_REL.as_posix())

    return {
        "verdict": "pass",
        "configPath": str(config_path),
        "written": written,
        "ciStub": ci_payload,
    }


def cmd_dry_run(
    root: Path,
    *,
    integration: str,
    machine_dest: Path | None,
    dist_source: Path | None,
    accept_ci_stub: bool,
    source_root: Path | None,
) -> int:
    """Print the write-scope enumeration without writing (R22)."""
    import install as install_mod

    try:
        norm = install_mod.normalize_integration(integration)
    except ValueError as exc:
        print(json.dumps({"verdict": "fail", "error": str(exc)}), file=sys.stderr)
        return 2
    source_root = source_root or REPO_ROOT
    dest = (machine_dest or install_mod.default_dest_for(norm)).expanduser().resolve()
    dist = (dist_source or install_mod.dist_source_for(norm, root=source_root)).resolve()
    scope = enumerate_write_scope(
        root,
        integration=norm,
        machine_dest=dest,
        dist_source=dist,
        accept_ci_stub=accept_ci_stub,
    )
    print(
        json.dumps(
            {
                "verdict": "pass",
                "action": "dry-run",
                "integration": norm,
                "scope": scope,
                "wrote": False,
            },
            indent=2,
        )
    )
    return 0


def _detect_priority_zero_surfaces(root: Path) -> dict[str, dict[str, Any]]:
    """Probe the five priority-zero surfaces without writing (R24)."""
    config = load_workflow_config(root)
    detected: dict[str, dict[str, Any]] = {}

    verify = config.get("verify")
    if isinstance(verify, dict) and any(str(v).strip() for v in verify.values() if isinstance(v, str)):
        detected["verify"] = {"value": verify, "source": "config"}
    else:
        try:
            probe = _detect_project_type(root)
        except (OSError, subprocess.CalledProcessError, json.JSONDecodeError):
            probe = {}
        proposals = {
            key: meta.get("command")
            for key, meta in (probe.get("proposals") or {}).items()
            if isinstance(meta, dict) and meta.get("safe") and meta.get("command")
        }
        if proposals:
            detected["verify"] = {"value": proposals, "source": "project-type-detection"}

    default_branch = default_base_branch(root)
    ci_scan = scan_ci_workflows(root, default_branch)
    if ci_scan.get("presence") == CI_PRESENCE_SATISFIED:
        detected["ci-stub"] = {"value": ci_scan, "source": "ci-presence"}
    elif (root / STUB_WORKFLOW_REL).is_file():
        detected["ci-stub"] = {"value": {"path": STUB_WORKFLOW_REL.as_posix()}, "source": "ci-stub-file"}

    host = config.get("host") if isinstance(config.get("host"), dict) else {}
    credential_ref = str(host.get("credentialRef") or "").strip()
    project_id = str(config.get("projectId") or "").strip()
    if credential_ref and project_id:
        detected["credentials"] = {
            "value": {"credentialRef": credential_ref, "projectId": project_id},
            "source": "config",
        }

    models = config.get("models") if isinstance(config.get("models"), dict) else {}
    tiers = models.get("tiers") if isinstance(models.get("tiers"), dict) else {}
    if tiers:
        detected["models.tiers"] = {"value": tiers, "source": "config"}

    configured_branch = str(config.get("defaultBaseBranch") or "").strip()
    if configured_branch:
        detected["defaultBaseBranch"] = {"value": configured_branch, "source": "config"}
    elif default_branch:
        detected["defaultBaseBranch"] = {"value": default_branch, "source": "host-default"}

    return detected


def run_priority_zero_interview(
    root: Path,
    *,
    accept_defaults: bool = False,
    decline_surfaces: frozenset[str] | None = None,
    plan_confirmed: bool = False,
    apply_confirmed: bool = False,
    progressive_disclosure: bool = False,
) -> dict[str, Any]:
    """Resolve all five priority-zero surfaces in one run (R24–R27).

    Every surface ends as detected, confirmed, or declined-with-consequence —
    never silently unset.
    """
    decline_surfaces = decline_surfaces or frozenset()
    unknown = sorted(decline_surfaces - set(PRIORITY_ZERO_SURFACES))
    if unknown:
        return {
            "verdict": "fail",
            "error": "unknown-decline-surface",
            "unknownSurfaces": unknown,
        }

    detected_map = _detect_priority_zero_surfaces(root)
    records: list[dict[str, Any]] = []
    for surface in PRIORITY_ZERO_SURFACES:
        if surface in decline_surfaces:
            records.append(record_priority_zero_surface(surface, "declined", source="operator-decline"))
            continue
        hit = detected_map.get(surface)
        if hit is not None:
            records.append(
                record_priority_zero_surface(
                    surface,
                    "detected",
                    value=hit.get("value"),
                    source=str(hit.get("source") or "detected"),
                )
            )
            continue
        if accept_defaults:
            records.append(
                record_priority_zero_surface(
                    surface,
                    "confirmed",
                    value={"acceptedDefault": True},
                    source="accept-defaults",
                )
            )
            continue
        # Non-interactive completeness: record an explicit decline rather than leave unset.
        records.append(
            record_priority_zero_surface(
                surface,
                "declined",
                source="unset-without-confirmation",
            )
        )

    coverage = validate_priority_zero_coverage(records)
    reuse = interview_reuse_bundle(
        root,
        plan_confirmed=plan_confirmed,
        apply_confirmed=apply_confirmed,
    )
    schema = load_config_schema(root)
    priorities = derive_interview_priorities(schema)
    findings = build_findings_report(root)

    payload: dict[str, Any] = {
        "verdict": "pass" if coverage.get("verdict") == "pass" else "fail",
        "action": "interview",
        "priorityZero": coverage.get("surfaces") or records,
        "coverage": {
            "recorded": coverage.get("recorded"),
            "expected": coverage.get("expected"),
            "verdict": coverage.get("verdict"),
            "errors": coverage.get("errors") or [],
        },
        "priorityOne": {
            "keys": priorities.get("priorityOne") or [],
            "inline": True,
        },
        "priorityTwo": {
            "keys": priorities.get("priorityTwo") or [],
            "progressiveDisclosure": True,
            "included": bool(progressive_disclosure),
        },
        "defaultPriorityForNewKeys": priorities.get("defaultPriority"),
        "findings": findings,
        "infrastructure": reuse,
        "secondInterviewEngine": False,
    }
    if coverage.get("verdict") != "pass":
        payload["error"] = "priority-zero-coverage-incomplete"
    return payload


def cmd_interview(root: Path, rest: list[str]) -> int:
    """CLI: resolve priority-zero interview surfaces in one invocation."""
    accept_defaults = "--accept-defaults" in rest
    plan_confirmed = "--plan-confirm" in rest or "--confirm-plan" in rest
    apply_confirmed = "--apply-confirm" in rest or "--confirm-apply" in rest or "--confirm" in rest
    progressive = "--include-priority-two" in rest or "--progressive-disclosure" in rest
    decline: set[str] = set()
    i = 0
    while i < len(rest):
        token = rest[i]
        if token == "--decline" and i + 1 < len(rest):
            decline.add(rest[i + 1])
            i += 2
            continue
        if token.startswith("--decline="):
            decline.add(token.split("=", 1)[1])
            i += 1
            continue
        i += 1
    payload = run_priority_zero_interview(
        root,
        accept_defaults=accept_defaults,
        decline_surfaces=frozenset(decline),
        plan_confirmed=plan_confirmed,
        apply_confirmed=apply_confirmed,
        progressive_disclosure=progressive,
    )
    print(json.dumps(payload, indent=2))
    return 0 if payload.get("verdict") == "pass" else 1


def main(argv: list[str] | None = None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])
    if not args or args[0] in ("-h", "--help"):
        print(
            "usage: sw-configure.py detect|schema-version|shipwright-version|"
            "drift-check|portability-check|findings|write-draft|dry-run|"
            "interview|credential|ci-stub|doctrine",
            file=sys.stderr,
        )
        return 2 if args else 0
    cmd = args[0]
    rest = args[1:]
    root = REPO_ROOT
    config = ""
    accept = False
    write_verify = False
    markdown = False
    integration = "cursor"
    machine_dest = ""
    dist_source = ""
    source_root = ""
    accept_ci_stub = True
    i = 0
    while i < len(rest):
        token = rest[i]
        if token == "--config" and i + 1 < len(rest):
            config = rest[i + 1]
            i += 2
            continue
        if token == "--accept-defaults":
            accept = True
            i += 1
            continue
        if token == "--write-verify":
            write_verify = True
            i += 1
            continue
        if token == "--markdown":
            markdown = True
            i += 1
            continue
        if token == "--propose":
            i += 1
            continue
        if token == "--integration" and i + 1 < len(rest):
            integration = rest[i + 1]
            i += 2
            continue
        if token == "--dest" and i + 1 < len(rest):
            machine_dest = rest[i + 1]
            i += 2
            continue
        if token == "--dist-source" and i + 1 < len(rest):
            dist_source = rest[i + 1]
            i += 2
            continue
        if token == "--source-root" and i + 1 < len(rest):
            source_root = rest[i + 1]
            i += 2
            continue
        if token == "--root" and i + 1 < len(rest):
            root = Path(rest[i + 1]).expanduser().resolve()
            i += 2
            continue
        if token == "--no-ci-stub":
            accept_ci_stub = False
            i += 1
            continue
        i += 1

    if cmd == "detect":
        detect_args = ["--root", str(root)]
        if "--propose" in args:
            detect_args.append("--propose")
        return subprocess.run([sys.executable, str(SCRIPT_DIR / "detect-project-type.py"), *detect_args]).returncode
    if cmd == "schema-version":
        print(schema_version(root))
        return 0
    if cmd == "shipwright-version":
        print(shipwright_version(root))
        return 0
    if cmd == "drift-check":
        return cmd_drift_check(root, config)
    if cmd == "portability-check":
        return cmd_portability_check(root, config)
    if cmd in ("findings", "findings-report"):
        return cmd_findings_report(root, markdown=markdown)
    if cmd == "write-draft":
        out = config or "/tmp/sw-init-draft.json"
        return cmd_write_draft(root, accept=accept, write_verify=write_verify, config=out)
    if cmd == "dry-run":
        return cmd_dry_run(
            root,
            integration=integration,
            machine_dest=Path(machine_dest) if machine_dest else None,
            dist_source=Path(dist_source) if dist_source else None,
            accept_ci_stub=accept_ci_stub,
            source_root=Path(source_root) if source_root else None,
        )
    if cmd == "interview":
        return cmd_interview(root, rest)
    if cmd == "ci-stub":
        subcmd, sub_rest = _credential_argv(rest)
        return cmd_ci_stub(root, subcmd, sub_rest)
    if cmd == "credential":
        subcmd, sub_rest = _credential_argv(rest)
        if not subcmd:
            print(json.dumps({"verdict": "fail", "error": "credential subcommand required"}), file=sys.stderr)
            return 2
        return cmd_credential(root, subcmd, sub_rest)
    if cmd in ("doctrine", "project-doctrine"):
        subcmd, sub_rest = _credential_argv(rest)
        return cmd_doctrine(root, subcmd, sub_rest)
    print(json.dumps({"verdict": "fail", "error": f"unknown command: {cmd}"}), file=sys.stderr)
    return 2


if __name__ == "__main__":
    run_module_main(main)
