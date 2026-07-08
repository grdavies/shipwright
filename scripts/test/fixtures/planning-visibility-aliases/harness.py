#!/usr/bin/env python3
"""Visibility tier alias precedence harness (PRD 057 R29 / gap-028).

Proves the deterministic old->new alias-precedence table for the one-release
back-compat window between the deprecated `planning.visibilityProfile` key and its
tier-first rename `planning.visibilityTier` (R13):

1. New key wins over the deprecated alias when both are present and the new value
   is at least as private as the deprecated value.
2. A mixed old/new config never resolves to a *less private* tier than the
   deprecated value — the redaction default is never weakened.
3. A deprecated-only config resolves identically to pre-rename behavior (the raw
   `visibilityProfile` value, unchanged).
4. A live config that still sets the deprecated key emits a doctor deprecation
   warning naming the exact remediation; a new-key-only config does not.

ZOMBIES: Zero (no config) · One (single key set) · Many (both keys set, agreeing
and disagreeing) · Boundaries (equal-privacy values) · Interfaces (doctor warning
shape) · Exceptions (invalid legacy value) · Simple/Scale (n/a) — offline, deterministic.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parents[3]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import planning_visibility as pv

_TIER_RANK = {"all-public": 0, "specs-public": 1, "all-private": 2}


def check_deprecated_only_matches_pre_rename() -> dict:
    cfg = {"planning": {"visibilityProfile": "all-public"}}
    resolved = pv.visibility_tier(cfg)
    ok = resolved == "all-public"
    return {
        "name": "deprecated-only-matches-pre-rename",
        "ok": ok,
        "detail": f"resolved={resolved!r} expected='all-public'",
    }


def check_new_wins_when_more_private() -> dict:
    cfg = {"planning": {"visibilityTier": "all-private", "visibilityProfile": "specs-public"}}
    resolved = pv.visibility_tier(cfg)
    warning = pv.deprecated_visibility_key_warning(cfg)
    ok = resolved == "all-private" and warning is not None and warning["check"] == "visibility-tier-key-deprecated"
    return {
        "name": "new-key-wins-with-deprecation-warning",
        "ok": ok,
        "detail": f"resolved={resolved!r} warning={warning!r}",
    }


def check_new_wins_when_equal() -> dict:
    cfg = {"planning": {"visibilityTier": "specs-public", "visibilityProfile": "specs-public"}}
    resolved = pv.visibility_tier(cfg)
    ok = resolved == "specs-public"
    return {
        "name": "new-key-wins-when-equal-privacy",
        "ok": ok,
        "detail": f"resolved={resolved!r}",
    }


def check_mixed_config_never_weakens_default() -> dict:
    """R29 acceptance: a mixed old/new config with a *less private* new value never
    weakens the redaction default relative to the deprecated value."""
    cfg = {"planning": {"visibilityTier": "all-public", "visibilityProfile": "all-private"}}
    resolved = pv.visibility_tier(cfg)
    ok = resolved == "all-private" and _TIER_RANK[resolved] >= _TIER_RANK["all-private"]
    return {
        "name": "mixed-config-never-weakens-redaction-default",
        "ok": ok,
        "detail": f"resolved={resolved!r} (new='all-public' deprecated='all-private')",
    }


def check_new_key_only_no_deprecation_warning() -> dict:
    cfg = {"planning": {"visibilityTier": "all-public"}}
    resolved = pv.visibility_tier(cfg)
    warning = pv.deprecated_visibility_key_warning(cfg)
    ok = resolved == "all-public" and warning is None
    return {
        "name": "new-key-only-no-deprecation-warning",
        "ok": ok,
        "detail": f"resolved={resolved!r} warning={warning!r}",
    }


def check_no_config_defaults_specs_public() -> dict:
    resolved = pv.visibility_tier({})
    ok = resolved == "specs-public"
    return {
        "name": "no-config-defaults-specs-public",
        "ok": ok,
        "detail": f"resolved={resolved!r}",
    }


def check_invalid_legacy_value_ignored() -> dict:
    cfg = {"planning": {"visibilityProfile": "not-a-real-tier"}}
    resolved = pv.visibility_tier(cfg)
    ok = resolved == "specs-public"
    return {
        "name": "invalid-legacy-value-ignored",
        "ok": ok,
        "detail": f"resolved={resolved!r}",
    }


def main() -> int:
    checks = [
        check_deprecated_only_matches_pre_rename(),
        check_new_wins_when_more_private(),
        check_new_wins_when_equal(),
        check_mixed_config_never_weakens_default(),
        check_new_key_only_no_deprecation_warning(),
        check_no_config_defaults_specs_public(),
        check_invalid_legacy_value_ignored(),
    ]
    failures = [c for c in checks if not c["ok"]]
    verdict = "pass" if not failures else "fail"
    report = {
        "fixture": "planning-visibility-aliases",
        "rid": "R29",
        "verdict": verdict,
        "checks": checks,
        "failures": failures,
    }
    print(json.dumps(report, ensure_ascii=False))
    return 0 if verdict == "pass" else 20


if __name__ == "__main__":
    raise SystemExit(main())
