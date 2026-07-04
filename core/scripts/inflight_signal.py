#!/usr/bin/env python3
"""Committed in-flight signal writer for planning INDEX inFlight region (PRD 032 R1/R2/R11/R17/R18)."""
from __future__ import annotations

import getpass
import json
import os
import re
import socket
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import planning_index_gen as pig  # noqa: E402
import planning_paths  # noqa: E402
import planning_visibility as pv  # noqa: E402
from host_lib import load_workflow_config  # noqa: E402
from secret_scan import load_allowlist, scan_text  # noqa: E402
from wave_state import (  # noqa: E402
    enumerate_scoped_runs,
    load_deliver_state,
    resolve_state_path,
)
from wave_json_io import write_json  # noqa: E402

UNIT_HEADER_RE = re.compile(r"^([a-z][a-z0-9-]*):$")
ALLOWED_FIELDS = frozenset({"run-id", "branch", "branch-token", "epoch"})
FORBIDDEN_STATUS_TOKENS = frozenset(
    {"in-progress", "not-started", "complete", "proposed", "planned", "status:"}
)
LIFECYCLE_FIELD_RE = re.compile(r"^\s*status\s*:", re.IGNORECASE)
BODY_FIELD_RE = re.compile(r"^\s*(body|content|secret)\s*:", re.IGNORECASE)
TERMINAL_VERDICTS = frozenset({"complete", "blocked", "halted", "terminal", "merged"})


@dataclass(frozen=True)
class InflightTuple:
    run_id: str
    epoch: int
    branch: str | None = None
    branch_token: str | None = None

    def validate_shape(self) -> None:
        if not self.run_id or not self.run_id.strip():
            raise ValueError("run-id required")
        if self.epoch < 1:
            raise ValueError("epoch must be >= 1")
        if self.branch and self.branch_token:
            raise ValueError("branch and branch-token are mutually exclusive")
        if not self.branch and not self.branch_token:
            raise ValueError("branch or branch-token required")

    def render_lines(self) -> list[str]:
        self.validate_shape()
        lines = [f"run-id: {self.run_id}", f"epoch: {self.epoch}"]
        if self.branch_token:
            lines.append(f"branch-token: {self.branch_token}")
        else:
            lines.append(f"branch: {self.branch}")
        return lines


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def emit(obj: dict[str, Any], exit_code: int = 0) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))
    sys.exit(exit_code)


def fail(error: str, exit_code: int = 2, **extra: Any) -> None:
    emit({"verdict": "fail", "error": error, **extra}, exit_code)


def parse_kv(args: list[str], flag: str, default: str | None = None) -> str | None:
    if flag in args:
        i = args.index(flag)
        return args[i + 1] if i + 1 < len(args) else default
    return default


def has_flag(args: list[str], flag: str) -> bool:
    return flag in args


def actor_id() -> str:
    user = getpass.getuser()
    host = socket.gethostname()
    return f"{user}@{host}"


def unit_visibility(root: Path, unit_id: str) -> str:
    """Resolve visibility for inFlight redaction (PRD 034 R12 / 032 R13 handoff)."""
    cfg = load_workflow_config(root)
    for unit in pig.discover_units(root):
        if unit.id == unit_id:
            fm = pig.unit_frontmatter_dict(unit)
            return pv.resolve_unit_visibility(fm, cfg)["visibility"]
    return "private"


def redact_tuple_for_visibility(root: Path, unit_id: str, tup: InflightTuple) -> InflightTuple:
    vis = unit_visibility(root, unit_id)
    payload: dict[str, Any] = {
        "runId": tup.run_id,
        "epoch": tup.epoch,
    }
    if tup.branch_token:
        payload["branchToken"] = tup.branch_token
    elif tup.branch:
        payload["branch"] = tup.branch
    red = pv.redact_inflight_tuple(payload, vis)
    return InflightTuple(
        run_id=str(red.get("runId", tup.run_id)),
        epoch=int(red.get("epoch", tup.epoch)),
        branch=red.get("branch") if isinstance(red.get("branch"), str) else None,
        branch_token=red.get("branchToken") if isinstance(red.get("branchToken"), str) else None,
    )


