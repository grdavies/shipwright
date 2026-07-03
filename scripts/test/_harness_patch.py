"""Bash harness source patching for embedded fixture ports (R27)."""
from __future__ import annotations

import re
from pathlib import Path


_BARE_SCRIPT_RENAMES = {
    "parity-compare.sh": "parity_compare.py",
    "snapshot-tree.sh": "snapshot-tree.py",
    "memory-redact.sh": "memory-redact.py",
    "planning-unit-validate.sh": "planning-unit-validate.py",
    "doc-format-normalize.sh": "doc-format-normalize.py",
    "index-region-guard.sh": "index-region-guard.py",
    "planning-privacy-guard.sh": "planning-privacy-guard.py",
    "relief-acceptance-check.sh": "relief-acceptance-check.py",
    "spec-rigor-check.sh": "spec-rigor-check.py",
    "traceability-check.sh": "traceability-check.py",
    "copy-to-core.sh": "copy-to-core.py",
    "host-doctor.sh": "host-doctor.py",
    "stabilize-merge-sync.sh": "stabilize-merge-sync.py",
    "rules-empty.sh": "rules-empty.py",
    "rules-fail.sh": "rules-fail.py",
    "rules-ok.sh": "rules-ok.py",
    "run-gate-fixtures.sh": "scripts/unit_tests/meta/harness_gate.py",
    "run-core-scripts-parity-fixtures.sh": "scripts/unit_tests/meta/harness_core_scripts_parity.py",
    "pre-commit-completed-unit.sh": "pre-commit-completed-unit.py",
    "authoring-guard.sh": "authoring-guard.py",
    "rules-*.sh": "rules-*.py",
    "pilot-022-prerequisite-check.sh": "pilot_022_prerequisite_check.py",
}


def _apply_bare_renames(src: str) -> str:
    for old, new in _BARE_SCRIPT_RENAMES.items():
        src = src.replace(old, new)
    src = re.sub(r'bash\s+"\$ROOT/scripts/([^"]+\.py)"', r'python3 "$ROOT/scripts/\1"', src)
    src = re.sub(r'env -u GH_TOKEN bash "\$ROOT/scripts/([^"]+\.py)"', r'env -u GH_TOKEN python3 "$ROOT/scripts/\1"', src)
    return src

_FIXTURE_LIB_SHIM = """
content_path() {
  local rel="${1:?relative path}"
  if [[ -f "$ROOT/core/$rel" ]]; then
    printf '%s\\n' "$ROOT/core/$rel"
  elif [[ -f "$ROOT/$rel" ]]; then
    printf '%s\\n' "$ROOT/$rel"
  else
    printf '%s\\n' "$ROOT/$rel"
    return 1
  fi
}
""".strip()



_META = frozenset({"emitter", "parity", "claude_golden", "pr_test_plan", "core_scripts_parity", "gate", "inflight_guards_parity", "living_doc"})
_PLANNING = frozenset({"plan_killswitch", "plan_persist", "plan_proposed_parity"})


def _harness_pkg(stem: str) -> str:
    if stem in _META:
        return "meta"
    if stem.startswith("planning_") or stem in _PLANNING:
        return "planning"
    _W3 = {
        "deliver": "deliver", "deliver_concurrency": "deliver", "deliver_cwd_guard": "deliver",
        "deliver_invariant": "deliver", "deliver_loop": "deliver", "deliver_worktree_contract": "deliver",
        "merge_queue": "deliver", "parallel_merge_safety": "deliver", "status_integrity": "deliver",
        "terminal_state_read": "deliver", "hook": "hooks", "hook_worktree_alignment": "hooks",
        "fanout": "dispatch", "execute_orchestration": "execute", "delegation": "dispatch",
    }
    if stem in _W3:
        return _W3[stem]
    _W2 = {
        "state": "git", "branch_guard": "w4", "doc": "git", "host": "git", "feedback": "git",
        "retrospective": "git", "git_workflow": "workflow", "two_track": "git", "visibility": "git",
        "ux_polish": "git", "planning_autonomy": "git", "planning_graph": "git",
    }
    if stem in _W2:
        return _W2[stem]
    return "w4"


def _remap_legacy_fixture_scripts(src: str) -> str:
    def repl(match: re.Match[str]) -> str:
        stem = match.group(1)
        pkg = _harness_pkg(stem)
        return f'scripts/unit_tests/{pkg}/harness_{stem}.py'

    src = re.sub(
        r"scripts/test/run_([a-z0-9_]+)_fixtures\.py",
        repl,
        src,
    )
    return src


