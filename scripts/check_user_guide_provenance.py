#!/usr/bin/env python3
"""CI user-guide-provenance gate with already-seeded adopter guide exclusion (PRD 348 R4).

Adopter-facing guides under ``core/documentation/*.md`` and ``README.md`` must not cite
PRD / R-ID / GAP tokens. Guides that already contained at least one such token at the
diff base (``--base``) are excluded — only net-new / previously-clean guide content is
checked (D5).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

# Match harness_ux_polish user-guide-provenance tokenisation (case-sensitive).
PROVENANCE_TOKEN_RE = re.compile(r"\bPRD\s*\d+|\bR\d+\b|\bGAP-\d+")

EXIT_PASS = 0
EXIT_FAIL = 20
EXIT_ERROR = 2


@dataclass
class GuideFinding:
    path: str
    reason: str
    seeded: bool = False
    excluded: bool = False


@dataclass
class ProvenanceResult:
    verdict: str
    checked: list[str] = field(default_factory=list)
    excluded: list[str] = field(default_factory=list)
    failures: list[GuideFinding] = field(default_factory=list)
    base: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict,
            "base": self.base,
            "checked": list(self.checked),
            "excluded": list(self.excluded),
            "failures": [asdict(f) for f in self.failures],
        }


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def has_provenance_tokens(text: str | None) -> bool:
    """True when text contains at least one PRD / R-ID / GAP token."""
    if not text:
        return False
    return PROVENANCE_TOKEN_RE.search(text) is not None


def is_seeded_guide(base_text: str | None) -> bool:
    """R4 — guide already contained provenance tokens at diff-open (base)."""
    if base_text is None:
        return False
    return has_provenance_tokens(base_text)


def should_check_guide(*, base_text: str | None) -> bool:
    """Exclude already-seeded guides; include clean-new / previously-clean guides."""
    return not is_seeded_guide(base_text)


def adopter_guide_paths(root: Path) -> list[Path]:
    """Canonical adopter guide surfaces checked by user-guide-provenance."""
    docs = root / "core" / "documentation"
    paths: list[Path] = []
    if docs.is_dir():
        paths.extend(sorted(p for p in docs.glob("*.md") if p.is_file()))
    readme = root / "README.md"
    if readme.is_file():
        paths.append(readme)
    return paths


def _git_show(root: Path, ref: str, rel_path: str) -> str | None:
    """Return file contents at ref, or None when the path is absent at that ref."""
    proc = subprocess.run(
        ["git", "-C", str(root), "show", f"{ref}:{rel_path}"],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        return None
    return proc.stdout


def resolve_base_ref(explicit: str | None) -> str | None:
    if explicit:
        return explicit
    for key in ("SW_PROVENANCE_BASE", "GITHUB_BASE_SHA", "GITHUB_BASE_REF"):
        value = (os.environ.get(key) or "").strip()
        if value:
            if key == "GITHUB_BASE_REF" and "/" not in value and not value.startswith("origin/"):
                return f"origin/{value}"
            return value
    return None


def evaluate_guide(
    *,
    rel_path: str,
    head_text: str,
    base_text: str | None,
) -> GuideFinding | None:
    """Return a finding when the guide fails the gate; None when pass or excluded.

    Returns a GuideFinding with excluded=True for seeded guides (informational),
    or reason describing a failure. Callers treat excluded findings separately.
    """
    if not should_check_guide(base_text=base_text):
        return GuideFinding(
            path=rel_path,
            reason="already-seeded-at-base",
            seeded=True,
            excluded=True,
        )
    if has_provenance_tokens(head_text):
        return GuideFinding(
            path=rel_path,
            reason="provenance-tokens-in-clean-or-new-guide",
            seeded=False,
            excluded=False,
        )
    return None


def check_user_guide_provenance(
    root: Path,
    *,
    base: str | None = None,
) -> ProvenanceResult:
    """Run the provenance gate over adopter guides under root."""
    base_ref = resolve_base_ref(base)
    result = ProvenanceResult(verdict="pass", base=base_ref)

    for path in adopter_guide_paths(root):
        rel = path.relative_to(root).as_posix()
        head_text = path.read_text(encoding="utf-8")
        base_text: str | None
        if base_ref:
            base_text = _git_show(root, base_ref, rel)
        else:
            # No diff base: nothing is grandfathered; every guide is checked (legacy).
            base_text = None

        finding = evaluate_guide(rel_path=rel, head_text=head_text, base_text=base_text)
        if finding is None:
            result.checked.append(rel)
            continue
        if finding.excluded:
            result.excluded.append(rel)
            continue
        result.checked.append(rel)
        result.failures.append(finding)

    if result.failures:
        result.verdict = "fail"
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Check adopter guides for PRD/R-ID/GAP tokens (seeded-guide exclusion)"
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=None,
        help="Repository root (default: parent of scripts/)",
    )
    parser.add_argument(
        "--base",
        default=None,
        help="Git ref for diff-open baseline (also SW_PROVENANCE_BASE / GITHUB_BASE_*)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON on stdout",
    )
    args = parser.parse_args(argv)

    root = (args.root or repo_root()).resolve()
    if not root.is_dir():
        print(f"check_user_guide_provenance: root not found: {root}", file=sys.stderr)
        return EXIT_ERROR

    try:
        result = check_user_guide_provenance(root, base=args.base)
    except OSError as exc:
        print(f"check_user_guide_provenance: error: {exc}", file=sys.stderr)
        return EXIT_ERROR

    if args.json:
        print(json.dumps(result.to_dict(), indent=2, sort_keys=True))
    else:
        if result.excluded:
            print(
                "user-guide-provenance: excluded seeded guides: "
                + ", ".join(result.excluded)
            )
        if result.failures:
            for failure in result.failures:
                print(
                    f"FAIL user-guide-provenance: {failure.path} ({failure.reason})",
                    file=sys.stderr,
                )
            print(
                "user-guide-provenance: PRD/R-ID/GAP tokens remain in net-new adopter docs",
                file=sys.stderr,
            )
        else:
            checked = len(result.checked)
            excluded = len(result.excluded)
            print(
                f"user-guide-provenance: ok "
                f"(checked={checked}, excluded-seeded={excluded}, base={result.base!r})"
            )

    return EXIT_PASS if result.verdict == "pass" else EXIT_FAIL


if __name__ == "__main__":
    raise SystemExit(main())
