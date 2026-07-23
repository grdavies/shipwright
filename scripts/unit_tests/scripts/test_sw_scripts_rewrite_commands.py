"""Command migration rewriter fixtures (PRD 078 phase 7 / TR3, R3, R13)."""
from __future__ import annotations

from pathlib import Path

from sw_scripts_rewrite import rewrite_text


def test_sample_command_body_rewrites_to_bootstrap_argv() -> None:
    body = """\
## Procedure

```bash
PR_JSON=$(python3 scripts/host.py pr-view --number "$PR")
python3 scripts/git-push.py -u origin HEAD
```

**Model tier:** cheap — resolve via `python3 scripts/resolve-model-tier.py --command sw-watch-ci`.
"""
    updated, rewrites = rewrite_text(body)
    assert "python3 scripts/sw_bootstrap.py host.py -- pr-view --number \"$PR\"" in updated
    assert "python3 scripts/sw_bootstrap.py git-push.py -- -u origin HEAD" in updated
    assert (
        "python3 scripts/sw_bootstrap.py resolve-model-tier.py -- --command sw-watch-ci"
        in updated
    )
    assert len(rewrites) == 3
    scripts = {rw.script for rw in rewrites}
    assert scripts == {"host.py", "git-push.py", "resolve-model-tier.py"}


def test_self_repo_only_row_untouched() -> None:
    body = """\
Run `python3 scripts/wave.py ship-loop drive` and `python3 scripts/check-gate.py`.
"""
    updated, rewrites = rewrite_text(body)
    assert updated == body
    assert rewrites == []


def test_pythonpath_form_rewrites() -> None:
    body = "Use PYTHONPATH=scripts python3 scripts/doctor.py status\n"
    updated, rewrites = rewrite_text(body)
    assert updated == "Use python3 scripts/sw_bootstrap.py doctor.py -- status\n"
    assert len(rewrites) == 1
    assert rewrites[0].script == "doctor.py"


def test_prose_reference_without_args() -> None:
    body = "Route context through python3 scripts/memory-redact.py before dispatch.\n"
    updated, rewrites = rewrite_text(body)
    assert "python3 scripts/sw_bootstrap.py memory-redact.py dispatch" in updated
    assert len(rewrites) == 1
