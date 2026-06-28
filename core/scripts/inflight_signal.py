#!/usr/bin/env python3
"""Committed in-flight signal writer for planning INDEX inFlight region (PRD 032 R1–R2, R11, R17–R18)."""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import planning_index_gen as pig  # noqa: E402
import planning_paths  # noqa: E402

TUPLE_FIELDS = ("runId", "branch", "leaseEpoch")
OPAQUE_FIELD = "branchToken"
TABLE_HEADER = "| unitId | runId | branch | branchToken | leaseEpoch |"
TABLE_SEP = "| --- | --- | --- | --- | --- |"
ROW_RE = re.compile(
    r"^\|\s*(?P<unit>[^|]+?)\s*\|\s*(?P<runId>[^|]+?)\s*\|\s*(?P<branch>[^|]+?)\s*\|\s*(?P<branchToken>[^|]*?)\s*\|\s*(?P<leaseEpoch>[^|]+?)\s*\|$"
)
SECRET_PATTERNS = (
    re.compile(r"(?i)(api[_-]?key|secret|password|token)\s*[:=]"),
    re.compile(r"-----BEGIN [A-Z ]+-----"),
)


@dataclass(frozen=True)
class InFlightTuple:
    unit_id: str
    run_id: str
    branch: str
    lease_epoch: int
    branch_token: str | None = None

    def to_row(self) -> str:
        token = self.branch_token or ""
        branch = self.branch if not self.branch_token else ""
        return (
            f"| {self.unit_id} | {self.run_id} | {branch} | {token} | {self.lease_epoch} |"
        )


def emit(obj: dict[str, Any], exit_code: int = 0) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))
    sys.exit(exit_code)


def fail(error: str, exit_code: int = 2, **extra: Any) -> None:
    emit({"verdict": "fail", "error": error, **extra}, exit_code)


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def git_root(start: Path | None = None) -> Path:
    return planning_paths.git_root(start)


def index_path(root: Path) -> Path:
    dirs = planning_paths.load_planning_dirs(root)
    return git_root(root) / dirs.planning / "INDEX.md"


def lease_registry_path(root: Path) -> Path:
    path = git_root(root) / ".cursor" / "sw-deliver-runs" / "index.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def resolve_state_path(root: Path, target_branch: str) -> Path:
    from wave_state import resolve_state_path as _resolve

    return _resolve(root, target=target_branch)


def parse_inflight_body(body: str) -> dict[str, InFlightTuple]:
    tuples: dict[str, InFlightTuple] = {}
    for line in body.splitlines():
        line = line.strip()
        if not line or line.startswith("| ---"):
            continue
        m = ROW_RE.match(line)
        if not m:
            continue
        unit = m.group("unit").strip()
        run_id = m.group("runId").strip()
        branch = m.group("branch").strip()
        branch_token = m.group("branchToken").strip() or None
        try:
            lease_epoch = int(m.group("leaseEpoch").strip())
        except ValueError:
            continue
        if not unit or not run_id:
            continue
        tuples[unit] = InFlightTuple(
            unit_id=unit,
            run_id=run_id,
            branch=branch,
            lease_epoch=lease_epoch,
            branch_token=branch_token,
        )
    return tuples


def render_inflight_body(tuples: dict[str, InFlightTuple]) -> str:
    if not tuples:
        return "\n"
    lines = [TABLE_HEADER, TABLE_SEP]
    for unit_id in sorted(tuples):
        lines.append(tuples[unit_id].to_row())
    return "\n".join(lines) + "\n"


def read_inflight_region(root: Path) -> tuple[str, dict[str, InFlightTuple]]:
    path = index_path(root)
    if not path.is_file():
        return "", {}
    regions = pig.parse_regions(path.read_text(encoding="utf-8"))
    body = regions.inFlight
    return body, parse_inflight_body(body)


def opaque_branch_token(branch: str) -> str:
    digest = hashlib.sha256(branch.encode("utf-8")).hexdigest()[:16]
    return f"sha256:{digest}"


def scan_tuple_for_secrets(tuple_: InFlightTuple) -> list[str]:
    hits: list[str] = []
    for value in (tuple_.run_id, tuple_.branch, tuple_.branch_token or ""):
        if not value:
            continue
        for pat in SECRET_PATTERNS:
            if pat.search(value):
                hits.append(value)
    return hits


