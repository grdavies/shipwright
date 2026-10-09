"""Real Git and subprocess regressions; run directly to avoid primary-worktree fixtures."""
from __future__ import annotations
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))
import ship_gate_handlers as handlers


class ConsumerScope(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name).resolve()
        self.root = self.base / 'consumer'
        self.runtime = self.base / 'runtime'
        self.root.mkdir()
        (self.runtime / 'scripts').mkdir(parents=True)
        for name in ('ship-build-chain-check.py', 'shipwright_state_lib.py'):
            shutil.copy2(SCRIPTS / name, self.runtime / 'scripts' / name)
        shutil.copytree(SCRIPTS / '_sw', self.runtime / 'scripts/_sw')
        self.manifest = self.runtime / 'core/sw-reference/build-chain-paths.json'
        self.manifest.parent.mkdir(parents=True)
        self.manifest.write_text(json.dumps({'pathPrefixes': ['scripts/', 'core/']}))
        # Any accidental runtime parity is a visible failure, never an execution mock.
        (self.runtime / 'scripts/build-chain-sync.py').write_text('raise SystemExit(20)\n')
        self.git('init', '-b', 'integration')
        self.git('config', 'user.email', 'fixture@example.invalid')
        self.git('config', 'user.name', 'Scope Fixture')
        self.write('app/start.txt', 'base')
        self.write('scripts/old.txt', 'base')
        self.git('add', '.')
        self.git('commit', '-qm', 'base')
        self.git('checkout', '-qb', 'phase')
        self.state = self.root / '.git/shipwright.json'
        self.state.write_text(json.dumps({'parentBranch': 'integration', 'currentBranch': 'phase', 'phaseSlug': 'example'}))
        self.out = self.base / 'status.json'
        self.env = os.environ.copy()
        self.env.pop('BUILD_CHAIN_PATHS_MANIFEST', None)

    def git(self, *args):
        return subprocess.run(['git', '-C', str(self.root), *args], check=True, capture_output=True, text=True).stdout.strip()

    def write(self, rel, body):
        target = self.root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body)

    def run_check(self, *extra):
        proc = subprocess.run([sys.executable, str(self.runtime / 'scripts/ship-build-chain-check.py'), '--root', str(self.root), '--phase-slug', 'example', '--out', str(self.out), *extra], capture_output=True, text=True, env=self.env)
        data = json.loads(self.out.read_text()) if self.out.exists() else {}
        return proc.returncode, data

    def parity(self, code=0):
        self.write('scripts/build-chain-sync.py', 'from pathlib import Path\nimport sys\nassert sys.argv[1:] == ["--check"]\nPath(".git/parity-ran").write_text(str(Path.cwd()))\nraise SystemExit(%d)\n' % code)
        self.git('add', '.')
        self.git('commit', '-qm', 'parity fixture')
        self.git('branch', '-f', 'integration', 'HEAD')

    def test_clean_scope_skips(self):
        code, data = self.run_check()
        self.assertEqual(code, 0)
        self.assertEqual(data['applicability'], 'not-applicable')
        self.assertEqual(data['changedPaths'], [])

    def test_committed_non_build_scope_skips(self):
        self.write('app/committed.txt', 'change')
        self.git('add', '.')
        self.git('commit', '-qm', 'consumer change')
        code, data = self.run_check()
        self.assertEqual(code, 0)
        self.assertEqual(data['changedPaths'], ['app/committed.txt'])
        self.assertEqual(data['applicability'], 'not-applicable')

    def test_each_change_layer_is_acquired(self):
        self.parity()
        for layer in ('committed', 'staged', 'unstaged', 'untracked'):
            with self.subTest(layer=layer):
                self.write('scripts/' + layer + '.txt', layer)
                if layer in ('committed', 'staged'):
                    self.git('add', '.')
                if layer == 'committed':
                    self.git('commit', '-qm', layer)
                if layer == 'unstaged':
                    self.write('scripts/old.txt', 'changed')
                code, data = self.run_check()
                self.assertEqual(code, 0)
                self.assertEqual(data['applicability'], 'applicable')
                self.assertIn('scripts/' + layer + '.txt', data['changedPaths'])
                if layer == 'unstaged':
                    self.assertIn('scripts/old.txt', data['changedPaths'])
                self.assertEqual((self.root / '.git/parity-ran').read_text(), str(self.root))

    def test_rename_out_of_prefix_and_deletion_are_in_scope(self):
        self.parity()
        self.git('mv', 'scripts/old.txt', 'app/renamed.txt')
        self.git('commit', '-qm', 'rename out')
        code, data = self.run_check()
        self.assertEqual(code, 0)
        self.assertIn('scripts/old.txt', data['matchingPaths'])
        self.assertIn('app/renamed.txt', data['changedPaths'])

    def test_nul_paths(self):
        self.parity()
        self.write('scripts/new\nquoted" file.txt', 'x')
        code, data = self.run_check()
        self.assertEqual(code, 0)
        self.assertIn('scripts/new\nquoted" file.txt', data['matchingPaths'])

    def test_missing_parent_fails_closed(self):
        self.state.unlink()
        code, data = self.run_check()
        self.assertEqual(code, 20)
        self.assertEqual(data['applicability'], 'unknown')

    def test_invalid_or_wrong_identity_fails_closed(self):
        for fields in ({'parentBranch': 'missing'}, {'parentBranch': 'HEAD'}, {'currentBranch': 'other'}, {'phaseSlug': 'other'}):
            with self.subTest(fields=fields):
                state = {'parentBranch': 'integration', 'currentBranch': 'phase', 'phaseSlug': 'example'}
                state.update(fields)
                self.state.write_text(json.dumps(state))
                code, data = self.run_check()
                self.assertEqual(code, 20)
                self.assertEqual(data['applicability'], 'unknown')

    def test_invalid_manifest_fails_closed(self):
        for content in ('{', '[]', '{}', '{"pathPrefixes": []}', '{"pathPrefixes": [""]}', '{"pathPrefixes": ["../"]}', '{"pathPrefixes": "scripts/"}'):
            with self.subTest(content=content):
                self.manifest.write_text(content)
                code, data = self.run_check()
                self.assertEqual(code, 20)
                self.assertEqual(data['applicability'], 'unknown')

    def test_consumer_cannot_override_runtime_manifest(self):
        self.parity(7)
        self.write('scripts/change.txt', 'x')
        malicious = self.base / 'override.json'
        malicious.write_text('{"pathPrefixes": ["unrelated/"]}')
        self.env['BUILD_CHAIN_PATHS_MANIFEST'] = str(malicious)
        code, data = self.run_check()
        self.assertEqual(code, 20)
        self.assertEqual(data['parityExitCode'], 7)

    def test_actual_parity_failure(self):
        shutil.copy2(SCRIPTS / 'build-chain-sync.py', self.root / 'scripts/build-chain-sync.py')
        shutil.copytree(SCRIPTS / '_sw', self.root / 'scripts/_sw')
        code, data = self.run_check()
        self.assertEqual(code, 20)
        self.assertEqual(data['applicability'], 'applicable')
        self.assertNotEqual(data['parityExitCode'], 0)

    def test_deleted_build_path(self):
        self.parity()
        self.git('rm', 'scripts/old.txt')
        code, data = self.run_check()
        self.assertEqual(code, 0)
        self.assertIn('scripts/old.txt', data['matchingPaths'])

    def test_ambiguous_parent_namespace(self):
        self.git('update-ref', 'refs/remotes/integration', 'HEAD')
        code, data = self.run_check()
        self.assertEqual(code, 20)
        self.assertEqual(data['applicability'], 'unknown')

    def test_fully_qualified_current_branch_cannot_erase_committed_scope(self):
        self.write('scripts/committed.txt', 'build-chain change')
        self.git('add', '.')
        self.git('commit', '-qm', 'committed build-chain change')
        state = json.loads(self.state.read_text())
        state['parentBranch'] = 'refs/heads/phase'
        self.state.write_text(json.dumps(state))
        code, data = self.run_check()
        self.assertEqual(code, 20)
        self.assertEqual(data['applicability'], 'unknown')

    def test_symbolic_remote_alias_of_current_branch_fails_closed(self):
        self.write('scripts/committed.txt', 'build-chain change')
        self.git('add', '.')
        self.git('commit', '-qm', 'committed build-chain change')
        self.git('symbolic-ref', 'refs/remotes/origin/alias', 'refs/heads/phase')
        state = json.loads(self.state.read_text())
        state['parentBranch'] = 'refs/remotes/origin/alias'
        self.state.write_text(json.dumps(state))
        code, data = self.run_check()
        self.assertEqual(code, 20)
        self.assertEqual(data['applicability'], 'unknown')

    def test_distinct_qualified_parent_at_same_commit_remains_valid(self):
        state = json.loads(self.state.read_text())
        state['parentBranch'] = 'refs/heads/integration'
        self.state.write_text(json.dumps(state))
        code, data = self.run_check()
        self.assertEqual(code, 0)
        self.assertEqual(data['applicability'], 'not-applicable')
        self.assertEqual(data['changedPaths'], [])

    def test_missing_manifest(self):
        self.manifest.unlink()
        code, data = self.run_check()
        self.assertEqual(code, 20)
        self.assertEqual(data['applicability'], 'unknown')

    def test_staged_and_worktree_cancellation(self):
        self.parity()
        self.write('scripts/old.txt', 'index change')
        self.git('add', 'scripts/old.txt')
        self.write('scripts/old.txt', 'base')
        code, data = self.run_check()
        self.assertEqual(code, 0)
        self.assertIn('scripts/old.txt', data['matchingPaths'])

    def test_standalone_legacy_runs_parity(self):
        proc = subprocess.run([sys.executable, str(self.runtime / 'scripts/ship-build-chain-check.py')], capture_output=True, env=self.env)
        self.assertEqual(proc.returncode, 20)

    def test_handler_real_execution_evidence(self):
        # Configuration/reference seam only: command, Git, parity, and evidence writes are real.
        manifest = json.loads((SCRIPTS.parent / 'core/sw-reference/gate-manifest.json').read_text())
        for scenario in ('clean', 'committed', 'missing-parent', 'parity-failure'):
            with self.subTest(scenario=scenario):
                if scenario == 'committed':
                    self.write('app/new.txt', 'x')
                    self.git('add', '.')
                    self.git('commit', '-qm', 'consumer change')
                if scenario == 'missing-parent':
                    self.state.unlink()
                if scenario == 'parity-failure':
                    self.state.write_text(json.dumps({'parentBranch': 'integration', 'currentBranch': 'phase', 'phaseSlug': 'example'}))
                    self.write('scripts/change.txt', 'x')
                run = self.base / ('run-' + scenario)
                run.mkdir()
                with patch.object(handlers, 'SCRIPT_DIR', self.runtime / 'scripts'), patch.object(handlers, 'load_manifest', return_value=manifest), patch.object(handlers, 'resolve_gate_class', return_value='mandatory'):
                    result = handlers.run_gate_handler(self.root, 'example', 'build-chain', run, env=self.env)
                self.assertEqual(result['verdict'], 'pass' if scenario in ('clean', 'committed') else 'fail')
                self.assertIn(str(self.root), result['execution']['argv'])
                self.assertTrue(result['artifactRefs'])
                artifact = json.loads(Path(result['artifactRefs'][0]).read_text())
                self.assertIn('applicability', artifact)
                self.assertEqual(result['record']['execution'], result['execution'])


if __name__ == '__main__':
    unittest.main()
