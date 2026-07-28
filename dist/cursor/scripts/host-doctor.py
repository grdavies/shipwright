#!/usr/bin/env python3
"""Host provider doctor — validate provider, remote, and identity-aware host auth (PRD 080 phase 22)."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from _sw.cli import run_module_main
from credentials.doctor import CREDENTIAL_DOCTOR_CLI, diagnose_host_surface
from host_doctor_lib import probe_ci_status_capability  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="host-doctor.py")
    parser.add_argument("--root", default=None)
    args = parser.parse_args(argv)
    root = Path(args.root).resolve() if args.root else SCRIPT_DIR.parent
    host = root / "scripts" / "host_lib.py"
    resolved = json.loads(subprocess.check_output([sys.executable, str(host), "--root", str(root), "resolve"], text=True))
    warnings: list[str] = []
    checks: list[dict] = []
    provider = resolved.get("provider", "none")
    checks.append({"check": "provider", "status": "ok" if resolved.get("verdict") == "ok" else "fail", "provider": provider})
    if resolved.get("verdict") != "ok":
        warnings.append(resolved.get("error", "unknown_provider"))
    remote = resolved.get("remote", "origin")
    remote_url = resolved.get("remoteUrl")
    if remote_url:
        checks.append({"check": "remote", "status": "ok", "remote": remote, "url": remote_url})
    else:
        checks.append({"check": "remote", "status": "warn", "remote": remote, "message": "remote not configured or missing"})
        warnings.append("missing-remote")

    host_identity = diagnose_host_surface(root)
    identity_status = "ok"
    if host_identity.get("requiredOperationVerdict") == "fail":
        identity_status = "fail"
        warnings.append("host-credential-failed")
    elif host_identity.get("requiredOperationVerdict") == "skipped":
        identity_status = "skipped"
    checks.append(
        {
            "check": "host-identity",
            "status": identity_status,
            "principal": host_identity.get("principal"),
            "requiredOperationVerdict": host_identity.get("requiredOperationVerdict"),
            "repositoryAccess": host_identity.get("repositoryAccess"),
            "credentialRef": host_identity.get("credentialRef"),
            "credentialDoctor": host_identity.get("credentialDoctor"),
            "failure": host_identity.get("failure"),
        }
    )

    rate = resolved.get("rateLimit") or {}
    checks.append({"check": "rateLimit", "status": "ok", "config": rate})

    ci_status = probe_ci_status_capability(root)
    checks.append(
        {
            "check": "ciStatus",
            "status": "ok" if ci_status.get("capability") == "capable" else "warn",
            "capability": ci_status.get("capability"),
            "reasonCode": ci_status.get("reasonCode"),
            "provider": ci_status.get("provider"),
        }
    )
    if ci_status.get("capability") == "denied":
        warnings.append("ci-status-denied")
    elif ci_status.get("capability") == "inconclusive":
        warnings.append("ci-status-inconclusive")

    verdict = "fail" if any(c.get("status") == "fail" for c in checks) else ("degraded" if warnings else "ok")
    print(
        json.dumps(
            {
                "verdict": verdict,
                "provider": provider,
                "warnings": warnings,
                "checks": checks,
                "ciStatus": ci_status,
                "credentialDoctor": f"{CREDENTIAL_DOCTOR_CLI} --root {root}",
                "migration": {
                    "deferCredentialReporting": True,
                    "credentialDoctorSurface": f"{CREDENTIAL_DOCTOR_CLI} --root {root}",
                },
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    run_module_main(main)