def load_lease_registry(root: Path) -> dict[str, Any]:
    path = lease_registry_path(root)
    if not path.is_file():
        return {"updatedAt": utc_now(), "leases": {}, "runs": []}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"updatedAt": utc_now(), "leases": {}, "runs": []}


def save_lease_registry(root: Path, registry: dict[str, Any]) -> None:
    registry["updatedAt"] = utc_now()
    path = lease_registry_path(root)
    path.write_text(json.dumps(registry, indent=2) + "\n", encoding="utf-8")
    os.chmod(path, 0o600)


def lease_is_live(root: Path, registry: dict[str, Any], run_id: str) -> bool:
    lease = (registry.get("leases") or {}).get(run_id)
    if not isinstance(lease, dict):
        return False
    if lease.get("releasedAt"):
        return False
    state_path = lease.get("statePath")
    if isinstance(state_path, str):
        sp = root / state_path
        if sp.is_file():
            try:
                state = json.loads(sp.read_text(encoding="utf-8"))
                if state.get("verdict") == "running":
                    return True
            except json.JSONDecodeError:
                pass
    return lease.get("live", False) is True


def append_override_audit(
    root: Path,
    *,
    target_branch: str,
    kind: str,
    reason: str,
    actor: str | None = None,
) -> None:
    state_path = resolve_state_path(root, target_branch)
    if not state_path.is_file():
        fail(f"deliver state not found for audit: {state_path}")
    state = json.loads(state_path.read_text(encoding="utf-8"))
    log = state.setdefault("overrideAudit", [])
    if not isinstance(log, list):
        log = []
        state["overrideAudit"] = log
    log.append(
        {
            "kind": kind,
            "reason": reason,
            "who": actor or os.environ.get("USER", "unknown"),
            "when": utc_now(),
        }
    )
    state["updatedAt"] = utc_now()
    state_path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")


def write_region(root: Path, body: str, *, dry_run: bool = False) -> None:
    path = index_path(root)
    existing = path.read_text(encoding="utf-8") if path.is_file() else None
    content = pig.read_merge_write(existing, writer="inFlight", new_region_body=body)
    if dry_run:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    pig.write_index(root, content)


def ensure_run_id(state: dict[str, Any]) -> str:
    run_id = state.get("runId")
    if isinstance(run_id, str) and run_id.strip():
        return run_id.strip()
    run_id = f"deliver-{uuid.uuid4().hex[:12]}"
    state["runId"] = run_id
    return run_id


def unit_id_from_target(target: dict[str, Any]) -> str:
    slug = str(target.get("slug") or "").strip()
    if not slug:
        fail("target.slug required for in-flight signal")
    return slug


def cmd_write(root: Path, args: list[str]) -> None:
    if "--target" not in args:
        fail("--target required")
    target_branch = args[args.index("--target") + 1]
    takeover = "--takeover" in args
    takeover_reason = None
    if takeover:
        if "--takeover-reason" not in args:
            fail("--takeover requires --takeover-reason")
        takeover_reason = args[args.index("--takeover-reason") + 1]
    opaque = "--opaque-branch" in args
    dry_run = "--dry-run" in args

    state_path = resolve_state_path(root, str(target_branch))
    if not state_path.is_file():
        fail(f"deliver state missing: {state_path}")
    state = json.loads(state_path.read_text(encoding="utf-8"))
    target = state.get("target") or {}
    unit_id = unit_id_from_target(target)
    run_id = ensure_run_id(state)
    branch = str(target.get("branch") or target_branch)
    state_path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")

    registry = load_lease_registry(root)
    _, existing = read_inflight_region(root)
    prior = existing.get(unit_id)
    lease_epoch = (prior.lease_epoch + 1) if prior else 1

    if prior and prior.run_id != run_id:
        if lease_is_live(root, registry, prior.run_id) and not takeover:
            fail(
                "in-flight tuple names a different live run-id; pass --takeover",
                exit_code=20,
                runId=prior.run_id,
                branch=prior.branch,
            )
        if takeover:
            append_override_audit(
                root,
                target_branch=str(target_branch),
                kind="takeover",
                reason=str(takeover_reason),
            )

    if prior and prior.run_id == run_id and prior.lease_epoch >= lease_epoch:
        lease_epoch = prior.lease_epoch + 1

    branch_token = opaque_branch_token(branch) if opaque else None
    tuple_ = InFlightTuple(
        unit_id=unit_id,
        run_id=run_id,
        branch="" if branch_token else branch,
        lease_epoch=lease_epoch,
        branch_token=branch_token,
    )
    secret_hits = scan_tuple_for_secrets(tuple_)
    if secret_hits:
        fail("tuple rejected: secret-like material", hits=secret_hits)

    leases = registry.setdefault("leases", {})
    leases[run_id] = {
        "unitId": unit_id,
        "branch": branch,
        "statePath": str(state_path.relative_to(git_root(root))),
        "acquiredAt": utc_now(),
        "live": True,
    }
    save_lease_registry(root, registry)

    new_map = dict(existing)
    new_map[unit_id] = tuple_
    body = render_inflight_body(new_map)
    write_region(root, body, dry_run=dry_run)

    emit(
        {
            "verdict": "pass",
            "action": "inflight-write",
            "unitId": unit_id,
            "runId": run_id,
            "branch": branch,
            "leaseEpoch": lease_epoch,
            "opaque": bool(branch_token),
            "dryRun": dry_run,
        }
    )


