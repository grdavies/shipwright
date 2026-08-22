#!/usr/bin/env python3
"""Consent-gated CI stub plan/apply for greenfield init (PRD 324 R5–R7)."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from _sw.cli import run_module_main
from host_lib import default_base_branch
from wave_preflight import (
    CI_PRESENCE_NO_WORKFLOWS,
    CI_PRESENCE_RESTRICTED,
    CI_PRESENCE_SATISFIED,
    scan_ci_workflows,
)

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

STUB_WORKFLOW_REL = Path(".github/workflows/shipwright-ci-stub.yml")
TEMPLATE_REL = Path("core/sw-reference/templates/ci-stub-pull-request.yml")
DECLINE_REL = Path(".cursor/sw-init-ci-stub.json")
CONSENT_MESSAGE = (
    "CI stub apply is consent-gated — re-run with apply --confirm to write the workflow file. "
    "After apply, Shipwright will not rewrite it; edit freely."
)

WireVerify = Literal["off", "on"]


def repo_root(start: Path | None = None) -> Path:
    start = (start or Path.cwd()).resolve()
    import subprocess

    proc = subprocess.run(
        ["git", "-C", str(start), "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
    )
    if proc.returncode == 0 and proc.stdout.strip():
        return Path(proc.stdout.strip())
    return start


def decline_path(root: Path) -> Path:
    return root / DECLINE_REL


def load_decline_record(root: Path) -> dict[str, Any] | None:
    path = decline_path(root)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def record_decline(root: Path, *, reason: str = "operator-decline") -> dict[str, Any]:
    path = decline_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "declined": True,
        "reason": reason,
        "recordedAt": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "surface": "ci-stub",
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return {
        "verdict": "pass",
        "action": "record-decline",
        "declinePath": str(DECLINE_REL),
        **payload,
    }


def template_path(root: Path) -> Path:
    return root / TEMPLATE_REL


def load_template(root: Path) -> str:
    path = template_path(root)
    if not path.is_file():
        raise FileNotFoundError(f"missing CI stub template: {TEMPLATE_REL}")
    return path.read_text(encoding="utf-8")


def render_stub_body(root: Path, *, wire_verify: WireVerify) -> str:
    body = load_template(root)
    if wire_verify != "on":
        return body if body.endswith("\n") else body + "\n"
    verify_block = """
      - name: Shipwright verify gate (explicit opt-in — not default placeholder)
        run: python3 scripts/check-gate.py
