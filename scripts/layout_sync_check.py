#!/usr/bin/env python3
"""Dual-home layout.md byte-identity check (PRD 348 R5/R6).

Enforces that ``.sw/layout.md`` and ``core/sw-reference/layout.md`` are
byte-identical when present. Skips (pass) when neither file exists.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

EXIT_PASS = 0
EXIT_FAIL = 20
EXIT_ERROR = 2

LEGACY_LAYOUT = Path(".sw/layout.md")
CORE_LAYOUT = Path("core/sw-reference/layout.md")
LAYOUT_PAIR = (LEGACY_LAYOUT, CORE_LAYOUT)


@dataclass
class LayoutSyncResult:
    verdict: str
    checked: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    reason: str | None = None
    diagnostic: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _read_bytes(path: Path) -> bytes | None:
    if not path.is_file():
        return None
    return path.read_bytes()


def check_layout_sync(root: Path) -> LayoutSyncResult:
    """Compare the dual-home layout pair under ``root``.

    R6 — skip (pass) when neither file is present.
    R5 — fail with a diagnostic naming both paths on mismatch or one-sided presence.
    """
    root = root.resolve()
    paths = [root / rel for rel in LAYOUT_PAIR]
    rels = [str(rel).replace("\\", "/") for rel in LAYOUT_PAIR]
    bodies = [_read_bytes(path) for path in paths]
    present = [rel for rel, body in zip(rels, bodies) if body is not None]
    missing = [rel for rel, body in zip(rels, bodies) if body is None]

    if not present:
        return LayoutSyncResult(
            verdict="pass",
            checked=[],
            missing=missing,
            reason="neither-layout-present",
            diagnostic=None,
        )

    if missing:
        diagnostic = (
            "layout dual-home incomplete: "
            f"present={present!r} missing={missing!r}; "
            f"both {rels[0]!r} and {rels[1]!r} must exist and be byte-identical"
        )
        return LayoutSyncResult(
            verdict="fail",
            checked=present,
            missing=missing,
            reason="one-sided-layout-pair",
            diagnostic=diagnostic,
        )

    left, right = bodies[0], bodies[1]
    assert left is not None and right is not None
    if left == right:
        return LayoutSyncResult(
            verdict="pass",
            checked=rels,
            missing=[],
            reason="byte-identical",
            diagnostic=None,
        )

    diagnostic = (
        "layout dual-home byte mismatch: "
        f"{rels[0]!r} and {rels[1]!r} differ "
        f"({len(left)} vs {len(right)} bytes); "
        "copy the authoritative content so both files are byte-identical "
        "before commit (see docs/guides/configuration.md)"
    )
    return LayoutSyncResult(
        verdict="fail",
        checked=rels,
        missing=[],
        reason="byte-divergent",
        diagnostic=diagnostic,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Enforce byte-identity of .sw/layout.md and core/sw-reference/layout.md"
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=None,
        help="Repository root (default: parent of scripts/)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON on stdout",
    )
    args = parser.parse_args(argv)

    root = (args.root or repo_root()).resolve()
    if not root.is_dir():
        print(f"layout_sync_check: root not found: {root}", file=sys.stderr)
        return EXIT_ERROR

    try:
        result = check_layout_sync(root)
    except OSError as exc:
        print(f"layout_sync_check: error: {exc}", file=sys.stderr)
        return EXIT_ERROR

    if args.json:
        print(json.dumps(result.to_dict(), indent=2, sort_keys=True))
    else:
        if result.verdict == "pass":
            if result.reason == "neither-layout-present":
                print("layout-dual-home-sync: ok (skipped — neither layout file present)")
            else:
                print(
                    "layout-dual-home-sync: ok "
                    f"(byte-identical: {', '.join(result.checked)})"
                )
        else:
            message = result.diagnostic or result.reason or "layout dual-home check failed"
            print(f"FAIL layout-dual-home-sync: {message}", file=sys.stderr)

    return EXIT_PASS if result.verdict == "pass" else EXIT_FAIL


if __name__ == "__main__":
    raise SystemExit(main())