def parse_region_body(body: str) -> dict[str, InflightTuple]:
    """Parse inFlight region into unit-id → tuple map."""
    tuples: dict[str, InflightTuple] = {}
    current_unit: str | None = None
    fields: dict[str, str] = {}

    def flush() -> None:
        nonlocal fields, current_unit
        if not fields.get("run-id"):
            fields = {}
            return
        unit_key = current_unit or "__default__"
        epoch_raw = fields.get("epoch", "1")
        try:
            epoch = int(epoch_raw)
        except ValueError as exc:
            raise ValueError(f"invalid epoch: {epoch_raw}") from exc
        tuples[unit_key] = InflightTuple(
            run_id=fields["run-id"].strip(),
            epoch=epoch,
            branch=fields.get("branch"),
            branch_token=fields.get("branch-token"),
        )
        fields = {}

    for raw in body.splitlines():
        line = raw.rstrip()
        if not line.strip():
            flush()
            current_unit = None
            continue
        header = UNIT_HEADER_RE.match(line.strip())
        if header:
            flush()
            current_unit = header.group(1)
            continue
        if LIFECYCLE_FIELD_RE.match(line) or BODY_FIELD_RE.match(line):
            raise ValueError(f"forbidden field in inFlight tuple: {line.strip()}")
        lowered = line.strip().lower()
        for token in FORBIDDEN_STATUS_TOKENS:
            if token in lowered and not lowered.startswith("run-id:"):
                raise ValueError(f"lifecycle status must not appear in tuple: {line.strip()}")
        if ":" not in line:
            raise ValueError(f"malformed inFlight line: {line}")
        key, _, val = line.partition(":")
        key = key.strip()
        if key not in ALLOWED_FIELDS:
            raise ValueError(f"unknown inFlight field: {key}")
        fields[key] = val.strip()
    flush()
    return tuples


def render_region_body(tuples: dict[str, InflightTuple]) -> str:
    if not tuples:
        return "\n"
    blocks: list[str] = []
    for unit_id in sorted(tuples.keys()):
        tup = tuples[unit_id]
        tup.validate_shape()
        lines = tup.render_lines()
        if unit_id != "__default__":
            blocks.append(f"{unit_id}:")
            blocks.extend(lines)
        else:
            blocks.extend(lines)
        blocks.append("")
    return "\n".join(blocks).rstrip() + "\n"


def validate_tuple_text(text: str, *, path: str | None = None) -> None:
    """Fail-closed validation: metadata only, no secrets (R18)."""
    for line in text.splitlines():
        if LIFECYCLE_FIELD_RE.match(line) or BODY_FIELD_RE.match(line):
            fail(f"tuple must not carry body or lifecycle fields: {line.strip()}", exit_code=1)
        lowered = line.strip().lower()
        if "in-progress" in lowered and not lowered.startswith("run-id:"):
            fail("lifecycle in-progress must not appear in tuple", exit_code=1)
    root = pig.index_path(Path.cwd())
    try:
        root = planning_paths.git_root()
    except planning_paths.PathEscapeError:
        pass
    allowlist = load_allowlist(root if root.is_dir() else Path.cwd())
    findings = scan_text(text, allowlist=allowlist, path=path)
    if findings:
        fail(
            "tuple would carry secret material",
            exit_code=1,
            findings=[{"pattern": f.pattern, "line": f.line_no} for f in findings],
        )
    try:
        parse_region_body(text)
    except ValueError as exc:
        fail(str(exc), exit_code=1)


def read_tuples(root: Path) -> dict[str, InflightTuple]:
    path = pig.index_path(root)
    if not path.is_file():
        return {}
    try:
        regions = pig.parse_regions(path.read_text(encoding="utf-8"))
    except ValueError:
        # Pre-cutover repos may point planningDir at a legacy INDEX without dual-region markers.
        return {}
    try:
        return parse_region_body(regions.inFlight)
    except ValueError as exc:
        fail(f"corrupt inFlight region: {exc}")


def write_tuples(root: Path, tuples: dict[str, InflightTuple], *, dry_run: bool = False) -> str:
    body = render_region_body(tuples)
    validate_tuple_text(body, path=str(pig.index_rel(root)))
    path = pig.index_path(root)
    existing = path.read_text(encoding="utf-8") if path.is_file() else None
    content = pig.read_merge_write(existing, writer="deliver", new_region_body=body)
    if not dry_run:
        pig.write_index(root, content)
    return body


