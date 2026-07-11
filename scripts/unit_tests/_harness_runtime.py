"""Embedded bash harness runtime for pytest ports (PRD 054 phase 7)."""
from __future__ import annotations

import os
import re
from pathlib import Path


def harness_subprocess_env(root: Path, base: dict[str, str] | None = None) -> dict[str, str]:
    """Hermetic env for embedded bash harnesses — drop deliver phase-mode pollution."""
    env = dict(base if base is not None else os.environ)
    for key in list(env):
        if key.startswith("SW_PHASE") or key in (
            "SW_RUN_DIR",
            "SW_REPO_ROOT",
            "SW_INTEGRATION_BRANCH",
            "PYTHONHOME",
        ):
            env.pop(key, None)
    env["ROOT"] = str(root)
    env["SW_HARNESS"] = "1"
    env["PYTHONPATH"] = os.pathsep.join(
        p
        for p in (
            str(root / "scripts" / "test"),
            str(root / "scripts"),
            env.get("PYTHONPATH", ""),
        )
        if p
    )
    return env


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
    "validate-descriptor.sh": "validate_descriptor.py",
    "tasks-progress.sh": "tasks-progress.py",
    "tasks-currency-gate.sh": "tasks-currency-gate.py",
    "check-frozen.sh": "check-frozen.py",
    "worktree.sh": "worktree.py",
    "branch-name-guard.sh": "branch-name-guard.py",
    "resolve-base-branch.sh": "resolve-base-branch.py",
    "secret-scan.sh": "secret-scan.py",
    "git-push.sh": "git-push.py",
    "redaction-guard.sh": "redaction-guard.py",
    "ship-phase-steps.sh": "ship-phase-steps.py",
    "ship-phase-status.sh": "ship-phase-status.py",
    "shipwright-state.sh": "shipwright-state.py",
    "sw-assert-worktree.sh": "sw-assert-worktree.py",
    "docs_worktree.sh": "docs_worktree.py",
    "doc-link-check.sh": "docs_link_check.py",
    "docs-link-check.sh": "docs_link_check.py",
    "intra-phase-dispatch.sh": "intra_phase_dispatch.py",
    "wave.sh": "wave.py",
    "sw-resolve-plugin-root.sh": "sw-resolve-plugin-root.py",
    "in-repo-memory-search.sh": "in-repo-memory-search.py",
    "in-repo-rules.sh": "in-repo-rules.py",
    "model-routing-check.sh": "model-routing-check.py",
    "resolve-model-tier.sh": "resolve-model-tier.py",
    "model-tier-check.sh": "model-tier-check.py",
    "code-review-normalize.sh": "code-review-normalize.py",
    "code-review-gate.sh": "code-review-gate.py",
    "code-review-apply-check.sh": "code-review-apply-check.py",
    "code-review-select.sh": "code-review-select.py",
    "review-local-resolve.sh": "review-local-resolve.py",
    "feedback-backlog.sh": "feedback-backlog.py",
    "feedback-closure-gate.sh": "feedback-closure-gate.py",
    "verify-evidence.sh": "verify-evidence.py",
    "verify-baseline.sh": "verify-baseline.py",
    "sw-tmp.sh": "sw-tmp.py",
    "tdd-gate.sh": "tdd-gate.py",
    "plan-self-review.sh": "plan-self-review.py",
    "simplify-gate.sh": "simplify-gate.py",
    "verify-e2e.sh": "verify-e2e.py",
}


def _apply_bare_renames(src: str) -> str:
    for old, new in _BARE_SCRIPT_RENAMES.items():
        src = src.replace(old, new)
    src = re.sub(r'bash\s+"\$ROOT/scripts/([^"]+\.py)"', r'python3 "$ROOT/scripts/\1"', src)
    src = re.sub(r'env -u GH_TOKEN bash "\$ROOT/scripts/([^"]+\.py)"', r'env -u GH_TOKEN python3 "$ROOT/scripts/\1"', src)
    src = re.sub(
        r'source "\$ROOT/scripts/sw-resolve-plugin-root\.py"\s*\nCONTENT="\$\(sw_resolve_plugin_root "\$ROOT/scripts"\)"',
        'CONTENT="$(python3 "$ROOT/scripts/sw-resolve-plugin-root.py" "$ROOT/scripts")"',
        src,
    )
    src = src.replace(
        'CONTENT="$(sw_resolve_plugin_root "$ROOT/scripts")"',
        'CONTENT="$(python3 "$ROOT/scripts/sw-resolve-plugin-root.py" "$ROOT/scripts")"',
    )
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
    return 0
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
        return f"scripts/unit_tests/{pkg}/harness_{stem}.py"

    src = re.sub(
        r"scripts/test/run_([a-z0-9_]+)_fixtures\.py",
        repl,
        src,
    )
    src = re.sub(
        r'source "\$ROOT/scripts/sw-resolve-plugin-root\.py"\s*\nCONTENT="\$\(sw_resolve_plugin_root "\$ROOT/scripts"\)"',
        'CONTENT="$(python3 "$ROOT/scripts/sw-resolve-plugin-root.py" "$ROOT/scripts")"',
        src,
    )
    src = src.replace(
        'CONTENT="$(sw_resolve_plugin_root "$ROOT/scripts")"',
        'CONTENT="$(python3 "$ROOT/scripts/sw-resolve-plugin-root.py" "$ROOT/scripts")"',
    )
    return src


