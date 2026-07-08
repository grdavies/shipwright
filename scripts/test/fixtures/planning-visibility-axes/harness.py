#!/usr/bin/env python3
"""Three orthogonal visibility axes harness (PRD 057 R13 / R14 / gap-028, gap-029).

Proves `planning_visibility.resolve_default_profile` models three orthogonal axes
distinctly — visibility (redaction) tier, `storeLocation`, and store-host privacy —
and that `probe_remote_visibility` is not the sole migration gate:

1. The three axes are present, independently keyed, and not aliases of one another.
2. A file-store (non-issue-store) root is unaffected by store-host privacy (R23
   parity): with no remote, the tier still defaults to `specs-public` exactly as
   before R13, and `storeHostPrivacy` reports `not-applicable`.
3. An issue-store root with a *public* store host is forced to the `all-private`
   tier even when the git origin remote itself is not public — proving store-host
   privacy (R14) is an independent gate, not folded into `probe_remote_visibility`.
4. An issue-store root with a *private* store host and no public remote stays at
   `specs-public` (store-host privacy does not force private when it is itself
   already private).
5. `write=True` persists both the new `visibilityTier` key and the deprecated
   `visibilityProfile` alias (one-release back-compat, R13/R29) with matching values.

ZOMBIES: Zero (no remote/no store) · One (single-axis signal) · Many (two axes
disagreeing) · Boundaries (private store host) · Interfaces (persisted config
shape) · Exceptions (n/a) · Simple/Scale (n/a) — offline, deterministic (git init
only; no network).
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parents[3]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import planning_visibility as pv


def _make_root(cfg: dict) -> tempfile.TemporaryDirectory:
    tmp = tempfile.TemporaryDirectory()
    root = Path(tmp.name)
    cursor_dir = root / ".cursor"
    cursor_dir.mkdir()
    (cursor_dir / "workflow.config.json").write_text(json.dumps(cfg), encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=str(root), check=True)
    return tmp


def check_three_axes_distinct_keys() -> dict:
    with _make_root({"planning": {}}) as tmp:
        out = pv.resolve_default_profile(Path(tmp))
    keys = {"visibilityTier", "storeLocation", "storeHostPrivacy"}
    ok = keys <= out.keys() and len({out["visibilityTier"], json.dumps(out["storeLocation"]), out["storeHostPrivacy"]}) == 3
    return {
        "name": "three-axes-distinct-keys",
        "ok": ok,
        "detail": f"keys-present={keys <= out.keys()} values={ {k: out.get(k) for k in keys} }",
    }


def check_file_store_root_unaffected_by_store_host_privacy() -> dict:
    with _make_root({"planning": {}}) as tmp:
        out = pv.resolve_default_profile(Path(tmp))
    ok = out["visibilityTier"] == "specs-public" and out["storeHostPrivacy"] == "not-applicable"
    return {
        "name": "file-store-root-unaffected-by-store-host-privacy",
        "ok": ok,
        "detail": f"tier={out['visibilityTier']!r} storeHostPrivacy={out['storeHostPrivacy']!r}",
    }


def check_public_store_host_forces_private_tier_independent_of_remote() -> dict:
    """R13 — probe_remote_visibility is not the sole gate: an absent/non-public
    remote plus a *public* store host still forces the private tier."""
    cfg = {
        "planning": {"store": {"backend": "issue-store", "issuesProvider": "github-issues", "storeHostPrivacy": "public"}},
        "host": {"provider": "github"},
    }
    with _make_root(cfg) as tmp:
        out = pv.resolve_default_profile(Path(tmp))
    remote_not_public = out["remoteProbe"].get("remoteVisibility") != "public"
    ok = remote_not_public and out["visibilityTier"] == "all-private" and out["privacyAck"]["reason"] == "public-store-host"
    return {
        "name": "public-store-host-forces-private-tier",
        "ok": ok,
        "detail": f"remoteProbe={out['remoteProbe']} tier={out['visibilityTier']!r} ack={out['privacyAck']!r}",
    }


def check_private_store_host_stays_specs_public() -> dict:
    cfg = {
        "planning": {"store": {"backend": "issue-store", "issuesProvider": "github-issues", "storeHostPrivacy": "private"}},
        "host": {"provider": "github"},
    }
    with _make_root(cfg) as tmp:
        out = pv.resolve_default_profile(Path(tmp))
    ok = out["visibilityTier"] == "specs-public" and out["storeHostPrivacy"] == "private"
    return {
        "name": "private-store-host-stays-specs-public",
        "ok": ok,
        "detail": f"tier={out['visibilityTier']!r} storeHostPrivacy={out['storeHostPrivacy']!r}",
    }


def check_write_persists_new_key_and_deprecated_alias() -> dict:
    cfg = {
        "planning": {"store": {"backend": "issue-store", "issuesProvider": "github-issues", "storeHostPrivacy": "public"}},
        "host": {"provider": "github"},
    }
    with _make_root(cfg) as tmp:
        root = Path(tmp)
        pv.resolve_default_profile(root, write=True)
        written = json.loads((root / ".cursor" / "workflow.config.json").read_text(encoding="utf-8"))
    planning = written.get("planning", {})
    ok = (
        planning.get("visibilityTier") == "all-private"
        and planning.get("visibilityProfile") == "all-private"
        and planning.get("visibilityTier") == planning.get("visibilityProfile")
    )
    return {
        "name": "write-persists-new-key-and-deprecated-alias",
        "ok": ok,
        "detail": f"planning={planning}",
    }


def main() -> int:
    checks = [
        check_three_axes_distinct_keys(),
        check_file_store_root_unaffected_by_store_host_privacy(),
        check_public_store_host_forces_private_tier_independent_of_remote(),
        check_private_store_host_stays_specs_public(),
        check_write_persists_new_key_and_deprecated_alias(),
    ]
    failures = [c for c in checks if not c["ok"]]
    verdict = "pass" if not failures else "fail"
    report = {
        "fixture": "planning-visibility-axes",
        "rid": "R13",
        "verdict": verdict,
        "checks": checks,
        "failures": failures,
    }
    print(json.dumps(report, ensure_ascii=False))
    return 0 if verdict == "pass" else 20


if __name__ == "__main__":
    raise SystemExit(main())