def prd_unit_id_from_state(state: dict[str, Any], task_list: str | None = None) -> str | None:
    prd = state.get("prd_number")
    raw = task_list or state.get("source_task_list") or ""
    if raw:
        m = re.search(r"docs/prds/(\d+)-([^/]+)/", str(raw).replace("\\", "/"))
        if m:
            return f"prd-{m.group(1)}-{m.group(2)}"
    if prd:
        slug = state.get("prd_slug")
        if slug:
            return f"prd-{prd}-{slug}"
        return f"prd-{prd}"
    return None


def run_id_from_slug(slug: str) -> str:
    return f"deliver-{slug}"


def state_slug_from_path(path: Path) -> str | None:
    name = path.name
    if name.startswith("sw-deliver-state.") and name.endswith(".json"):
        return name.removeprefix("sw-deliver-state.").removesuffix(".json")
    return None


def resolve_run_context(
    root: Path, args: list[str], state: dict[str, Any] | None = None
) -> tuple[dict[str, Any], Path, str, str]:
    target = parse_kv(args, "--target")
    task_list = parse_kv(args, "--task-list")
    if state is None:
        state = load_deliver_state(root, target=target, task_list=task_list)
    state_path = resolve_state_path(root, target=target, task_list=task_list, state_hint=state)
    slug = state_slug_from_path(state_path) or parse_kv(args, "--slug") or "default"
    unit_id = parse_kv(args, "--unit") or prd_unit_id_from_state(state, task_list)
    if not unit_id:
        fail("cannot resolve planning unit id (--unit or prd_number/source_task_list required)")
    assert unit_id is not None
    return state, state_path, slug, unit_id


def persist_state(state_path: Path, state: dict[str, Any]) -> None:
    state["updatedAt"] = utc_now()
    state_path.parent.mkdir(parents=True, exist_ok=True)
    write_json(state_path, state)


def append_override_audit(
    state: dict[str, Any],
    *,
    action: str,
    why: str,
    prior_run_id: str | None = None,
) -> None:
    log = state.setdefault("overrideAudit", [])
    if not isinstance(log, list):
        log = []
        state["overrideAudit"] = log
    entry: dict[str, Any] = {
        "action": action,
        "who": actor_id(),
        "when": utc_now(),
        "why": why,
    }
    if prior_run_id:
        entry["priorRunId"] = prior_run_id
    log.append(entry)