def _dash_fixtures(name: str) -> str:
    if not name.startswith("run-") or not name.endswith("-fixtures.sh"):
        return name.replace(".sh", ".py")
    mid = name[len("run") : -len("-fixtures.sh")].lstrip("-")
    return "run_" + mid.replace("-", "_") + "_fixtures.py"


def _apply_grep_py_aliases(src: str) -> str:
    """Accept .py successors in harness grep checks after shell retirement."""
    pairs = [
        ("git-push.sh", "git-push.py"),
        ("secret-scan.sh", "secret-scan.py"),
        ("doc-link-check.sh", "docs_link_check.py"),
        ("branch-name-guard.sh", "branch-name-guard.py"),
        ("worktree.sh", "worktree.py"),
        ("check-gate.sh", "check-gate.py"),
        ("code-review-normalize.sh", "code-review-normalize.py"),
        ("in-repo-memory-search.sh", "in-repo-memory-search.py"),
        ("in-repo-rules.sh", "in-repo-rules.py"),
        ("stub.sh", "stub.py"),
        ("playwright.sh", "playwright.py"),
        ("failstub.sh", "failstub.py"),
    ]
    out_lines: list[str] = []
    for line in src.splitlines(keepends=True):
        if "grep" in line:
            for old, new_name in pairs:
                line = line.replace(old, new_name)
        out_lines.append(line)
    src = "".join(out_lines)
    src = re.sub(r'\[\[ -x "\$([A-Z_][A-Z0-9_]*)" \]\]', r'[[ -f "$\1" ]]', src)
    src = src.replace('OUT=$("$VALIDATE"', 'OUT=$(python3 "$VALIDATE"')
    src = src.replace('OUT=$("$SHIP_STATUS"', 'OUT=$(python3 "$SHIP_STATUS"')
    src = re.sub(
        r'source "\$ROOT/scripts/sw-resolve-plugin-root\.py"\s*\nCONTENT="\$\(sw_resolve_plugin_root "\$ROOT/scripts"\)"',
        'CONTENT="$(python3 "$ROOT/scripts/sw-resolve-plugin-root.py" "$ROOT/scripts")"',
        src,
    )
    src = src.replace(
        'CONTENT="$(sw_resolve_plugin_root "$ROOT/scripts")"',
        'CONTENT="$(python3 "$ROOT/scripts/sw-resolve-plugin-root.py" "$ROOT/scripts")"',
    )
    return src


def patch_source(src: str, root: Path) -> str:
    import os
    src = re.sub(
        r'bash -n "\$\{BASH_SOURCE\[0\]\}" \|\| \{[^}]*\}\n',
        "",
        src,
    )
    ephemeral = os.environ.get("SW_FIXTURES_EPHEMERAL_ROOT", "").strip()
    src = src.replace("#!/usr/bin/env bash", "")
    src = src.replace("set -euo pipefail", "set -eu")
    if "unset SW_PHASE_MODE" not in src:
        src = re.sub(
            r"(set -eu\s*\n)",
            r"\1unset SW_PHASE_MODE SW_PHASE_SLUG SW_RUN_DIR SW_REPO_ROOT SW_INTEGRATION_BRANCH 2>/dev/null || true\n",
            src,
            count=1,
        )
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
        r'ROOT="\$\(cd "\$\(dirname "\$\{BASH_SOURCE\[0\]\}"\)/(?:\.\./)*\.\." && pwd\)"',
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
    src = src.replace("scripts/docs-link-check.py", "scripts/docs_link_check.py")
    src = src.replace("providers/verify/stub.sh", "providers/verify/stub.py")
    src = src.replace("providers/verify/playwright.sh", "providers/verify/playwright.py")
    src = src.replace("providers/verify/failstub.sh", "providers/verify/failstub.py")
    src = re.sub(
        r"PERMS=\$\(stat -f '%Lp' \"\$RUN_DIR\" 2>/dev/null \|\| stat -c '%a' \"\$RUN_DIR\" 2>/dev/null\)",
        'PERMS=$(python3 -c "import os,sys; print(oct(os.stat(sys.argv[1]).st_mode & 0o777)[-3:])" "$RUN_DIR")',
        src,
    )
    src = re.sub(
        r'git init -q "(\$TMP/[^"]+)"\n  git -C "\1" commit',
        r'git init -q "\1"\n  git -C "\1" config user.email "fixture@shipwright.local"\n  git -C "\1" config user.name "fixture"\n  git -C "\1" commit',
        src,
    )
    src = re.sub(r'bash\s+"([^"]+\.py)"', r'python3 "\1"', src)
    src = re.sub(r'\bbash scripts/([A-Za-z0-9_./-]+\.py)\b', r'python3 scripts/\1', src)
    src = re.sub(r'bash\s+"\$([A-Z_][A-Z0-9_]*)"', r'python3 "$\1"', src)
    src = re.sub(r"chmod \+x[^\n]*\n", "", src)
    src = re.sub(r'\[\[ -x "\$REDACT" \]\]', '[[ -f "$REDACT" ]]', src)
    src = re.sub(r'\| bash "\$REDACT"', '| python3 "$REDACT"', src)
    src = re.sub(r'"\$ROOT/core/hooks/pre-commit"', '"$ROOT/core/hooks/pre-commit.py"', src)
    src = re.sub(
        r'grep -q .pre-commit-completed-unit. "\$ROOT/core/hooks/pre-commit"',
        'grep -q pre-commit-completed-unit "$ROOT/core/hooks/pre-commit.py"',
        src,
    )
    src = re.sub(r'bash\s+"\$ROOT/([^"]+)"', r'python3 "$ROOT/\1"', src)
    src = _apply_grep_py_aliases(src)
    if "content_path()" not in src:
        src = re.sub(
            rf'(ROOT="{re.escape(str(root))}"\s*\n)',
            r"\1" + _FIXTURE_LIB_SHIM + "\n",
            src,
            count=1,
        )
    src = re.sub(
        r'source "\$ROOT/scripts/sw-resolve-plugin-root\.py"\s*\nCONTENT="\$\(sw_resolve_plugin_root "\$ROOT/scripts"\)"',
        'CONTENT="$(python3 "$ROOT/scripts/sw-resolve-plugin-root.py" "$ROOT/scripts")"',
        src,
    )
    src = src.replace(
        'CONTENT="$(sw_resolve_plugin_root "$ROOT/scripts")"',
        'CONTENT="$(python3 "$ROOT/scripts/sw-resolve-plugin-root.py" "$ROOT/scripts")"',
    )
    return src

