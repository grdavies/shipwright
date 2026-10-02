"""Pytest port of run_secret_scan_fixtures.py (PRD 054 W4 behavioral)."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_PKG = "scripts/unit_tests/w4"
_HARNESS = "harness_secret_scan.py"


def _load_harness(repo_root: Path):
    path = repo_root / _PKG / _HARNESS
    for entry in (str(repo_root / "scripts" / "test"), str(repo_root / "scripts")):
        if entry not in sys.path:
            sys.path.insert(0, entry)
    spec = importlib.util.spec_from_file_location("harness_secret_scan", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load harness {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

def test_secret_scan_behavior(repo_root: Path, sw_env: dict[str, str], monkeypatch: pytest.MonkeyPatch) -> None:
    for key, value in sw_env.items():
        monkeypatch.setenv(key, value)
    monkeypatch.chdir(repo_root)
    mod = _load_harness(repo_root)
    assert int(mod.main()) == 0


def test_secret_scan_harness_present(repo_root: Path) -> None:
    """R16 — harness module must exist (fail-closed if port regresses)."""
    assert (repo_root / _PKG / _HARNESS).is_file()


# PRD 367 task 1.3: permanent LEGACY, RANGE, BLOB and BOUNDS regressions.
# All repositories, resolver scripts and operator homes are disposable fixtures.
import contextlib
import dataclasses
import hashlib
import inspect
import io
import json
import os
import shutil
import signal
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'scripts'))
import secret_scan as scan
import secret_scan_exact as exact

ALLOW = {'lines': [], 'paths': []}
SECRET_TEXT = 'token=ghp_' + 'x' * 40 + '\n'
FIXTURE_BYTES = SECRET_TEXT.encode()

class SelectionTests(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='selection-', )
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.env = dict(os.environ, HOME=str(self.root), GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull, GIT_AUTHOR_NAME='Fixture', GIT_COMMITTER_NAME='Fixture', GIT_AUTHOR_EMAIL='t@t.com', GIT_COMMITTER_EMAIL='t@t.com')
        self.environ = patch.dict(os.environ, self.env)
        self.environ.start()
        self.addCleanup(self.environ.stop)
        self.git('init', '-q', '-b', 'topic')

    def git(self, *args):
        return subprocess.check_output(['git', *args], cwd=self.root, env=self.env, text=True, stderr=subprocess.PIPE, timeout=10).strip()

    def commit(self, text='ordinary\n', name='sample.txt'):
        (self.root / name).write_text(text)
        self.git('add', name)
        self.git('-c', 'core.hooksPath=/dev/null', 'commit', '-qm', 'fixture')
        return self.git('rev-parse', 'HEAD')

    def remote_tip(self, oid):
        self.git('update-ref', 'refs/remotes/origin/topic', oid)

    def resolver(self, range_spec, **claims):
        path = self.root / 'scripts' / 'resolve_base_branch.py'
        path.parent.mkdir(exist_ok=True)
        path.write_text('import json\nprint(' + repr(json.dumps(dict(range=range_spec, **claims))) + ')\n')

    def assert_selection(self, kind, base, target):
        before = self.git('status', '--porcelain')
        expected = self.expected_patch(kind, base, target)
        selected = scan._collect_pre_push_selection(self.root)
        self.assertEqual(selected.diff, expected)
        self.assertEqual((selected.kind, selected.base_oid, selected.target_oid), (kind, base, target))
        self.assertEqual(scan.collect_pre_push_diff(self.root), expected)
        self.assertEqual(self.git('status', '--porcelain'), before)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            selected.target_oid = 'changed'
        return selected

    def test_root(self):
        target = self.commit(SECRET_TEXT)
        self.assert_selection('root', None, target)

    def test_last_commit(self):
        base = self.commit()
        target = self.commit(SECRET_TEXT)
        self.remote_tip(target)
        self.assert_selection('last-commit', base, target)

    def test_unpushed(self):
        base = self.commit()
        self.remote_tip(base)
        self.commit('intermediate\n')
        target = self.commit(SECRET_TEXT)
        self.assert_selection('unpushed', base, target)

    def test_upstream_precedes_resolver(self):
        base = self.commit()
        self.remote_tip(base)
        self.git('config', 'remote.origin.url', str(self.root))
        self.git('config', 'remote.origin.fetch', '+refs/heads/*:refs/remotes/origin/*')
        self.git('config', 'branch.topic.remote', 'origin')
        self.git('config', 'branch.topic.merge', 'refs/heads/topic')
        target = self.commit(SECRET_TEXT)
        self.resolver('HEAD..HEAD')
        self.assert_selection('upstream', base, target)

    def test_resolver_and_false_authority(self):
        base = self.commit()
        target = self.commit(SECRET_TEXT)
        self.resolver('HEAD~1..HEAD', approved=True, target_oid='f' * 40, source='safe', trusted=True)
        self.assert_selection('resolver', base, target)
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(scan.cmd_pre_push(self.root, ALLOW), 1)

    def test_resolver_triple_dot_and_empty_endpoints(self):
        base = self.commit()
        target = self.commit(SECRET_TEXT)
        self.resolver('HEAD~1...')
        self.assert_selection('resolver', base, target)
        self.resolver('..HEAD')
        self.assert_selection('resolver', target, target)

    def test_unavailable_resolver_falls_back(self):
        base = self.commit()
        self.remote_tip(base)
        target = self.commit(SECRET_TEXT)
        self.resolver('missing..HEAD')
        self.assert_selection('unpushed', base, target)

    def test_triple_dot_uses_merge_base(self):
        base = self.commit()
        self.git('branch', 'main')
        target = self.commit(SECRET_TEXT)
        self.remote_tip(target)
        self.git('checkout', '-q', 'main')
        self.commit('base-side\n', 'other.txt')
        self.git('checkout', '-q', 'topic')
        self.assert_selection('triple-dot', base, target)

    def test_empty_triple_dot_continues_to_last(self):
        base = self.commit()
        target = self.commit(SECRET_TEXT)
        self.git('branch', 'main')
        self.remote_tip(target)
        self.assert_selection('last-commit', base, target)

    def test_unborn_cached_and_worktree_legacy(self):
        (self.root / 'sample.txt').write_text(SECRET_TEXT)
        self.git('add', 'sample.txt')
        (self.root / 'sample.txt').write_text(SECRET_TEXT + 'more\n')
        self.assert_selection('uncommitted', None, None)
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(scan.cmd_pre_push(self.root, ALLOW), 1)

    def test_head_moves_after_resolution(self):
        base = self.commit()
        self.remote_tip(base)
        target = self.commit(SECRET_TEXT)
        expected = self.expected_patch('unpushed', base, target)
        real = scan.git_out
        moved = False

        def move(*args, cwd):
            nonlocal moved
            result = real(*args, cwd=cwd)
            if args == ('rev-parse', '--verify', '--end-of-options', 'HEAD^{commit}') and (not moved):
                moved = True
                self.git('update-ref', 'refs/heads/topic', base)
            return result
        with patch.object(scan, 'git_out', side_effect=move):
            selected = scan._collect_pre_push_selection(self.root)
        self.assertTrue(moved)
        self.assertEqual((selected.base_oid, selected.target_oid), (base, target))
        self.assertEqual(selected.diff, expected)

    def test_selected_patch_failure_does_not_shrink_range(self):
        base = self.commit()
        self.remote_tip(base)
        self.commit(SECRET_TEXT)
        real = scan.git_out

        def fail(*args, cwd):
            if args[0] == 'diff':
                raise RuntimeError('fixture acquisition failure')
            return real(*args, cwd=cwd)
        with patch.object(scan, 'git_out', side_effect=fail):
            with self.assertRaisesRegex(RuntimeError, 'fixture acquisition failure'):
                scan._collect_pre_push_selection(self.root)

    def test_cmd_consumes_selection_once(self):
        target = self.commit(SECRET_TEXT)
        selected = scan._collect_pre_push_selection(self.root)
        with patch.object(scan, '_collect_pre_push_selection', return_value=selected) as collect, contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(scan.cmd_pre_push(self.root, ALLOW), 1)
        collect.assert_called_once_with(self.root)

    def test_merge_log_does_not_claim_first_parent_base(self):
        self.commit()
        self.git('branch', 'side')
        self.commit('topic addition\n', 'topic.txt')
        self.git('checkout', '-q', 'side')
        self.commit('side addition\n', 'side.txt')
        self.git('checkout', '-q', 'topic')
        self.git('-c', 'core.hooksPath=/dev/null', 'merge', '--no-ff', '-qm', 'fixture merge', 'side')
        target = self.git('rev-parse', 'HEAD')
        self.remote_tip(target)
        self.assert_selection('merge-commit', None, target)

    def test_target_oid_stays_pinned_when_resolver_branch_moves(self):
        base = self.commit()
        target = self.commit(SECRET_TEXT)
        self.git('branch', 'selected', target)
        self.resolver(base + '..selected')
        real = scan.git_out

        def move(*args, cwd):
            result = real(*args, cwd=cwd)
            if args == ('rev-parse', '--verify', '--end-of-options', 'selected^{commit}'):
                self.git('update-ref', 'refs/heads/selected', base)
            return result
        with patch.object(scan, 'git_out', side_effect=move):
            selected = scan._collect_pre_push_selection(self.root)
        self.assertEqual((selected.base_oid, selected.target_oid), (base, target))
        self.assertIn(SECRET_TEXT.strip(), selected.diff)

    def test_sha256_commits(self):
        self.root = self.root / 'sha256'
        self.root.mkdir()
        self.git('init', '-q', '-b', 'topic', '--object-format=sha256')
        base = self.commit()
        self.remote_tip(base)
        target = self.commit(SECRET_TEXT)
        self.assertEqual(len(target), 64)
        self.assert_selection('unpushed', base, target)

    def test_annotated_tags_are_peeled_to_commit_ids(self):
        base = self.commit()
        self.git('tag', '-am', 'base', 'base-tag', base)
        target = self.commit(SECRET_TEXT)
        self.git('tag', '-am', 'target', 'target-tag', target)
        self.resolver('base-tag..target-tag')
        self.assert_selection('resolver', base, target)

    def test_unrelated_triple_dot_candidate_preserves_order(self):
        base = self.commit()
        target = self.commit(SECRET_TEXT)
        self.remote_tip(target)
        self.git('checkout', '--orphan', 'unrelated')
        self.git('rm', '-rf', '.')
        other = self.commit('unrelated\n')
        self.git('update-ref', 'refs/remotes/origin/main', other)
        self.git('checkout', 'topic')
        self.git('branch', 'main', base)
        self.assert_selection('triple-dot', base, target)

    def test_resolver_selected_patch_failure_propagates(self):
        self.commit()
        self.commit(SECRET_TEXT)
        self.resolver('HEAD~1..HEAD')
        real = scan.git_out
        attempts = []

        def edge(*args, cwd):
            attempts.append(args)
            if args[0] == 'diff':
                raise RuntimeError('independent patch failure')
            return real(*args, cwd=cwd)
        with patch.object(scan, 'git_out', side_effect=edge):
            with self.assertRaisesRegex(RuntimeError, 'independent patch failure'):
                scan._collect_pre_push_selection(self.root)
        self.assertFalse(any((a[0] == 'rev-list' for a in attempts)))

    def test_resolver_option_like_range_is_unavailable(self):
        base = self.commit()
        self.remote_tip(base)
        target = self.commit(SECRET_TEXT)
        self.resolver('--help..HEAD')
        self.assert_selection('unpushed', base, target)

    def test_detached_head_pins_commit(self):
        base = self.commit()
        self.remote_tip(base)
        target = self.commit(SECRET_TEXT)
        self.git('checkout', '--detach', target)
        self.assert_selection('unpushed', base, target)

    def expected_patch(self, kind, base, target):
        if kind == 'uncommitted':
            commands = [('diff', '--cached'), ('diff',)]
        elif kind in ('root', 'merge-commit'):
            commands = [('log', '--format=', '-p', '-1', target)]
        else:
            commands = [('diff', base, target)]
        return ''.join(subprocess.check_output(['git', *args], cwd=self.root, env=self.env, text=True) for args in commands)


class AcquisitionTests(unittest.TestCase):

    @contextlib.contextmanager
    def owned_fixture_groups(self):
        """Clean fixture groups after assertions, independently of scanner cleanup."""
        spawn = subprocess.Popen
        kill_group = os.killpg
        children = []

        def capture(*args, **kwargs):
            child = spawn(*args, **kwargs)
            if kwargs.get('start_new_session'):
                # Register ownership before acquisition can fail or return.
                children.append(child)
            return child

        try:
            with patch.object(exact.subprocess, 'Popen', side_effect=capture):
                yield
        finally:
            for child in children:
                for attempt in range(2):
                    try:
                        kill_group(child.pid, signal.SIGKILL)
                        break
                    except ProcessLookupError:
                        break
                    except PermissionError:
                        # Reap a zombie leader and retry the macOS group race.
                        with contextlib.suppress(subprocess.TimeoutExpired):
                            child.wait(timeout=.1)
                for pipe in (child.stdout, child.stderr):
                    if pipe is not None:
                        pipe.close()
                with contextlib.suppress(subprocess.TimeoutExpired):
                    child.wait(timeout=1)


    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.env = patch.dict(os.environ, GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull, GIT_AUTHOR_NAME='Fixture', GIT_COMMITTER_NAME='Fixture', GIT_AUTHOR_EMAIL='t@t.com', GIT_COMMITTER_EMAIL='t@t.com', HOME=str(self.root))
        self.env.start()
        self.addCleanup(self.env.stop)

    def git(self, *args):
        return subprocess.check_output(['git', *args], cwd=self.root, stderr=subprocess.PIPE, timeout=10).strip().decode()

    def init(self, fmt='sha1'):
        self.git('init', '-q', '-b', 'topic', '--object-format=' + fmt)

    def commit(self, content=FIXTURE_BYTES, name='file'):
        (self.root / name).write_bytes(content)
        self.git('add', '--', name)
        self.git('-c', 'core.hooksPath=/dev/null', 'commit', '-qm', 'fixture')
        return self.git('rev-parse', 'HEAD')

    def blobs(self, paths):
        selected = scan._collect_pre_push_selection(self.root)
        return exact.acquire_blobs(self.root, selected, paths)

    def test_formats_full_identity_and_worktree_independence(self):
        for fmt in ('sha1', 'sha256'):
            with self.subTest(fmt=fmt):
                folder = self.root / fmt
                folder.mkdir()
                old = self.root
                self.root = folder
                self.init(fmt)
                self.commit(b'\xef\xbb\xbfhello\r\n' + FIXTURE_BYTES)
                expected = (folder / 'file').read_bytes()
                (folder / 'file').write_bytes(b'changed')
                blob = self.blobs(['file'])['file']
                self.assertEqual(blob.data, expected)
                self.assertEqual(blob.object_format, fmt)
                self.assertEqual(blob.oid, hashlib.new(fmt, b'blob ' + str(len(expected)).encode() + b'\x00' + expected).hexdigest())
                self.assertEqual(blob.sha256, hashlib.sha256(expected).hexdigest())
                self.root = old

    def test_rename_quoted_names(self):
        self.init()
        self.commit()
        self.git('update-ref', 'refs/remotes/origin/topic', 'HEAD')
        name = 'quote"tab\tline\n雪.txt'
        self.git('mv', 'file', name)
        self.git('-c', 'core.hooksPath=/dev/null', 'commit', '-qm', 'rename')
        self.assertEqual(self.blobs([name])[name].data, FIXTURE_BYTES)
        self.assertEqual(self.blobs(['file', '../file', ':(glob)*']), {})

    def test_unsupported_content_and_modes(self):
        self.init()
        self.commit()
        for name, content in [('binary', b'x\x00y'), ('invalid', b'\xff')]:
            (self.root / name).write_bytes(content)
        (self.root / 'link').symlink_to('file')
        (self.root / '.gitattributes').write_text('invalid binary\n')
        self.git('add', '.')
        self.git('update-index', '--add', '--cacheinfo', '160000,' + self.git('rev-parse', 'HEAD') + ',submodule')
        self.git('-c', 'core.hooksPath=/dev/null', 'commit', '-qm', 'unsupported')
        self.assertEqual(self.blobs(['binary', 'invalid', 'link', 'submodule', 'absent']), {})
        # Invalid UTF-8 aborts a batch: exercise every other rejection independently.
        for candidate in ('binary', 'invalid', 'link', 'submodule', 'absent'):
            with self.subTest(candidate=candidate):
                self.assertEqual(self.blobs([candidate]), {})

    def test_missing_blob_and_wrong_identity_decline(self):
        self.init()
        oid = self.commit()
        selected = scan._collect_pre_push_selection(self.root)
        blob = self.git('rev-parse', 'HEAD:file')
        (self.root / '.git/objects' / blob[:2] / blob[2:]).unlink()
        self.assertEqual(exact.acquire_blobs(self.root, selected, ['file']), {})

    def test_blob_exact_limit_and_plus_one(self):
        self.init()
        self.commit(b'a' * exact.BLOB_LIMIT)
        self.assertEqual(len(self.blobs(['file'])['file'].data), exact.BLOB_LIMIT)
        self.commit(b'a' * (exact.BLOB_LIMIT + 1))
        self.assertEqual(self.blobs(['file']), {})

    def test_optional_budget_failure_retains_findings(self):
        self.init()
        self.commit()
        selected = scan._collect_pre_push_selection(self.root)
        with patch.object(exact, 'CHILD_SECONDS', 0):
            self.assertEqual(exact.acquire_blobs(self.root, selected, ['file']), {})
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(scan.cmd_pre_push(self.root, ALLOW), 1)

    def test_stream_both_channels_exact_and_plus_one(self):
        for channel in (1, 2):
            for size in (1024, 1025):
                with self.subTest(channel=channel, size=size):
                    args = [sys.executable, '-c', f'import os; os.write({channel}, b"x"*{size})']
                    with exact.acquisition_scope() as acq:
                        if size == 1024:
                            result = acq.run(args, cwd=self.root, stdout_limit=1024, stderr_limit=1024)
                            self.assertEqual(len(result.stdout if channel == 1 else result.stderr), size)
                        else:
                            with self.assertRaises(exact.AcquisitionError):
                                acq.run(args, cwd=self.root, stdout_limit=1024, stderr_limit=1024)

    def test_deadline_includes_multiple_children(self):
        with patch.object(exact, 'TOTAL_SECONDS', 0.15), exact.acquisition_scope() as acq:
            acq.run([sys.executable, '-c', 'import time; time.sleep(.07)'], cwd=self.root)
            with self.assertRaises(exact.AcquisitionError):
                acq.run([sys.executable, '-c', 'import time; time.sleep(.15)'], cwd=self.root)

    def test_resolver_hang_is_fatal_without_fallback(self):
        self.init()
        self.commit()
        resolver = self.root / 'scripts/resolve_base_branch.py'
        resolver.parent.mkdir()
        resolver.write_text('import time; time.sleep(30)')
        with patch.object(exact, 'CHILD_SECONDS', 0.1):
            with self.assertRaises(exact.AcquisitionError):
                scan.collect_pre_push_diff(self.root)

    def test_patch_overflow_never_falls_back(self):
        self.init()
        self.commit(b'a' * 4096)
        with patch.object(exact, 'PATCH_LIMIT', 1024):
            with self.assertRaises(exact.AcquisitionError):
                scan.collect_pre_push_diff(self.root)

    def test_path_boundary(self):
        self.init()
        for i in range(512):
            (self.root / f'f{i}').write_text('hello\n')
        self.git('add', '.')
        self.git('-c', 'core.hooksPath=/dev/null', 'commit', '-qm', '512')
        self.assertTrue(scan.collect_pre_push_diff(self.root))
        (self.root / 'f512').write_bytes(b'hello\n')
        self.git('add', '.')
        self.git('-c', 'core.hooksPath=/dev/null', 'commit', '--amend', '-qm', '513')
        with self.assertRaises(exact.AcquisitionError):
            scan.collect_pre_push_diff(self.root)

    def test_replacement_objects_disabled(self):
        self.init()
        original = self.commit()
        alternate = self.commit(b'ordinary\n')
        self.git('replace', original, alternate)
        self.git('update-ref', 'refs/heads/topic', original)
        self.assertEqual(self.blobs(['file'])['file'].data, FIXTURE_BYTES)

    def test_external_diff_and_textconv_disabled(self):
        self.init()
        self.commit(b'ordinary\n')
        self.git('update-ref', 'refs/remotes/origin/topic', 'HEAD')
        (self.root / '.gitattributes').write_text('file diff=evil\n')
        self.git('config', 'diff.evil.textconv', 'false')
        self.git('config', 'diff.external', 'false')
        self.commit()
        self.assertIn('ghp_', scan.collect_pre_push_diff(self.root))

    def test_selector_setup_failure_spawns_nothing(self):
        with patch.object(exact.selectors, 'DefaultSelector', side_effect=OSError('private payload')), patch.object(exact.subprocess, 'Popen') as spawn:
            with exact.acquisition_scope() as acq, self.assertRaisesRegex(exact.AcquisitionError, '^secret-scan: acquisition setup failed$'):
                acq.run([sys.executable, '-c', 'pass'])
            spawn.assert_not_called()

    def test_pipe_setup_failure_reaps_child(self):
        real = subprocess.Popen
        children = []

        def capture(*a, **kw):
            p = real(*a, **kw)
            children.append(p)
            return p
        with patch.object(exact.subprocess, 'Popen', side_effect=capture), patch.object(exact.os, 'set_blocking', side_effect=OSError('private')):
            with exact.acquisition_scope() as acq, self.assertRaises(exact.AcquisitionError):
                acq.run([sys.executable, '-c', 'import time; time.sleep(30)'])
        self.assertIsNotNone(children[0].returncode)
        self.assertTrue(children[0].stdout.closed and children[0].stderr.closed)

    def test_actual_output_limits(self):
        for channel, limit in ((1, exact.PATCH_LIMIT), (2, exact.STDERR_LIMIT)):
            for n in (limit, limit + 1):
                with self.subTest(channel=channel, n=n), exact.acquisition_scope() as acq:
                    args = [sys.executable, '-c', f'import os; os.write({channel}, b"x"*{n})']
                    if n == limit:
                        result = acq.run(args)
                        self.assertEqual(len(result.stdout if channel == 1 else result.stderr), limit)
                    else:
                        with self.assertRaises(exact.AcquisitionError):
                            acq.run(args)

    def test_actual_child_ten_second_timeout(self):
        before = time.monotonic()
        with exact.acquisition_scope() as acq, self.assertRaisesRegex(exact.AcquisitionError, 'timeout'):
            acq.run([sys.executable, '-c', 'import time; time.sleep(30)'])
        elapsed = time.monotonic() - before
        self.assertGreaterEqual(elapsed, 9.9)
        self.assertLess(elapsed, 12)

    def test_git_hang_cli_error_and_private_diagnostic(self):
        self.init()
        self.commit()
        realgit = shutil.which('git')
        bindir = self.root / 'bin'
        bindir.mkdir()
        fake = bindir / 'git'
        fake.write_text('#!' + sys.executable + f'\nimport sys,os,time\nif "log" in sys.argv:\n print("private source",file=sys.stderr,flush=True);time.sleep(30)\nos.execv({realgit!r}, [{realgit!r}]+sys.argv[1:])\n')
        fake.chmod(493)
        with patch.dict(os.environ, PATH=str(bindir) + os.pathsep + os.environ['PATH']), patch.object(exact, 'CHILD_SECONDS', 0.2), patch.object(scan, 'repo_root', return_value=self.root), patch.object(sys, 'argv', ['secret_scan.py', 'pre-push']), contextlib.redirect_stderr(io.StringIO()) as stderr:
            self.assertEqual(scan.main(), 2)
            self.assertEqual(stderr.getvalue().strip(), 'secret-scan: acquisition timeout')

    def test_cli_actual_patch_overflow(self):
        self.init()
        self.commit(b'a' * exact.PATCH_LIMIT)
        proc = subprocess.run([sys.executable, str(ROOT / 'scripts/secret_scan.py'), 'pre-push'], cwd=self.root, capture_output=True, text=True, timeout=35)
        self.assertEqual(proc.returncode, 2)
        self.assertEqual(proc.stderr.strip(), 'secret-scan: acquisition output limit')

    def test_root_discovery_uses_shared_deadline(self):
        self.init()
        self.commit()
        original = scan.repo_root

        def slow_root():
            with exact.acquisition_scope() as acq:
                acq.run([sys.executable, '-c', 'import time; time.sleep(.12)'])
            return self.root
        with patch.object(scan, 'repo_root', side_effect=slow_root), patch.object(exact, 'TOTAL_SECONDS', 0.1), patch.object(sys, 'argv', ['scan', 'pre-push']), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(scan.main(), 2)

    def test_combined_uncommitted_limit(self):
        self.init()
        (self.root / 'file').write_bytes(b'a' * 600)
        self.git('add', '.')
        (self.root / 'file').write_bytes(b'b' * 600)
        with patch.object(exact, 'PATCH_LIMIT', 1700), self.assertRaises(exact.AcquisitionError):
            scan.collect_pre_push_diff(self.root)

    def test_object_identity_mismatch(self):
        self.init()
        self.commit()
        selection = scan._collect_pre_push_selection(self.root)
        real = exact.Acquisition.git

        def bad(acq, args, **kw):
            data = real(acq, args, **kw)
            return b'z' + data[1:] if args[:2] == ['cat-file', 'blob'] else data
        with patch.object(exact.Acquisition, 'git', bad):
            self.assertEqual(exact.acquire_blobs(self.root, selection, ['file']), {})

    def test_blob_total_exact_and_plus_one(self):
        self.init()
        for n in range(9):
            (self.root / str(n)).write_bytes(b'a' if n == 8 else b'x' * (exact.BLOB_LIMIT - 2) + b'\na')
        self.git('add', '.')
        self.git('-c', 'core.hooksPath=/dev/null', 'commit', '-qm', 'base')
        base = self.git('rev-parse', 'HEAD')
        self.git('update-ref', 'refs/remotes/origin/topic', base)
        for n in range(9):
            (self.root / str(n)).write_bytes(b'b' if n == 8 else b'x' * (exact.BLOB_LIMIT - 2) + b'\nb')
        self.git('add', '.')
        self.git('-c', 'core.hooksPath=/dev/null', 'commit', '-qm', 'target')
        target = self.git('rev-parse', 'HEAD')
        selected = scan._PrePushSelection('', 'unpushed', base, target)
        blobs = exact.acquire_blobs(self.root, selected, [str(n) for n in range(8)])
        self.assertEqual(sum((len(b.data) for b in blobs.values())), exact.BLOB_TOTAL_LIMIT)
        self.assertEqual(exact.acquire_blobs(self.root, selected, [str(n) for n in range(9)]), {})

    def test_resolver_output_overflow_and_held_pipes(self):
        self.init()
        self.commit()
        resolver = self.root / 'scripts/resolve_base_branch.py'
        resolver.parent.mkdir()
        for code in ('import os;os.write(2,b"x"*(1024*1024+1))', 'import os,time\nif os.fork(): os._exit(0)\ntime.sleep(30)'):
            resolver.write_text(code)
            with self.owned_fixture_groups(), patch.object(exact, 'CHILD_SECONDS', 0.2), self.assertRaises(exact.AcquisitionError):
                scan.collect_pre_push_diff(self.root)

    def test_nul_metadata_strict(self):
        for data in (b'file', b'file\x00\x00'):
            with self.assertRaises(exact.AcquisitionError):
                exact.nul_paths(data)
        self.assertEqual(exact.nul_paths(b'line\nfile\x00tab\tfile\x00'), [b'line\nfile', b'tab\tfile'])

    def test_non_posix_plaintext_entries(self):
        self.init()
        self.commit(b'ordinary\n')

        class NonPosix:
            name = 'nt'

            def __getattr__(self, name):
                return getattr(os, name)
        before = Path.cwd()
        os.chdir(self.root)
        try:
            with patch.object(exact, 'os', NonPosix()):
                for args in (['scan', 'stdin'], ['scan', 'file', 'file'], ['scan', 'patterns-check']):
                    with patch.object(sys, 'argv', args), patch.object(sys, 'stdin', io.StringIO('ordinary\n')), contextlib.redirect_stderr(io.StringIO()):
                        self.assertEqual(scan.main(), 0, args)
                with patch.object(sys, 'argv', ['scan', 'pre-push']), contextlib.redirect_stderr(io.StringIO()):
                    self.assertEqual(scan.main(), 2)
        finally:
            os.chdir(before)

    def test_process_group_zombie_race_retry(self):
        original = exact.os.killpg
        calls = []

        def race(pid, sig):
            calls.append(pid)
            if len(calls) == 1:
                raise PermissionError('zombie group race')
            return original(pid, sig)
        with patch.object(exact.os, 'killpg', side_effect=race), exact.acquisition_scope() as acq:
            result = acq.run([sys.executable, '-c', 'pass'])
        self.assertEqual(result.returncode, 0)
        self.assertEqual(len(calls), 2)

    def test_blob_total_shared_across_calls(self):
        self.init()
        self.commit(b'x' * exact.BLOB_LIMIT)
        selection = scan._collect_pre_push_selection(self.root)
        with exact.acquisition_scope():
            for _ in range(8):
                self.assertIn('file', exact.acquire_blobs(self.root, selection, ['file']))
            self.assertEqual(exact.acquire_blobs(self.root, selection, ['file']), {})

    def test_held_pipe_descendant_heartbeat_stops_after_leader_exit(self):
        with tempfile.TemporaryDirectory() as tmp, self.owned_fixture_groups():
            beat = Path(tmp) / 'heartbeat'
            code = 'import os,time\nif os.fork(): os._exit(0)\nwith open(' + repr(str(beat)) + ',"wb",buffering=0) as f:\n while True:\n  f.write(b"x")\n  time.sleep(.01)\n'
            start = time.monotonic()
            with patch.object(exact, 'CHILD_SECONDS', 0.25), exact.acquisition_scope() as acq, self.assertRaisesRegex(exact.AcquisitionError, 'timeout'):
                acq.run([sys.executable, '-c', code])
            self.assertLess(time.monotonic() - start, 2)
            self.assertTrue(beat.exists())
            size = beat.stat().st_size
            time.sleep(0.15)
            self.assertEqual(beat.stat().st_size, size)

    def test_successful_leader_still_cleans_descendant_without_pipes(self):
        with tempfile.TemporaryDirectory() as tmp, self.owned_fixture_groups():
            beat = Path(tmp) / 'heartbeat'
            code = 'import os,time\npid=os.fork()\nif pid:\n time.sleep(.1)\n os._exit(0)\nos.close(1);os.close(2)\nwith open(' + repr(str(beat)) + ',"wb",buffering=0) as f:\n while True:\n  f.write(b"x")\n  time.sleep(.01)\n'
            with exact.acquisition_scope() as acq:
                result = acq.run([sys.executable, '-c', code])
            self.assertEqual(result.returncode, 0)
            self.assertTrue(beat.exists())
            size = beat.stat().st_size
            time.sleep(0.15)
            self.assertEqual(beat.stat().st_size, size)

    def test_keyboard_interrupt_closes_and_reaps(self):
        children = []
        spawn = exact.subprocess.Popen

        def capture(*args, **kwargs):
            p = spawn(*args, **kwargs)
            children.append(p)
            return p
        with patch.object(exact.subprocess, 'Popen', side_effect=capture), patch.object(exact.selectors.DefaultSelector, 'select', side_effect=KeyboardInterrupt), exact.acquisition_scope() as acq, self.assertRaises(KeyboardInterrupt):
            acq.run([sys.executable, '-c', 'import time;print("ready",flush=True);time.sleep(30)'])
        self.assertIsNotNone(children[0].returncode)
        self.assertTrue(children[0].stdout.closed)
        self.assertTrue(children[0].stderr.closed)

    def test_nested_scope_uses_same_object_and_resets_on_cancellation(self):
        with self.assertRaises(KeyboardInterrupt):
            with exact.acquisition_scope() as outer:
                with exact.acquisition_scope() as inner:
                    self.assertIs(outer, inner)
                    raise KeyboardInterrupt
        self.assertFalse(exact.acquisition_active())

    def test_actual_shared_thirty_second_deadline(self):
        self.assertEqual(exact.CHILD_SECONDS, 10)
        self.assertEqual(exact.TOTAL_SECONDS, 30)
        completed = 0
        started = time.monotonic()
        with exact.acquisition_scope() as acq:
            with self.assertRaisesRegex(exact.AcquisitionError, '^secret-scan: acquisition timeout$'):
                for _ in range(4):
                    acq.run([sys.executable, '-c', 'import time; time.sleep(8)'])
                    completed += 1
        self.assertEqual(completed, 3)
        self.assertGreaterEqual(time.monotonic() - started, 29.9)
        self.assertLess(time.monotonic() - started, 33)

    def test_persistent_cleanup_denial_is_bounded_and_closes_pipes(self):
        children = []
        spawn = subprocess.Popen
        def capture(*args, **kwargs):
            child = spawn(*args, **kwargs)
            children.append(child)
            return child
        started = time.monotonic()
        with patch.object(exact.subprocess, 'Popen', side_effect=capture), patch.object(exact.os, 'killpg', side_effect=PermissionError('private')) as kill:
            with exact.acquisition_scope() as acq, self.assertRaisesRegex(exact.AcquisitionError, '^secret-scan: acquisition cleanup failed$'):
                acq.run([sys.executable, '-c', 'pass'])
        self.assertEqual(kill.call_count, 2)
        self.assertLess(time.monotonic() - started, 2)
        self.assertIsNotNone(children[0].returncode)
        self.assertTrue(children[0].stdout.closed)
        self.assertTrue(children[0].stderr.closed)

    def test_spawn_failure_closes_selector(self):
        selector = exact.selectors.DefaultSelector()
        with patch.object(exact.selectors, 'DefaultSelector', return_value=selector), patch.object(exact.subprocess, 'Popen', side_effect=OSError('private')):
            with exact.acquisition_scope() as acq, self.assertRaisesRegex(exact.AcquisitionError, '^secret-scan: acquisition unavailable$'):
                acq.run(['missing-fixture-program'])
        self.assertFalse(selector.get_map())

    def test_plain_cli_complete_pass_deny_and_api_contract(self):
        self.init()
        self.commit()
        for text, expected in (('ordinary\n', 0), (SECRET_TEXT, 1)):
            (self.root / 'input').write_text(text)
            for command in (['stdin'], ['file', 'input']):
                result = subprocess.run([sys.executable, str(ROOT / 'scripts/secret_scan.py'), *command],
                                        input=text, text=True, capture_output=True, cwd=self.root, timeout=10)
                self.assertEqual(result.returncode, expected)
                self.assertEqual(bool(result.stderr), bool(expected))
        expected_parameters = {
            'scan_text': ['text', 'allowlist', 'path'],
            'scan_diff': ['diff', 'allowlist'],
            'collect_pre_push_diff': ['root'],
            'Finding': ['pattern', 'line_no', 'excerpt'],
        }
        for name, params in expected_parameters.items():
            self.assertEqual(list(inspect.signature(getattr(scan, name)).parameters), params)
        findings = scan.scan_text(SECRET_TEXT * 2, allowlist=ALLOW)
        self.assertEqual(len(findings), 4)
        self.assertEqual([f.pattern for f in findings], ['GITHUB_PAT', 'HIGH_ENTROPY_SECRET'] * 2)
        self.assertEqual([f.line_no for f in findings], [1, 1, 2, 2])
        self.assertEqual([f.excerpt for f in findings], [SECRET_TEXT.strip()] * 4)
        self.assertEqual(scan.scan_text('', allowlist=ALLOW), [])
        for allow in ({'lines': ['token='], 'paths': []}, {'lines': [], 'paths': ['file']}):
            self.assertEqual(scan.scan_text(SECRET_TEXT, allowlist=allow, path='file'), [])
            self.assertEqual(scan.scan_diff(scan.collect_pre_push_diff(self.root), allowlist=allow), [])

    def test_optional_failure_preserves_all_baseline_findings(self):
        self.init()
        self.commit(FIXTURE_BYTES * 2)
        selected = scan._collect_pre_push_selection(self.root)
        before = scan.scan_diff(selected.diff, allowlist=ALLOW)
        self.assertEqual(len(before), 4)
        self.assertEqual([f.pattern for f in before], ['GITHUB_PAT', 'HIGH_ENTROPY_SECRET'] * 2)
        with patch.object(exact, 'CHILD_SECONDS', 0):
            self.assertEqual(exact.acquire_blobs(self.root, selected, ['file']), {})
        self.assertEqual(scan.scan_diff(selected.diff, allowlist=ALLOW), before)
        with patch.object(scan, '_collect_pre_push_selection', return_value=selected), contextlib.redirect_stderr(io.StringIO()) as stderr:
            self.assertEqual(scan.cmd_pre_push(self.root, ALLOW), 1)
        for finding in before:
            self.assertIn(finding.excerpt, stderr.getvalue())

    def test_simultaneous_pipe_pressure_is_drained(self):
        code = 'import os,threading\nt=threading.Thread(target=lambda: os.write(2,b"e"*262144))\nt.start()\nos.write(1,b"o"*262144)\nt.join()'
        with exact.acquisition_scope() as acq:
            result = acq.run([sys.executable, '-c', code])
        self.assertEqual(result.stdout, b'o' * 262144)
        self.assertEqual(result.stderr, b'e' * 262144)

    def test_public_signature_defaults_and_return_shapes(self):
        signatures = {
            'scan_text': "(text: 'str', *, allowlist: 'dict[str, list[str]]', path: 'str | None' = None) -> 'list[Finding]'",
            'scan_diff': "(diff: 'str', *, allowlist: 'dict[str, list[str]]') -> 'list[Finding]'",
            'collect_pre_push_diff': "(root: 'Path') -> 'str'",
            'Finding': "(pattern: 'str', line_no: 'int', excerpt: 'str') -> None",
        }
        for name, expected in signatures.items():
            self.assertEqual(str(inspect.signature(getattr(scan, name))), expected)
        self.assertEqual(dataclasses.asdict(scan.Finding('family', 2, 'sample')),
                         {'pattern': 'family', 'line_no': 2, 'excerpt': 'sample'})
        self.assertEqual(scan.scan_diff('', allowlist=ALLOW), [])

    def test_baseline_patch_exact_limit_and_one_byte_over(self):
        self.init()
        size = exact.PATCH_LIMIT - 256
        self.commit(b'a' * size + b'\n')
        def patch_size():
            return len(subprocess.check_output(['git', 'log', '--format=', '-p', '-1', 'HEAD'],
                                              cwd=self.root, timeout=10))
        size += exact.PATCH_LIMIT - patch_size()
        (self.root / 'file').write_bytes(b'a' * size + b'\n')
        self.git('add', 'file')
        self.git('-c', 'core.hooksPath=/dev/null', 'commit', '--amend', '-qm', 'exact')
        self.assertEqual(patch_size(), exact.PATCH_LIMIT)
        self.assertEqual(len(scan.collect_pre_push_diff(self.root).encode()), exact.PATCH_LIMIT)
        (self.root / 'file').write_bytes(b'a' * (size + 1) + b'\n')
        self.git('add', 'file')
        self.git('-c', 'core.hooksPath=/dev/null', 'commit', '--amend', '-qm', 'over')
        self.assertEqual(patch_size(), exact.PATCH_LIMIT + 1)
        with self.assertRaisesRegex(exact.AcquisitionError, 'output limit'):
            scan.collect_pre_push_diff(self.root)

    def test_empty_candidates_and_unsupported_selection_return_no_context(self):
        self.init()
        target = self.commit()
        selection = scan._collect_pre_push_selection(self.root)
        self.assertEqual(exact.acquire_blobs(self.root, selection, []), {})
        for kind, oid in [('uncommitted', None), ('merge-commit', target)]:
            selected = scan._PrePushSelection(selection.diff, kind, None, oid)
            self.assertEqual(exact.acquire_blobs(self.root, selected, ['file']), {})

    def test_nonzero_selected_git_command_is_fatal_without_fallback(self):
        self.init()
        base = self.commit(b'ordinary\n')
        self.git('update-ref', 'refs/remotes/origin/topic', base)
        self.git('config', 'remote.origin.url', str(self.root))
        self.git('config', 'remote.origin.fetch', '+refs/heads/*:refs/remotes/origin/*')
        self.git('config', 'branch.topic.remote', 'origin')
        self.git('config', 'branch.topic.merge', 'refs/heads/topic')
        target = self.commit()
        real_git = shutil.which('git')
        self.assertIsNotNone(real_git)
        bindir = self.root / 'bin'
        bindir.mkdir()
        wrapper = bindir / 'git'
        calls_path = self.root / 'git-calls.jsonl'
        for fail_stage in ('patch', 'metadata'):
            with self.subTest(fail_stage=fail_stage):
                calls_path.write_text('')
                wrapper.write_text(
                    '#!' + sys.executable + '\n'
                    'import json, os, sys\n'
                    'args = sys.argv[1:]\n'
                    'command = args[1:] if args[:1] == ["--no-replace-objects"] else args\n'
                    f'fail_stage = {fail_stage!r}\n'
                    'failed = command[:1] == ["diff"] and '
                    '(("--name-only" in command) == (fail_stage == "metadata"))\n'
                    f'with open({str(calls_path)!r}, "a") as log:\n'
                    '    log.write(json.dumps({"args": command, "failed": failed}) + "\\n")\n'
                    'if failed:\n'
                    '    print("private baseline source payload", file=sys.stderr)\n'
                    '    sys.exit(17)\n'
                    f'os.execv({real_git!r}, [{real_git!r}] + args)\n'
                )
                wrapper.chmod(0o755)
                env = dict(os.environ, PATH=str(bindir) + os.pathsep + os.environ['PATH'])
                result = subprocess.run(
                    [sys.executable, str(ROOT / 'scripts/secret_scan.py'), 'pre-push'],
                    cwd=self.root, env=env, capture_output=True, text=True, timeout=35,
                )
                self.assertEqual(result.returncode, 2)
                self.assertEqual(result.stderr.strip(), 'secret-scan: baseline acquisition failed')
                self.assertEqual(result.stdout, '')
                calls = [json.loads(line) for line in calls_path.read_text().splitlines()]
                failed = [index for index, call in enumerate(calls) if call['failed']]
                self.assertEqual(failed, [len(calls) - 1], calls)
                patches = [call['args'] for call in calls if call['args'][:1] == ['diff']]
                self.assertEqual(len(patches), 1 if fail_stage == 'patch' else 2)
                for args in patches:
                    self.assertIn(base + '..' + target, args)
                self.assertEqual('--name-only' in patches[-1], fail_stage == 'metadata')
                self.assertTrue(any(call['args'][:1] == ['merge-base'] for call in calls))
                self.assertFalse(any(call['args'][:1] in (['rev-list'], ['log']) for call in calls))

    def test_failed_existing_head_peel_never_falls_back_to_uncommitted(self):
        self.init()
        self.commit(b'ordinary\n')
        real_git = shutil.which('git')
        self.assertIsNotNone(real_git)
        bindir = self.root / 'head-bin'
        bindir.mkdir()
        wrapper = bindir / 'git'
        calls_path = self.root / 'head-git-calls.jsonl'
        wrapper.write_text(
            '#!' + sys.executable + '\n'
            'import json, os, sys\n'
            'args = sys.argv[1:]\n'
            f'with open({str(calls_path)!r}, "a") as log:\n'
            '    log.write(json.dumps(args) + "\\n")\n'
            'if "HEAD^{commit}" in args: sys.exit(128)\n'
            f'os.execv({real_git!r}, [{real_git!r}] + args)\n'
        )
        wrapper.chmod(0o700)
        for mode in ('symbolic', 'unicode-trailing-space', 'detached'):
            with self.subTest(mode=mode):
                if mode == 'unicode-trailing-space':
                    self.git('branch', '-m', 'topic\u00a0')
                if mode == 'detached':
                    self.git('checkout', '--detach', '-q')
                calls_path.write_text('')
                result = subprocess.run(
                    [sys.executable, str(ROOT / 'scripts/secret_scan.py'), 'pre-push'],
                    cwd=self.root,
                    env=dict(os.environ, PATH=str(bindir) + os.pathsep + os.environ['PATH']),
                    capture_output=True, text=True, timeout=35,
                )
                self.assertEqual(result.returncode, 2)
                self.assertEqual(result.stderr.strip(), 'secret-scan: baseline acquisition failed')
                self.assertEqual(result.stdout, '')
                calls = [json.loads(line) for line in calls_path.read_text().splitlines()]
                self.assertTrue(any('HEAD^{commit}' in args for args in calls))
                self.assertFalse(any('diff' in args or 'log' in args or 'rev-list' in args for args in calls))
