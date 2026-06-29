#!/usr/bin/env python3
"""Phase-mode PR base resolution and superseded PR close (PRD 026 R20-R22)."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from host_invoke import host_verb
from host_lib import phase_mode_active


def integration_branch(root: Path) -> str | None:
    """Sole authority: durable deliver state; SW_INTEGRATION_BRANCH is harness-only (R4)."""
    state_branch: str | None = None
    try:
        from wave_state import load_deliver_state

        state = load_deliver_state(root)
        target = state.get("target") or {}
        raw = target.get("branch")
        if isinstance(raw, str) and raw.strip():
            state_branch = raw.strip()
    except ImportError:
        state_branch = None
    env_branch = os.environ.get("SW_INTEGRATION_BRANCH", "").strip()
    if env_branch and state_branch and env_branch != state_branch:
        return None  # caller maps to fail-closed via resolve_phase_pr_base
    if state_branch:
        return state_branch
    if env_branch:
        return env_branch
    return None


def integration_branch_or_fail(root: Path) -> str:
    state_branch: str | None = None
    try:
        from wave_state import load_deliver_state

        state = load_deliver_state(root)
        target = state.get("target") or {}
        raw = target.get("branch")
        if isinstance(raw, str) and raw.strip():
            state_branch = raw.strip()
    except ImportError:
        state_branch = None
    env_branch = os.environ.get("SW_INTEGRATION_BRANCH", "").strip()
    if env_branch and state_branch and env_branch != state_branch:
        from wave_state import fail

        fail(
            "integration-branch-env-state-mismatch",
            exit_code=20,
            envBranch=env_branch,
            stateBranch=state_branch,
        )
    branch = state_branch or env_branch
    if not branch:
        from wave_state import fail

        fail("integration-branch-missing", exit_code=20)
    return branch


def resolve_phase_pr_base(root: Path, explicit_base: str | None = None) -> dict[str, Any]:
    integration = integration_branch(root)
    active = phase_mode_active()
    base = (explicit_base or "").strip() or None
    if not active:
        return {"verdict": "ok", "phaseMode": False, "base": base, "integrationBranch": integration, "enforced": False}
    if not integration:
        return {"verdict": "fail", "error": "integration-branch-missing", "phaseMode": True,
                "message": "SW_PHASE_MODE set but deliver integration branch not found"}
    if base and base != integration:
        return {"verdict": "fail", "error": "phase-pr-base-mismatch", "phaseMode": True,
                "base": base, "integrationBranch": integration,
                "message": f"phase-mode PR base must be {integration!r}, got {base!r}"}
    return {"verdict": "ok", "phaseMode": True, "base": integration, "integrationBranch": integration, "enforced": True}


def enforce_phase_pr_base(root: Path, base: str) -> dict[str, Any]:
    resolved = resolve_phase_pr_base(root, base)
    if resolved.get("verdict") != "ok":
        return resolved
    if resolved.get("enforced"):
        resolved["base"] = resolved["integrationBranch"]
    return resolved


def _phase_branch_for_slug(state: dict[str, Any], phase_slug: str) -> str | None:
    for meta in (state.get("phases") or {}).values():
        if meta.get("slug") == phase_slug:
            branch = meta.get("branch")
            return str(branch) if branch else None
    return None


def _green_merged_slugs(state: dict[str, Any]) -> set[str]:
    terminal = {"green-merged", "teardown-pending", "teardown-complete"}
    slugs: set[str] = set()
    for meta in (state.get("phases") or {}).values():
        if meta.get("status") in terminal and meta.get("slug"):
            slugs.add(str(meta["slug"]))
    return slugs


def close_superseded_phase_prs(root: Path, state: dict[str, Any], *, phase_slug: str | None = None) -> dict[str, Any]:
    allowed = _green_merged_slugs(state)
    if phase_slug:
        if phase_slug not in allowed:
            return {"verdict": "skip", "reason": "phase-not-green-merged", "phase": phase_slug, "closed": []}
        slugs = {phase_slug}
    else:
        slugs = allowed
    closed, skipped, errors = [], [], []
    for slug in sorted(slugs):
        branch = _phase_branch_for_slug(state, slug)
        if not branch:
            skipped.append({"phaseSlug": slug, "reason": "missing-branch"})
            continue
        listed = host_verb(root, "pr-list", head=branch, state="open", limit="10")
        if listed.get("verdict") != "ok":
            errors.append({"phaseSlug": slug, "branch": branch, "reason": listed.get("reason", "pr-list-failed")})
            continue
        items = listed.get("data") or []
        if not isinstance(items, list) or not items:
            skipped.append({"phaseSlug": slug, "branch": branch, "reason": "no-open-pr"})
            continue
        for pr in items:
            if not isinstance(pr, dict) or pr.get("number") is None:
                continue
            number = pr["number"]
            out = host_verb(root, "pr-close", number=str(number))
            entry = {"phaseSlug": slug, "branch": branch, "number": number, "url": pr.get("url"), "verdict": out.get("verdict")}
            if out.get("verdict") == "ok":
                closed.append(entry)
            else:
                errors.append({**entry, "reason": out.get("reason", "pr-close-failed")})
    return {"verdict": "ok" if not errors else "partial", "closed": closed, "skipped": skipped, "errors": errors}


def _phase_meta_for_slug(state: dict[str, Any], phase_slug: str) -> dict[str, Any] | None:
    for meta in (state.get("phases") or {}).values():
        if meta.get("slug") == phase_slug:
            return meta if isinstance(meta, dict) else None
    return None


def close_prs_wrong_base(
    root: Path,
    *,
    head: str,
    integration: str,
) -> dict[str, Any]:
    """Close open PRs on head whose base ≠ integration (R4)."""
    listed = host_verb(root, "pr-list", head=head, state="open", limit="20")
    if listed.get("verdict") != "ok":
        return {"verdict": "fail", "reason": listed.get("reason", "pr-list-failed")}
    closed: list[dict[str, Any]] = []
    kept: list[dict[str, Any]] = []
    for pr in listed.get("data") or []:
        if not isinstance(pr, dict):
            continue
        base = pr.get("baseRefName") or pr.get("base")
        if base == integration:
            kept.append(pr)
            continue
        number = pr.get("number")
        if number is None:
            continue
        out = host_verb(root, "pr-close", number=str(number))
        closed.append({"number": number, "base": base, "verdict": out.get("verdict")})
    return {"verdict": "ok", "closed": closed, "kept": kept}


def canonical_pr_on_base(prs: list[dict[str, Any]], integration: str) -> dict[str, Any] | None:
    """Select canonical PR by integration-base identity (R5)."""
    matches = [
        pr
        for pr in prs
        if isinstance(pr, dict)
        and (pr.get("baseRefName") or pr.get("base")) == integration
    ]
    if not matches:
        return None
    if len(matches) == 1:
        return matches[0]
    matches.sort(key=lambda p: str(p.get("createdAt") or p.get("number") or ""))
    return matches[0]


def persist_open_pr_number(
    root: Path,
    *,
    phase_slug: str,
    number: int | str,
) -> None:
    from wave_state import load_deliver_state, save_deliver_state

    state = load_deliver_state(root)
    for meta in (state.get("phases") or {}).values():
        if meta.get("slug") == phase_slug:
            meta["openPrNumber"] = int(number)
            break
    save_deliver_state(root, state)


def recorded_open_pr(state: dict[str, Any], phase_slug: str) -> int | None:
    meta = _phase_meta_for_slug(state, phase_slug)
    if not meta:
        return None
    raw = meta.get("openPrNumber")
    return int(raw) if raw is not None else None


def create_or_reuse_phase_pr(
    root: Path,
    *,
    phase_slug: str,
    head: str,
    title: str,
    body: str,
) -> dict[str, Any]:
    """Idempotent phase PR under per-head lease (R2/R3/R4)."""
    from wave_state import fail, load_deliver_state

    integration = integration_branch_or_fail(root)
    resolved = enforce_phase_pr_base(root, integration)
    if resolved.get("verdict") != "ok":
        return resolved
    base = str(resolved["base"])

    from wave_lock import acquire_ship_lease, release_ship_lease

    acquire_args = ["--integration", integration, "--phase-branch", head]
    lease = acquire_ship_lease(root, acquire_args)
    if lease.get("verdict") != "pass":
        return lease
    owned_lease = not lease.get("reentrant")

    try:
        close_prs_wrong_base(root, head=head, integration=base)
        state = load_deliver_state(root)
        recorded = recorded_open_pr(state, phase_slug)
        if recorded is not None:
            listed = host_verb(root, "pr-list", head=head, base=base, state="open", limit="10")
            items = listed.get("data") if listed.get("verdict") == "ok" else []
            if isinstance(items, list):
                for pr in items:
                    if isinstance(pr, dict) and pr.get("number") == recorded:
                        return {"verdict": "ok", "reused": True, "pr": pr, "number": recorded}
            return {
                "verdict": "fail",
                "error": "duplicate-pr-recorded-open",
                "openPrNumber": recorded,
                "route": "supersede",
            }

        listed = host_verb(root, "pr-list", head=head, base=base, state="open", limit="10")
        if listed.get("verdict") != "ok":
            return {"verdict": "fail", "reason": listed.get("reason", "pr-list-failed")}
        items = listed.get("data") if isinstance(listed.get("data"), list) else []
        canonical = canonical_pr_on_base(items, base)
        if canonical and canonical.get("number") is not None:
            persist_open_pr_number(root, phase_slug=phase_slug, number=canonical["number"])
            return {"verdict": "ok", "reused": True, "pr": canonical, "number": canonical["number"]}

        out = host_verb(root, "pr-create", title=title, body=body, head=head, base=base)
        if out.get("verdict") != "ok":
            return {"verdict": "fail", "reason": out.get("reason", "pr-create-failed")}
        data = out.get("data") if isinstance(out.get("data"), dict) else {}
        number = data.get("number")
        if number is None:
            fail("pr-create missing number", exit_code=30)
        persist_open_pr_number(root, phase_slug=phase_slug, number=number)
        return {"verdict": "ok", "created": True, "pr": data, "number": number}
    finally:
        if owned_lease:
            release_ship_lease(root, acquire_args)


def phase_green_merged_branch(root: Path, branch: str) -> bool:
    try:
        from cleanup_lib import load_deliver_state
    except ImportError:
        return False
    terminal = {"green-merged", "teardown-pending", "teardown-complete"}
    for meta in (load_deliver_state(root).get("phases") or {}).values():
        if meta.get("branch") == branch and meta.get("status") in terminal:
            return True
    return False


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="Phase-mode PR helpers")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    sub = parser.add_subparsers(dest="cmd", required=True)
    resolve = sub.add_parser("resolve-base"); resolve.add_argument("--base", default="")
    enforce = sub.add_parser("enforce-base"); enforce.add_argument("--base", required=True)
    close = sub.add_parser("close-superseded"); close.add_argument("--phase-slug", default="")
    sub.add_parser("integration-branch")
    args = parser.parse_args()
    root = args.root.resolve()
    if args.cmd == "resolve-base":
        out = resolve_phase_pr_base(root, args.base or None)
    elif args.cmd == "enforce-base":
        out = enforce_phase_pr_base(root, args.base)
    elif args.cmd == "close-superseded":
        from wave_state import load_deliver_state
        out = close_superseded_phase_prs(root, load_deliver_state(root), phase_slug=args.phase_slug.strip() or None)
    else:
        out = {"verdict": "ok", "branch": integration_branch(root)}
    print(json.dumps(out, indent=2))
    sys.exit(0 if out.get("verdict") in ("ok", "skip", "partial") else 1)

if __name__ == "__main__":
    main()