def is_run_live(root: Path, run_id: str) -> bool:
    if run_id.startswith("deliver-"):
        slug = run_id.removeprefix("deliver-")
        state_path = root / ".cursor" / f"sw-deliver-state.{slug}.json"
        if state_path.is_file():
            try:
                data = json.loads(state_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                data = {}
            verdict = str(data.get("verdict") or "running")
            if verdict not in TERMINAL_VERDICTS:
                lease = data.get("inflightLease") or {}
                if lease.get("runId") == run_id:
                    return True
                if verdict == "running":
                    return True
    for run in enumerate_scoped_runs(root):
        slug = str(run.get("slug") or "")
        if run_id == run_id_from_slug(slug) and str(run.get("verdict")) not in TERMINAL_VERDICTS:
            return True
        state_path = root / str(run.get("statePath") or "")
        if state_path.is_file():
            try:
                data = json.loads(state_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            lease = data.get("inflightLease") or {}
            if lease.get("runId") == run_id and str(data.get("verdict")) not in TERMINAL_VERDICTS:
                return True
    return False


def cas_check(
    prior: InflightTuple | None,
    new: InflightTuple,
    *,
    takeover: str | None,
    override: str | None,
    handoff: str | None,
    state: dict[str, Any],
    root: Path,
    run_id: str,
) -> None:
    if prior is None:
        return
    if prior.run_id == new.run_id and prior.epoch == new.epoch:
        return
    if prior.run_id == new.run_id and new.epoch == prior.epoch + 1:
        return
    if prior.run_id != new.run_id and is_run_live(root, prior.run_id):
        reason = takeover or override or handoff
        if not reason:
            fail(
                "live in-flight tuple held by different run-id",
                exit_code=20,
                priorRunId=prior.run_id,
                newRunId=new.run_id,
                halt="inflight-cas",
            )
        action = "takeover" if takeover else "override" if override else "handoff"
        append_override_audit(state, action=action, why=reason, prior_run_id=prior.run_id)
    if prior.run_id == new.run_id and new.epoch != prior.epoch + 1:
        fail(
            "tuple epoch CAS mismatch",
            exit_code=20,
            expectedEpoch=prior.epoch + 1,
            got=new.epoch,
        )


def git_commit_inflight(root: Path, unit_id: str, dry_run: bool) -> str | None:
    if not dry_run:
        import default_branch_commit_guard

        default_branch_commit_guard.refuse_default_branch_commit(root, worktree=root)
    rel = pig.index_rel(root)
    proc = subprocess.run(
        ["git", "-C", str(root), "status", "--porcelain", "--", rel],
        text=True,
        capture_output=True,
    )
    if not proc.stdout.strip():
        return None
    if dry_run:
        return "dry-run"
    import default_branch_commit_guard

    default_branch_commit_guard.refuse_default_branch_commit(root, worktree=root)
    env = {**os.environ, "SW_INDEX_REGION_WRITER": "deliver"}
    subprocess.run(["git", "-C", str(root), "add", rel], check=True, env=env)
    msg = f"chore(planning): inFlight signal for {unit_id}"
    proc = subprocess.run(
        ["git", "-C", str(root), "commit", "-m", msg],
        text=True,
        capture_output=True,
        env=env,
    )
    if proc.returncode != 0:
        fail(proc.stderr.strip() or proc.stdout.strip() or "inflight INDEX commit failed")
    sha_proc = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        text=True,
        capture_output=True,
        check=True,
    )
    return sha_proc.stdout.strip()


def cmd_read(root: Path, args: list[str]) -> None:
    unit_id = parse_kv(args, "--unit")
    tuples = read_tuples(root)
    if unit_id:
        tup = tuples.get(unit_id) or tuples.get("__default__")
        if not tup:
            emit({"verdict": "pass", "action": "inflight-read", "unit": unit_id, "tuple": None})
        else:
            emit(
                {
                    "verdict": "pass",
                    "action": "inflight-read",
                    "unit": unit_id,
                    "tuple": {
                        "runId": tup.run_id,
                        "branch": tup.branch,
                        "branchToken": tup.branch_token,
                        "epoch": tup.epoch,
                    },
                }
            )
    else:
        out = {
            uid if uid != "__default__" else "(default)": {
                "runId": t.run_id,
                "branch": t.branch,
                "branchToken": t.branch_token,
                "epoch": t.epoch,
            }
            for uid, t in tuples.items()
        }
        emit({"verdict": "pass", "action": "inflight-read", "tuples": out})


def cmd_write(root: Path, args: list[str]) -> None:
    from wave_living_doc_lock import living_doc_write_lock

    state, state_path, slug, unit_id = resolve_run_context(root, args)
    run_id = parse_kv(args, "--run-id") or run_id_from_slug(slug)
    branch = parse_kv(args, "--branch") or (state.get("target") or {}).get("branch")
    branch_token = parse_kv(args, "--branch-token")
    epoch_raw = parse_kv(args, "--epoch")
    takeover = parse_kv(args, "--takeover")
    override = parse_kv(args, "--override")
    handoff = parse_kv(args, "--handoff")
    dry_run = has_flag(args, "--dry-run")
    do_commit = has_flag(args, "--commit")

    if epoch_raw:
        epoch = int(epoch_raw)
    else:
        prior_lease = (state.get("inflightLease") or {}).get("epoch", 0)
        tuples = read_tuples(root)
        prior = tuples.get(unit_id)
        epoch = (prior.epoch + 1) if prior and prior.run_id == run_id else max(1, int(prior_lease) + 1)

    new_tuple = InflightTuple(
        run_id=run_id,
        epoch=epoch,
        branch=branch if not branch_token else None,
        branch_token=branch_token,
    )
    new_tuple = redact_tuple_for_visibility(root, unit_id, new_tuple)
    new_tuple.validate_shape()

    target = (state.get("target") or {}).get("branch")
    with living_doc_write_lock(root, target=target, holder="inflight-signal-writer"):
        tuples = read_tuples(root)
        prior = tuples.get(unit_id)
        cas_check(
            prior,
            new_tuple,
            takeover=takeover,
            override=override,
            handoff=handoff,
            state=state,
            root=root,
            run_id=run_id,
        )
        tuples[unit_id] = new_tuple
        body = write_tuples(root, tuples, dry_run=dry_run)

        state["inflightLease"] = {
            "runId": run_id,
            "unitId": unit_id,
            "epoch": epoch,
            "branch": branch,
            "branchToken": branch_token,
            "holder": actor_id(),
            "leasedAt": utc_now(),
        }
        if not dry_run:
            persist_state(state_path, state)
        commit_sha = git_commit_inflight(root, unit_id, dry_run=dry_run or not do_commit)

    emit(
        {
            "verdict": "pass",
            "action": "inflight-write",
            "unit": unit_id,
            "runId": run_id,
            "epoch": epoch,
            "path": pig.index_rel(root),
            "statePath": str(state_path.relative_to(root)),
            "commit": commit_sha,
            "dryRun": dry_run,
        }
    )


def cmd_clear(root: Path, args: list[str]) -> None:
    from wave_living_doc_lock import living_doc_write_lock

    state, state_path, _slug, unit_id = resolve_run_context(root, args)
    reason = parse_kv(args, "--reason") or "run-complete"
    dry_run = has_flag(args, "--dry-run")
    do_commit = has_flag(args, "--commit")
    target = (state.get("target") or {}).get("branch")

    with living_doc_write_lock(root, target=target, holder="inflight-signal-clear"):
        tuples = read_tuples(root)
        if unit_id in tuples:
            del tuples[unit_id]
        write_tuples(root, tuples, dry_run=dry_run)
        state.pop("inflightLease", None)
        append_override_audit(state, action="clear", why=reason)
        if not dry_run:
            persist_state(state_path, state)
        commit_sha = git_commit_inflight(root, unit_id, dry_run=dry_run or not do_commit)

    emit(
        {
            "verdict": "pass",
            "action": "inflight-clear",
            "unit": unit_id,
            "reason": reason,
            "commit": commit_sha,
            "dryRun": dry_run,
        }
    )


def cmd_validate(root: Path, args: list[str]) -> None:
    if "--body" in args:
        text = args[args.index("--body") + 1]
    elif "--file" in args:
        path = Path(args[args.index("--file") + 1])
        if not path.is_file():
            fail(f"file not found: {path}")
        text = path.read_text(encoding="utf-8")
    else:
        tuples = read_tuples(root)
        text = render_region_body(tuples)
    validate_tuple_text(text)
    emit({"verdict": "pass", "action": "inflight-validate"})


def cmd_run_start(root: Path, args: list[str]) -> None:
    if "--commit" not in args:
        args = [*args, "--commit"]
    cmd_write(root, args)


def cmd_run_complete(root: Path, args: list[str]) -> None:
    if "--commit" not in args:
        args = [*args, "--commit"]
    if "--reason" not in args:
        args = [*args, "--reason", "deliver-run-complete"]
    cmd_clear(root, args)


def main(argv: list[str] | None = None) -> None:
    args = list(argv if argv is not None else sys.argv[1:])
    if not args:
        fail("usage: inflight_signal.py <repo-root> <command> [options]")
    root = Path(args[0]).resolve()
    rest = args[1:]
    if not rest:
        fail("subcommand required: read|write|clear|validate|run-start|run-complete")
    cmd = rest[0]
    tail = rest[1:]
    if cmd == "read":
        cmd_read(root, tail)
    elif cmd == "write":
        cmd_write(root, tail)
    elif cmd == "clear":
        cmd_clear(root, tail)
    elif cmd == "validate":
        cmd_validate(root, tail)
    elif cmd == "run-start":
        cmd_run_start(root, tail)
    elif cmd == "run-complete":
        cmd_run_complete(root, tail)
    else:
        fail(f"unknown subcommand: {cmd}")


if __name__ == "__main__":
    main()