def _dash_fixtures(name: str) -> str:
    if not name.startswith("run-") or not name.endswith("-fixtures.sh"):
        return name.replace(".sh", ".py")
    mid = name[len("run") : -len("-fixtures.sh")].lstrip("-")
    return "run_" + mid.replace("-", "_") + "_fixtures.py"


def patch_source(src: str, root: Path) -> str:
    import os
    ephemeral = os.environ.get("SW_FIXTURES_EPHEMERAL_ROOT", "").strip()
    src = src.replace("#!/usr/bin/env bash", "")
    src = src.replace("set -euo pipefail", "set -eu")
    src = re.sub(
        r'ROOT="\$\(cd "\$\(dirname "\$\{BASH_SOURCE\[0\]\}"\)/\.\./\.\." && pwd\)"',
        f'ROOT="{root}"',
        src,
    )
    src = re.sub(
        r'ROOT="\$\(cd "\$\(dirname "\$\{BASH_SOURCE\[0\]\}"\)/\.\./\.\./\.\." && pwd\)"',
        f'ROOT="{root}"',
        src,
    )
    src = re.sub(
        r'ROOT="\$\(cd "\$\(dirname "\$\{BASH_SOURCE\[0\]\}"\)/\.\." && pwd\)"',
        f'ROOT="{root}"',
        src,
    )
    src = re.sub(
        r'ROOT="\$\(cd "\$\(dirname "\$\{BASH_SOURCE\[0\]\}"\)/(?:\.\./)+" && pwd\)"',
        f'ROOT="{root}"',
        src,
    )
    if ephemeral:
        src = src.replace(f'"{root}/scripts/test/fixtures', f'"{ephemeral}')
        src = src.replace("scripts/test/fixtures/", ephemeral.rstrip("/") + "/")
    src = re.sub(r'ROOT="[^"]*worktrees/[^"]*"', f'ROOT="{root}"', src)
    src = re.sub(r"# shellcheck source=[^\n]*\n", "", src)
    src = re.sub(
        r'source\s+"\$\(dirname\s+"\$\{BASH_SOURCE\[0\]\}"\)/fixture-lib\.sh"\s*\n?',
        "",
        src,
    )
    src = re.sub(r'source\s+"\$ROOT/scripts/test/fixture-lib\.sh"\s*\n?', "", src)
    src = re.sub(r'source\s+"[^"]*fixture-lib\.sh"\s*\n?', "", src)
    src = re.sub(
        r"scripts/test/run-[a-z0-9-]+-fixtures\.sh",
        lambda m: "scripts/test/" + _dash_fixtures(m.group(0).rsplit("/", 1)[-1]),
        src,
    )
    src = _apply_bare_renames(src)
    src = _remap_legacy_fixture_scripts(src)
    src = re.sub(r'bash\s+"\$DOC_AFTER/\$\{fx\}\.sh"', r'python3 "$DOC_AFTER/${fx}.py"', src)
    src = re.sub(r"scripts/[A-Za-z0-9_./-]+\.sh", lambda m: m.group(0)[:-3] + ".py", src)
    src = re.sub(r'bash\s+"([^"]+\.py)"', r'python3 "\1"', src)
    src = re.sub(r'\bbash scripts/([A-Za-z0-9_./-]+\.py)\b', r'python3 scripts/\1', src)
    src = re.sub(r'bash\s+"\$([A-Z_][A-Z0-9_]*)"', r'python3 "$\1"', src)
    src = re.sub(r'chmod \+x[^\n]*\n', '', src)
    src = re.sub(r'\[\[ -x "\$REDACT" \]\]', '[[ -f "$REDACT" ]]', src)
    src = re.sub(r'\| bash "\$REDACT"', '| python3 "$REDACT"', src)
    src = re.sub(r'"\$ROOT/core/hooks/pre-commit"', '"$ROOT/core/hooks/pre-commit.py"', src)
    src = re.sub(r'grep -q .pre-commit-completed-unit. "\$ROOT/core/hooks/pre-commit"', 'grep -q pre-commit-completed-unit "$ROOT/core/hooks/pre-commit.py"', src)
    src = re.sub(r'bash\s+"\$ROOT/([^"]+)"', r'python3 "$ROOT/\1"', src)
    if "content_path()" not in src and "fixture-lib" in src:
        pass
    if "content_path()" not in src:
        src = re.sub(
            rf'(ROOT="{re.escape(str(root))}"\s*\n)',
            r"\1" + _FIXTURE_LIB_SHIM + "\n",
            src,
            count=1,
        )
    return src