def cmd_read(root: Path, args: list[str]) -> None:
    unit_id = args[args.index("--unit") + 1] if "--unit" in args else None
    _, tuples = read_inflight_region(root)
    if unit_id:
        t = tuples.get(unit_id)
        if not t:
            emit({"verdict": "pass", "action": "inflight-read", "unitId": unit_id, "tuple": None})
        emit(
            {
                "verdict": "pass",
                "action": "inflight-read",
                "unitId": unit_id,
                "tuple": {
                    "runId": t.run_id,
                    "branch": t.branch,
                    "branchToken": t.branch_token,
                    "leaseEpoch": t.lease_epoch,
                },
            }
        )
    emit(
        {
            "verdict": "pass",
            "action": "inflight-read-all",
            "tuples": {
                k: {
                    "runId": v.run_id,
                    "branch": v.branch,
                    "branchToken": v.branch_token,
                    "leaseEpoch": v.lease_epoch,
                }
                for k, v in tuples.items()
            },
        }
    )


def cmd_clear(root: Path, args: list[str]) -> None:
    unit_id = args[args.index("--unit") + 1] if "--unit" in args else None
    if not unit_id:
        fail("--unit required")
    dry_run = "--dry-run" in args
    _, existing = read_inflight_region(root)
    if unit_id not in existing:
        emit({"verdict": "pass", "action": "inflight-clear", "unitId": unit_id, "cleared": False})
    cleared = existing.pop(unit_id)
    registry = load_lease_registry(root)
    lease = (registry.get("leases") or {}).get(cleared.run_id)
    if isinstance(lease, dict):
        lease["releasedAt"] = utc_now()
        lease["live"] = False
    save_lease_registry(root, registry)
    write_region(root, render_inflight_body(existing), dry_run=dry_run)
    emit({"verdict": "pass", "action": "inflight-clear", "unitId": unit_id, "cleared": True})


def cmd_override(root: Path, args: list[str]) -> None:
    if "--target" not in args or "--kind" not in args or "--reason" not in args:
        fail("--target --kind --reason required")
    target = args[args.index("--target") + 1]
    kind = args[args.index("--kind") + 1]
    reason = args[args.index("--reason") + 1]
    if kind not in ("takeover", "handoff", "override"):
        fail(f"invalid override kind: {kind}")
    append_override_audit(root, target_branch=target, kind=kind, reason=reason)
    emit({"verdict": "pass", "action": "inflight-override-audit", "kind": kind})


def run_secret_scan(root: Path, payload: str) -> None:
    proc = subprocess.run(
        [str(root / "scripts" / "secret-scan.sh"), "--stdin"],
        input=payload,
        text=True,
        capture_output=True,
        cwd=str(git_root(root)),
    )
    if proc.returncode != 0:
        fail("secret-scan rejected tuple payload", stderr=proc.stderr.strip())


def main(argv: list[str] | None = None) -> None:
    args = list(argv if argv is not None else sys.argv[1:])
    if len(args) < 2:
        fail("usage: inflight_signal.py <repo-root> <command> ...")
    root = Path(args[0]).resolve()
    cmd_args = args[2:]
    commands = {
        "write": lambda: cmd_write(root, cmd_args),
        "read": lambda: cmd_read(root, cmd_args),
        "clear": lambda: cmd_clear(root, cmd_args),
        "override-audit": lambda: cmd_override(root, cmd_args),
    }
    handler = commands.get(args[1])
    if not handler:
        fail(f"unknown command: {args[1]}")
    handler()


if __name__ == "__main__":
    main()