"""
    marker = "      - name: Placeholder — replace with your CI steps"
    if marker not in body:
        return body if body.endswith("\n") else body + "\n"
    updated = body.replace(marker, marker + verify_block, 1)
    return updated if updated.endswith("\n") else updated + "\n"


def plan_reason(ci_scan: dict[str, Any], declined: bool) -> str:
    if declined:
        return "declined"
    presence = str(ci_scan.get("presence") or "")
    if presence == CI_PRESENCE_SATISFIED:
        return "satisfied"
    if presence == CI_PRESENCE_RESTRICTED:
        return "restricted-PR-trigger"
    if presence == CI_PRESENCE_NO_WORKFLOWS:
        return "no-workflows"
    return presence or "unknown"


def plan_ci_stub(
    root: Path,
    *,
    wire_verify: WireVerify = "off",
) -> dict[str, Any]:
    root = repo_root(root)
    default_branch = default_base_branch(root)
    ci_scan = scan_ci_workflows(root, default_branch)
    decline = load_decline_record(root)
    declined = bool(decline and decline.get("declined"))
    reason = plan_reason(ci_scan, declined)
    needed = reason in ("no-workflows", "restricted-PR-trigger")
    target = STUB_WORKFLOW_REL
    body = render_stub_body(root, wire_verify=wire_verify) if needed else ""
    payload: dict[str, Any] = {
        "verdict": "pass",
        "action": "plan",
        "needed": needed,
        "reason": reason,
        "targetPath": str(target),
        "defaultBaseBranch": default_branch,
        "ciScan": ci_scan,
        "declined": declined,
        "declinePath": str(DECLINE_REL),
        "wireVerify": wire_verify,
    }
    if decline:
        payload["declineRecord"] = decline
    if needed:
        payload["body"] = body
    if not needed and not declined and reason == "satisfied":
        payload["note"] = "CI presence already satisfied — apply would be a no-op"
    if declined:
        payload["note"] = (
            "Operator declined CI stub seeding; base-preflight should report explicit decline"
        )
    return payload


def apply_ci_stub(
    root: Path,
    *,
    confirm: bool,
    wire_verify: WireVerify = "off",
) -> dict[str, Any]:
    root = repo_root(root)
    if not confirm:
        return {
            "verdict": "fail",
            "action": "apply",
            "error": "confirm-required",
            "message": CONSENT_MESSAGE,
            "remediation": "python3 scripts/init_ci_stub.py apply --confirm",
        }

    plan = plan_ci_stub(root, wire_verify=wire_verify)
    target = root / STUB_WORKFLOW_REL
    if plan.get("declined"):
        return {
            "verdict": "noop",
            "action": "apply",
            "reason": "declined",
            "declinePath": str(DECLINE_REL),
            "message": "CI stub apply skipped — operator decline recorded",
        }
    if not plan.get("needed"):
        return {
            "verdict": "noop",
            "action": "apply",
            "reason": plan.get("reason"),
            "targetPath": str(STUB_WORKFLOW_REL),
            "message": "CI stub not needed — existing workflows satisfy CI presence",
        }
    if target.is_file():
        return {
            "verdict": "noop",
            "action": "apply",
            "reason": "already-present",
            "targetPath": str(STUB_WORKFLOW_REL),
            "message": "Workflow file already exists — preserving operator edits (idempotent no-op)",
        }

    body = str(plan.get("body") or render_stub_body(root, wire_verify=wire_verify))
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body, encoding="utf-8")
    return {
        "verdict": "pass",
        "action": "apply",
        "written": True,
        "targetPath": str(STUB_WORKFLOW_REL),
        "wireVerify": wire_verify,
        "message": (
            f"Wrote {STUB_WORKFLOW_REL} — this file is yours to edit; Shipwright will not rewrite it."
        ),
    }


def cmd_plan(args: argparse.Namespace) -> int:
    payload = plan_ci_stub(
        Path(args.root),
        wire_verify="on" if args.wire_verify else "off",
    )
    print(json.dumps(payload, indent=2))
    if args.body_only:
        body = payload.get("body")
        if body:
            print(body, end="" if str(body).endswith("\n") else "\n")
    return 0


def cmd_apply(args: argparse.Namespace) -> int:
    payload = apply_ci_stub(
        Path(args.root),
        confirm=args.confirm,
        wire_verify="on" if args.wire_verify else "off",
    )
    print(json.dumps(payload, indent=2))
    verdict = payload.get("verdict")
    if verdict == "fail":
        return 2
    return 0


def cmd_decline(args: argparse.Namespace) -> int:
    if not args.confirm:
        print(
            json.dumps(
                {
                    "verdict": "fail",
                    "action": "decline",
                    "error": "confirm-required",
                    "remediation": "python3 scripts/init_ci_stub.py decline --confirm",
                },
                indent=2,
            )
        )
        return 2
    payload = record_decline(Path(args.root), reason=args.reason or "operator-decline")
    print(json.dumps(payload, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Consent-gated CI stub plan/apply")
    parser.add_argument("root", nargs="?", default=".", type=Path)
    sub = parser.add_subparsers(dest="command", required=True)

    plan_p = sub.add_parser("plan", help="Read-only CI stub plan (default safe action)")
    plan_p.add_argument("--wire-verify", action="store_true")
    plan_p.add_argument("--body-only", action="store_true")
    plan_p.set_defaults(func=cmd_plan)

    apply_p = sub.add_parser("apply", help="Apply CI stub when plan says needed")
    apply_p.add_argument("--confirm", action="store_true")
    apply_p.add_argument("--wire-verify", action="store_true")
    apply_p.set_defaults(func=cmd_apply)

    decline_p = sub.add_parser("decline", help="Record explicit operator decline")
    decline_p.add_argument("--confirm", action="store_true")
    decline_p.add_argument("--reason", default="operator-decline")
    decline_p.set_defaults(func=cmd_decline)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    run_module_main(main)
