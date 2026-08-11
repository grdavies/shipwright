#!/usr/bin/env python3
"""Git-ref remote lease primitive for cross-clone coordination (PRD 090 R2).

Acquire/release leases keyed by (canonical remote URL, target branch) via a
conditionally-updated git ref ``refs/sw-locks/<digest>``. Falls back to
local-only mode with a warning when ref-update capability is absent.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from host_lib import git_remote_url, parse_git_remote_url, parse_owner_repo, remote_name
from wave_lock import lock_host, ship_lease_is_stale, ship_lease_owner_live, ship_lease_pid_alive
from wave_state import emit, fail, parse_kv, utc_now

LEASE_REF_PREFIX = "refs/sw-locks"
REMOTE_LEASE_STALE_SECONDS = int(os.environ.get("SW_REMOTE_LEASE_STALE_SECONDS", "300"))


def canonical_remote_url(url: str | None) -> str:
    """Stable lease key component for SSH/HTTPS remotes."""
    if not url or not str(url).strip():
        return ""
    cleaned = str(url).strip()
    if cleaned.startswith("file://"):
        try:
            return str(Path(urlparse(cleaned).path).resolve())
        except OSError:
            return cleaned
    path_candidate = Path(cleaned)
    if cleaned.startswith("/") or (path_candidate.exists() and path_candidate.is_dir()):
        try:
            return str(path_candidate.resolve())
        except OSError:
            return cleaned
    owner_repo = parse_owner_repo(cleaned)
    if owner_repo:
        host = parse_git_remote_url(cleaned)
        return f"https://{host}/{'/'.join(owner_repo)}.git"
    parsed = urlparse(cleaned)
    if parsed.scheme in ("http", "https") and parsed.path:
        path = parsed.path.rstrip("/")
        if path.endswith(".git"):
            path = path[:-4]
        return f"{parsed.scheme}://{parsed.netloc}{path}".lower()
    return cleaned.rstrip("/").removesuffix(".git").lower()


def remote_lease_key_digest(remote_url: str, target_branch: str) -> str:
    raw = f"{canonical_remote_url(remote_url)}\0{target_branch}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:32]


def remote_lease_ref(digest: str) -> str:
    return f"{LEASE_REF_PREFIX}/{digest}"


def resolve_remote(root: Path, remote: str | None = None) -> str:
    name = (remote or remote_name({}) or "origin").strip() or "origin"
    return name


def resolve_canonical_remote_url(root: Path, remote: str | None = None) -> str | None:
    name = resolve_remote(root, remote)
    url = git_remote_url(root, name)
    if not url:
        return None
    canonical = canonical_remote_url(url)
    return canonical or None


def _run_git(root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        text=True,
        check=check,
    )


def _read_ref(root: Path, remote: str, ref: str) -> str | None:
    proc = _run_git(root, "ls-remote", remote, ref, check=False)
    if proc.returncode != 0:
        return None
    for line in (proc.stdout or "").splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[1] == ref:
            return parts[0]
    return None


def _ensure_ref_fetched(root: Path, remote: str, ref: str, sha: str) -> None:
    proc = _run_git(root, "cat-file", "-e", sha, check=False)
    if proc.returncode == 0:
        return
    _run_git(root, "fetch", remote, f"{sha}", check=False)
    proc2 = _run_git(root, "cat-file", "-e", sha, check=False)
    if proc2.returncode != 0:
        _run_git(root, "fetch", remote, f"{ref}:{ref}", check=False)


def _read_lease_payload(root: Path, commit_sha: str, *, remote: str | None = None, ref: str | None = None) -> dict[str, Any] | None:
    if remote and ref:
        _ensure_ref_fetched(root, remote, ref, commit_sha)
    proc = _run_git(root, "cat-file", "-p", commit_sha, check=False)
    if proc.returncode != 0:
        return None
    text = proc.stdout or ""
    for line in text.splitlines():
        if line.startswith("{"):
            try:
                payload = json.loads(line)
                if isinstance(payload, dict):
                    return payload
            except json.JSONDecodeError:
                continue
    # commit message may span lines after blank line
    if "\n\n" in text:
        body = text.split("\n\n", 1)[1].strip()
        try:
            payload = json.loads(body)
            if isinstance(payload, dict):
                return payload
        except json.JSONDecodeError:
            return None
    return None


def _lease_owner_live(payload: dict[str, Any]) -> bool:
    meta = {
        "heartbeatAt": payload.get("heartbeatAt") or payload.get("acquiredAt"),
        "host": payload.get("host"),
        "pid": payload.get("pid"),
    }
    if ship_lease_owner_live(meta):
        return True
    hb = meta.get("heartbeatAt")
    if not isinstance(hb, str):
        return False
    try:
        dt = datetime.strptime(hb, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        age = (datetime.now(timezone.utc) - dt).total_seconds()
        return age <= REMOTE_LEASE_STALE_SECONDS
    except ValueError:
        return False


def _lease_meta(*, remote_url: str, target_branch: str, run_id: str) -> dict[str, Any]:
    now = utc_now()
    return {
        "kind": "remote-lease",
        "remoteUrl": canonical_remote_url(remote_url),
        "targetBranch": target_branch,
        "runId": run_id,
        "owner": f"{lock_host()}:{os.getpid()}",
        "host": lock_host(),
        "pid": os.getpid(),
        "epoch": 1,
        "acquiredAt": now,
        "heartbeatAt": now,
    }


_EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"


def _create_lease_commit(root: Path, payload: dict[str, Any]) -> str:
    msg = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    commit = subprocess.check_output(
        ["git", "-C", str(root), "commit-tree", _EMPTY_TREE, "-m", msg],
        text=True,
    ).strip()
    return commit


def probe_ref_update_capability(root: Path, remote: str | None = None) -> bool:
    """Return True when ref updates to the remote are expected to succeed."""
    if os.environ.get("SW_REMOTE_LEASE_FORCE_LOCAL", "").strip() in ("1", "true", "yes"):
        return False
    if os.environ.get("SW_REMOTE_LEASE_FORCE_REMOTE", "").strip() in ("1", "true", "yes"):
        return True
    name = resolve_remote(root, remote)
    url = git_remote_url(root, name) or ""
    if url.startswith("file://") or (url.startswith("/") and Path(url).exists()):
        return True
    if Path(url).exists():
        return True
    # Local bare/path remotes used in tests: /path/to/repo.git
    if url.endswith(".git") and Path(url).exists():
        return True
    # Hosted remotes require push permission; absence of credentials is not a hard error here.
    if not url.strip():
        return False
    return True


def _push_ref(
    root: Path,
    remote: str,
    ref: str,
    commit_sha: str,
    *,
    old_sha: str | None = None,
) -> tuple[bool, str]:
    spec = f"{commit_sha}:{ref}"
    cmd = ["git", "-C", str(root), "push", remote, spec]
    if old_sha:
        cmd = [
            "git",
            "-C",
            str(root),
            "push",
            f"--force-with-lease={ref}:{old_sha}",
            remote,
            spec,
        ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode == 0:
        return True, ""
    detail = (proc.stderr or proc.stdout or "").strip()
    return False, detail


def _delete_ref(root: Path, remote: str, ref: str, *, old_sha: str) -> tuple[bool, str]:
    proc = subprocess.run(
        [
            "git",
            "-C",
            str(root),
            "push",
            f"--force-with-lease={ref}:{old_sha}",
            remote,
            f":{ref}",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode == 0:
        return True, ""
    return False, (proc.stderr or proc.stdout or "").strip()


def acquire_remote_lease(
    root: Path,
    target_branch: str,
    run_id: str,
    *,
    remote: str | None = None,
) -> dict[str, Any]:
    """Acquire cross-clone remote lease; local-only fallback when ref updates unavailable."""
    name = resolve_remote(root, remote)
    remote_url = git_remote_url(root, name)
    if not remote_url:
        return {
            "verdict": "pass",
            "action": "remote-lease-acquire",
            "mode": "local-only",
            "warning": "remote-unavailable",
            "targetBranch": target_branch,
            "runId": run_id,
        }
    digest = remote_lease_key_digest(remote_url, target_branch)
    ref = remote_lease_ref(digest)
    if not probe_ref_update_capability(root, name):
        return {
            "verdict": "pass",
            "action": "remote-lease-acquire",
            "mode": "local-only",
            "warning": "ref-update-unavailable",
            "targetBranch": target_branch,
            "runId": run_id,
            "remoteUrl": canonical_remote_url(remote_url),
            "leaseRef": ref,
            "leaseKeyDigest": digest,
        }

    current_sha = _read_ref(root, name, ref)
    if current_sha:
        existing = _read_lease_payload(root, current_sha, remote=name, ref=ref) or {}
        if existing.get("runId") == run_id and _lease_owner_live(existing):
            return {
                "verdict": "pass",
                "action": "remote-lease-acquire",
                "mode": "remote",
                "reentrant": True,
                "targetBranch": target_branch,
                "runId": run_id,
                "remoteUrl": canonical_remote_url(remote_url),
                "leaseRef": ref,
                "leaseKeyDigest": digest,
                "commit": current_sha,
            }
        if _lease_owner_live(existing):
            return {
                "verdict": "fail",
                "error": "remote-lease-conflict",
                "holder": existing,
                "targetBranch": target_branch,
                "runId": run_id,
                "leaseRef": ref,
                "commit": current_sha,
            }

    prior_epoch = 0
    if current_sha:
        prior = _read_lease_payload(root, current_sha, remote=name, ref=ref) or {}
        prior_epoch = int(prior.get("epoch") or 0)

    payload = _lease_meta(remote_url=remote_url, target_branch=target_branch, run_id=run_id)
    payload["epoch"] = prior_epoch + 1
    commit_sha = _create_lease_commit(root, payload)

    if current_sha:
        ok, detail = _push_ref(root, name, ref, commit_sha, old_sha=current_sha)
    else:
        ok, detail = _push_ref(root, name, ref, commit_sha)
    if not ok:
        if "denied" in detail.lower() or "permission" in detail.lower():
            return {
                "verdict": "pass",
                "action": "remote-lease-acquire",
                "mode": "local-only",
                "warning": "ref-update-unavailable",
                "detail": detail,
                "targetBranch": target_branch,
                "runId": run_id,
                "remoteUrl": canonical_remote_url(remote_url),
                "leaseRef": ref,
                "leaseKeyDigest": digest,
            }
        return {
            "verdict": "fail",
            "error": "remote-lease-push-failed",
            "detail": detail,
            "targetBranch": target_branch,
            "runId": run_id,
            "leaseRef": ref,
        }

    return {
        "verdict": "pass",
        "action": "remote-lease-acquire",
        "mode": "remote",
        "targetBranch": target_branch,
        "runId": run_id,
        "remoteUrl": canonical_remote_url(remote_url),
        "leaseRef": ref,
        "leaseKeyDigest": digest,
        "commit": commit_sha,
        "epoch": payload["epoch"],
    }


def release_remote_lease(
    root: Path,
    target_branch: str,
    run_id: str,
    *,
    remote: str | None = None,
) -> dict[str, Any]:
    name = resolve_remote(root, remote)
    remote_url = git_remote_url(root, name)
    if not remote_url:
        return {
            "verdict": "pass",
            "action": "remote-lease-release",
            "mode": "local-only",
            "note": "remote-unavailable",
        }
    digest = remote_lease_key_digest(remote_url, target_branch)
    ref = remote_lease_ref(digest)
    if not probe_ref_update_capability(root, name):
        return {
            "verdict": "pass",
            "action": "remote-lease-release",
            "mode": "local-only",
            "note": "ref-update-unavailable",
        }

    current_sha = _read_ref(root, name, ref)
    if not current_sha:
        return {
            "verdict": "pass",
            "action": "remote-lease-release",
            "mode": "remote",
            "note": "no lease ref",
        }
    existing = _read_lease_payload(root, current_sha, remote=name, ref=ref) or {}
    if existing.get("runId") != run_id:
        return {
            "verdict": "fail",
            "error": "remote-lease-run-mismatch",
            "holder": existing,
        }
    ok, detail = _delete_ref(root, name, ref, old_sha=current_sha)
    if not ok:
        return {
            "verdict": "fail",
            "error": "remote-lease-release-failed",
            "detail": detail,
        }
    return {
        "verdict": "pass",
        "action": "remote-lease-release",
        "mode": "remote",
        "targetBranch": target_branch,
        "runId": run_id,
        "leaseRef": ref,
    }


def cmd_acquire(root: Path, args: list[str]) -> None:
    target = parse_kv(args, "--target")
    run_id = parse_kv(args, "--run-id") or os.environ.get("SW_DELIVER_RUN_ID", "")
    remote = parse_kv(args, "--remote")
    if not target:
        fail("--target required")
    if not run_id:
        fail("--run-id or SW_DELIVER_RUN_ID required")
    out = acquire_remote_lease(root, target, run_id, remote=remote)
    if out.get("verdict") != "pass":
        fail(out.get("error", "remote lease held"), exit_code=20, holder=out.get("holder"))
    emit(out)


def cmd_release(root: Path, args: list[str]) -> None:
    target = parse_kv(args, "--target")
    run_id = parse_kv(args, "--run-id") or os.environ.get("SW_DELIVER_RUN_ID", "")
    remote = parse_kv(args, "--remote")
    if not target or not run_id:
        fail("--target and --run-id required")
    out = release_remote_lease(root, target, run_id, remote=remote)
    if out.get("verdict") != "pass":
        fail(out.get("error", "remote lease release failed"), exit_code=20, holder=out.get("holder"))
    emit(out)


def cmd_probe(root: Path, args: list[str]) -> None:
    remote = parse_kv(args, "--remote")
    emit(
        {
            "verdict": "pass",
            "action": "remote-lease-probe",
            "refUpdateCapable": probe_ref_update_capability(root, remote),
            "remoteUrl": resolve_canonical_remote_url(root, remote),
        }
    )


def main() -> None:
    if len(sys.argv) < 3:
        fail("usage: wave_remote_lease.py <root> <acquire|release|probe> ...")
    root = Path(sys.argv[1]).resolve()
    sub = sys.argv[2]
    rest = sys.argv[3:]
    if sub == "acquire":
        cmd_acquire(root, rest)
    elif sub == "release":
        cmd_release(root, rest)
    elif sub == "probe":
        cmd_probe(root, rest)
    else:
        fail(f"unknown remote-lease subcommand: {sub}")


if __name__ == "__main__":
    main()
