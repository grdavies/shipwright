#!/usr/bin/env python3
"""Check R25 applicability against the consumer phase, then its build-chain parity."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

from _sw.cli import run_module_main
from shipwright_state_lib import resolve_state_path

RUNTIME_ROOT = Path(__file__).resolve().parent.parent


def git(root: Path, *args: str) -> str:
    proc = subprocess.run(['git', '-C', str(root), *args], capture_output=True, text=True)
    if proc.returncode:
        raise ValueError(f"git {' '.join(args)} failed: {proc.stderr.strip()}")
    return proc.stdout


def prefixes_from(manifest: Path) -> tuple[list[str], str]:
    raw = manifest.read_bytes()
    data = json.loads(raw)
    prefixes = data.get('pathPrefixes') if isinstance(data, dict) else None
    if not isinstance(prefixes, list) or not prefixes:
        raise ValueError('build-chain manifest requires nonempty pathPrefixes')
    for prefix in prefixes:
        if (not isinstance(prefix, str) or not prefix or prefix.startswith('/')
                or '\\' in prefix or any(p in ('', '.', '..') for p in prefix.rstrip('/').split('/'))):
            raise ValueError('build-chain manifest contains invalid path prefix')
    return prefixes, hashlib.sha256(raw).hexdigest()


def phase_scope(root: Path, phase_slug: str) -> dict:
    if Path(git(root, 'rev-parse', '--show-toplevel').strip()).resolve() != root:
        raise ValueError('consumer root must be the Git worktree root')
    state_path = resolve_state_path(root)
    state = json.loads(state_path.read_text(encoding='utf-8'))
    if not isinstance(state, dict):
        raise ValueError('per-worktree state must be an object')
    branch = git(root, 'symbolic-ref', '--quiet', '--short', 'HEAD').strip()
    if state.get('currentBranch') != branch or not phase_slug or state.get('phaseSlug') != phase_slug:
        raise ValueError('per-worktree branch/phase identity mismatch')
    if state.get('worktreePath') and Path(state['worktreePath']).resolve() != root:
        raise ValueError('per-worktree path mismatch')
    parent = state.get('parentBranch')
    if not isinstance(parent, str) or not parent or parent == branch:
        raise ValueError('recorded parentBranch missing or identical to phase branch')
    # Resolve exact branch namespaces; no HEAD/default-branch fallback or ambiguous revision syntax.
    candidates = [parent] if parent.startswith(('refs/heads/', 'refs/remotes/')) else ['refs/heads/' + parent, 'refs/remotes/' + parent]
    refs = [ref for ref in candidates if subprocess.run(
        ['git', '-C', str(root), 'show-ref', '--verify', '--quiet', ref],
        capture_output=True).returncode == 0]
    if len(refs) != 1:
        raise ValueError('recorded parentBranch is missing or ambiguous')
    parent_symbolic = subprocess.run(
        ['git', '-C', str(root), 'symbolic-ref', '--quiet', refs[0]],
        capture_output=True, text=True)
    if parent_symbolic.returncode not in (0, 1):
        raise ValueError('recorded parentBranch symbolic ref could not be resolved')
    parent_ref = parent_symbolic.stdout.strip() if parent_symbolic.returncode == 0 else refs[0]
    current_ref = git(root, 'symbolic-ref', '--quiet', 'HEAD').strip()
    if parent_ref == current_ref or not parent_ref.startswith(('refs/heads/', 'refs/remotes/')):
        raise ValueError('recorded parentBranch resolves to phase branch or a non-branch ref')
    head = git(root, 'rev-parse', '--verify', 'HEAD^{commit}').strip()
    parent_head = git(root, 'rev-parse', '--verify', refs[0] + '^{commit}').strip()
    bases = git(root, 'merge-base', '--all', parent_head, head).splitlines()
    if len(bases) != 1:
        raise ValueError('phase parent has no unique merge base')
    changed: set[str] = set()
    # Separate layers prevent index/worktree cancellation from hiding a touched build path.
    for args in (
        ('diff', '--name-only', '-z', '--no-renames', bases[0], head, '--'),
        ('diff', '--cached', '--name-only', '-z', '--no-renames', head, '--'),
        ('diff', '--name-only', '-z', '--no-renames', '--'),
        ('ls-files', '--others', '--exclude-standard', '-z'),
    ):
        changed.update(p for p in git(root, *args).split('\0') if p)
    if git(root, 'ls-files', '--unmerged', '-z'):
        raise ValueError('unmerged paths make phase scope ambiguous')
    return {'root': str(root), 'phaseSlug': phase_slug, 'head': head,
            'parentBranch': parent, 'parentRef': parent_ref, 'parentHead': parent_head, 'mergeBase': bases[0],
            'stateDigest': hashlib.sha256(state_path.read_bytes()).hexdigest(),
            'changedPaths': sorted(changed)}


def consumer_check(root: Path, phase_slug: str) -> tuple[int, dict]:
    report = {'verdict': 'fail', 'applicability': 'unknown', 'root': str(root)}
    try:
        # Runtime-owned contract: consumer environment cannot replace it with an empty waiver.
        manifest = RUNTIME_ROOT / 'core/sw-reference/build-chain-paths.json'
        prefixes, digest = prefixes_from(manifest)
        scope = phase_scope(root, phase_slug)
        if phase_scope(root, phase_slug) != scope or prefixes_from(manifest)[1] != digest:
            raise ValueError('phase scope changed during acquisition')
        report.update(scope, manifest=str(manifest), manifestDigest=digest, pathPrefixes=prefixes)
        matching = [p for p in scope['changedPaths'] if any(p.startswith(prefix) for prefix in prefixes)]
        report['matchingPaths'] = matching
        report['applicability'] = 'applicable' if matching else 'not-applicable'
        if matching:
            parity = root / 'scripts/build-chain-sync.py'
            if not parity.is_file() or parity.resolve().parent.parent != root:
                raise ValueError('consumer build-chain parity script missing or outside consumer root')
            argv = [sys.executable, str(parity), '--check']
            proc = subprocess.run(argv, cwd=str(root), capture_output=True, text=True)
            report.update(parityArgv=argv, parityExitCode=proc.returncode,
                          parityStdout=proc.stdout, parityStderr=proc.stderr)
            if proc.returncode:
                return 20, report
        if phase_scope(root, phase_slug) != scope or prefixes_from(manifest)[1] != digest:
            raise ValueError('phase scope changed during check')
        report['verdict'] = 'pass'
        return 0, report
    except (OSError, ValueError, TypeError, SystemExit) as exc:
        report.update(verdict='fail', error=str(exc))
        return 20, report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path)
    parser.add_argument('--phase-slug', default='')
    parser.add_argument('--out', type=Path)
    parser.add_argument('--porcelain-only', action='store_true')
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    if args.root is not None:
        code, report = consumer_check(args.root.resolve(), args.phase_slug)
        body = json.dumps(report, ensure_ascii=True, indent=2) + '\n'
        if args.out:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(body, encoding='utf-8')
        print(body, end='')
        return code
    # Legacy standalone Shipwright invocation remains an unconditional parity check.
    manifest = Path(os.environ.get('BUILD_CHAIN_PATHS_MANIFEST', str(RUNTIME_ROOT / 'core/sw-reference/build-chain-paths.json')))
    try:
        prefixes, _ = prefixes_from(manifest)
        if args.porcelain_only:
            changed = git(RUNTIME_ROOT, 'status', '--porcelain', '-z').split('\0')
            if not any(any(path[3:].startswith(p) for p in prefixes) for path in changed if path):
                print('ship-build-chain-check: no build-chain paths in diff — skip')
                return 0
    except (OSError, ValueError) as exc:
        print(f'ship-build-chain-check: {exc}', file=sys.stderr)
        return 2
    if subprocess.run([sys.executable, str(RUNTIME_ROOT / 'scripts/build-chain-sync.py'), '--check'], cwd=str(RUNTIME_ROOT)).returncode == 0:
        print('ship-build-chain-check: build-chain parity OK')
        return 0
    print('ship-build-chain-check: FAIL — run python3 scripts/build-chain-sync.py', file=sys.stderr)
    return 20


if __name__ == '__main__':
    run_module_main(main)