def content_path(root: Path, rel: str) -> Path:
    for base in (root, root / "core"):
        candidate = base / rel
        if candidate.is_file():
            return candidate
    return root / rel


class FixtureContext:
    """Fixture runner context for remaining embedded-python harness ports."""

    def __init__(self, from_file: str | Path) -> None:
        import sys
        from _sw.vendor_paths import repo_root as sw_repo_root

        self.root = sw_repo_root(from_file)
        self.failures = 0
        self._cleanups: list[Path] = []
        self.env = os.environ.copy()
        self.env.setdefault("PYTHONPATH", str(self.root / "scripts"))
        scripts = str(self.root / "scripts")
        if scripts not in self.env.get("PYTHONPATH", "").split(os.pathsep):
            self.env["PYTHONPATH"] = scripts + os.pathsep + self.env.get("PYTHONPATH", "")

    def ok(self, name: str) -> None:
        print(f"OK  {name}")

    def bad(self, name: str) -> None:
        print(f"FAIL {name}")
        self.failures += 1

    def baseline_path_for(self, run_id: str) -> Path:
        """Caller-owned per-run verify baseline path (PRD 060 R15)."""
        safe = re.sub(r"[^a-zA-Z0-9._-]+", "-", run_id).strip("-") or "run"
        base = self.mktemp(prefix=f"sw-baseline-{safe[:24]}-")
        path = base / "baseline.verify.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def mktemp(self, prefix: str = "sw-fix-") -> Path:
        import tempfile

        path = Path(tempfile.mkdtemp(prefix=prefix))
        self._cleanups.append(path)
        return path

    def cleanup(self) -> None:
        import shutil

        for path in self._cleanups:
            shutil.rmtree(path, ignore_errors=True)
        self._cleanups.clear()

    def script_path(self, rel: str) -> Path:
        rel = rel.replace(".sh", ".py")
        return self.root / rel

    def run_py(
        self,
        rel: str,
        *args: str,
        cwd: Path | None = None,
        env: dict[str, str] | None = None,
        input_text: str | None = None,
        check: bool = False,
    ):
        import sys
        from _sw import proc

        path = self.script_path(rel)
        cmd = [sys.executable, str(path), *args]
        merged = self.env.copy()
        if env:
            merged.update(env)
        return proc.run(cmd, cwd=str(cwd or self.root), env=merged, input_text=input_text, check=check)

    def run_git(self, *args: str, cwd: Path) -> None:
        from _sw import proc

        proc.run(["git", *args], cwd=str(cwd), env=self.env, check=False)

    def jq(self, text: str, expr: str) -> str:
        import sys
        from _sw import proc

        completed = proc.run(
            [sys.executable, "-c", f"import json,sys; d=json.load(sys.stdin); print({expr})"],
            input_text=text,
        )
        return completed.stdout.strip()

    def load_json(self, text: str) -> object:
        import json

        return json.loads(text)

    def exit_code(self) -> int:
        return 1 if self.failures else 0

