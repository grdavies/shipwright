"""PRD 330 R1/R2 — documented default parity and PROVENANCE truth claims."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

SCRIPT_DIR = Path(__file__).resolve().parents[2]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from documented_defaults_check import run_check  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]

GOOD_PROVENANCE = """\
| [CodeRabbit CLI](https://docs.coderabbit.ai/) | AI PR + local review | `review.provider: coderabbit` (opt-in; effective default `none`) | adapter |
Optional at install: none of the above are required. `/sw-init` validates providers (`/sw-setup` is a deprecated alias).
"""

STALE_CODERABBIT_DEFAULT = """\
| [CodeRabbit CLI](https://docs.coderabbit.ai/) | AI PR + local review | `review.provider: coderabbit` (default) | adapter |
Optional at install: `/sw-init` validates providers (`/sw-setup` is a deprecated alias).
"""

UNQUALIFIED_SW_SETUP = """\
| [CodeRabbit CLI](https://docs.coderabbit.ai/) | AI PR + local review | `review.provider: coderabbit` (opt-in; effective default `none`) | adapter |
Optional at install: `/sw-setup` validates what your selected providers need.
"""


def test_current_repo_documented_defaults_pass() -> None:
    result = run_check(ROOT)
    assert result["verdict"] == "pass", result
    review_claim = next(c for c in result["claims"] if c["id"] == "review-provider-effective-default")
    assert review_claim["verdict"] == "pass"
    assert review_claim["expectedDefault"] == "none"


def test_stale_coderabbit_default_claim_fails() -> None:
    result = run_check(ROOT, provenance_text=STALE_CODERABBIT_DEFAULT)
    assert result["verdict"] == "fail"
    rules = {row["rule"] for row in result["failures"]}
    assert "stale-coderabbit-default" in rules


def test_unqualified_sw_setup_claim_fails() -> None:
    result = run_check(ROOT, provenance_text=UNQUALIFIED_SW_SETUP)
    assert result["verdict"] == "fail"
    rules = {row["rule"] for row in result["failures"]}
    assert "unqualified-sw-setup-primary" in rules
    assert "provenance-setup-deprecated" in rules


def test_good_provenance_fixture_passes_review_and_init_claims() -> None:
    result = run_check(ROOT, provenance_text=GOOD_PROVENANCE)
    doc_failures = [f for f in result["failures"] if not f["rule"].startswith("review-provider")]
    assert doc_failures == [], result


def test_check_gate_lib_wires_documented_defaults() -> None:
    import check_gate_lib as gate

    assert gate.validate_documented_defaults_drift(ROOT) is None
