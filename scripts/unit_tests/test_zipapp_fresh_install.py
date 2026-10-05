"""Fresh-install smoke for the Shipwright zipapp + thin shim (PRD 091 R3)."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))


def _allowed_scripts_tree_files(scripts_dir: Path, platform: str) -> set[Path]:
    allowed = {scripts_dir / "sw-run.py"}
    if platform == "claude-code":
        allowed.add(scripts_dir / "install.py")
    return allowed


def _scripts_tree_is_shim_only(scripts_dir: Path, platform: str) -> bool:
    if not scripts_dir.is_dir():
        return True
    files = {p for p in scripts_dir.rglob("*") if p.is_file()}
    return files == _allowed_scripts_tree_files(scripts_dir, platform)


def _generate_platform_dist(repo_root: Path, out_root: Path, platform: str) -> Path:
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "sw",
            "generate",
            platform,
            "--dest",
            str(out_root),
        ],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
    return out_root / platform


@pytest.mark.parametrize("platform", ["cursor", "claude-code"])
def test_zipapp_fresh_install_smoke(repo_root: Path, tmp_path: Path, platform: str) -> None:
    dist_root = tmp_path / "dist"
    plugin_root = _generate_platform_dist(repo_root, dist_root, platform)

    scripts_dir = plugin_root / "scripts"
    assert _scripts_tree_is_shim_only(scripts_dir, platform), (
        f"expected shim-only scripts tree under {scripts_dir}, found: "
        f"{list(scripts_dir.rglob('*')) if scripts_dir.is_dir() else 'missing'}"
    )

    pyz = plugin_root / "shipwright.pyz"
    assert pyz.is_file(), f"missing stable zipapp symlink at {pyz}"
    versioned = sorted(plugin_root.glob("shipwright-*.pyz"))
    assert versioned, f"missing versioned zipapp under {plugin_root}"

    env_name = "CURSOR_PLUGIN_ROOT" if platform == "cursor" else "CLAUDE_PLUGIN_ROOT"
    env = os.environ.copy()
    env[env_name] = str(plugin_root)

    shim = scripts_dir / "sw-run.py"
    proc = subprocess.run(
        [
            sys.executable,
            str(shim),
            "resolve-model-tier.py",
            "--command",
            "sw-ship",
        ],
        cwd=str(repo_root),
        env=env,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
    assert "tier" in proc.stdout.lower() or "model" in proc.stdout.lower()

    direct = subprocess.run(
        [sys.executable, str(pyz), "resolve-model-tier.py", "--command", "sw-ship"],
        cwd=str(repo_root),
        env=env,
        capture_output=True,
        text=True,
    )
    assert direct.returncode == 0, direct.stderr or direct.stdout


# Scanner fixtures use public synthetic data only. The account database is
# substituted in child interpreters, never through a scanner/config override.
import ast
import hashlib
import json
import shutil
import signal
import stat
import struct
import tempfile
import zipfile

_SCANNER_MODULES = ('secret_scan.py', 'secret_scan_exact.py', 'secret_patterns.py')
_SCANNER_CATALOG = 'secret_scan_data/reviewed-occurrences.v1.json'
_SCANNER_ORIGIN = 'github.com/fixture/scanner-entry'
_SCANNER_ENTRIES = ('source', 'archive', 'shim')


def _scanner_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _scanner_json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(',', ':')).encode()


def _scanner_process(args, *, cwd, env, timeout=40):
    '''Bound the entire shim/zipapp/Git tree, including descendant-held pipes.'''
    proc = subprocess.Popen(args, cwd=cwd, env=env, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, start_new_session=True)
    try:
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)
        proc.communicate(timeout=5)
        pytest.fail('scanner fixture process exceeded bounded timeout')
    finally:
        # Each group belongs exclusively to this fixture invocation.
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    return subprocess.CompletedProcess(args, proc.returncode, out.decode(), err.decode())


class _ScannerInstall:
    def __init__(self, root: Path):
        self.root = root
        self.home = root / 'home'
        self.repo = root / 'repo'
        self.source = root / 'source'
        self.harness = root / 'harness'
        self.plugin = root / 'plugin'
        for path in (self.home, self.repo, self.source, self.harness, self.plugin):
            path.mkdir(mode=0o700)
        self.archive = self.plugin / 'shipwright.pyz'
        self.marker = self.repo / '.git/shipwright-secret-scan-instance-v1.json'
        self.trust = self.home / '.config/shipwright/secret-scan/trust-v1.json'
        self.env = {k: v for k, v in os.environ.items()
                    if not k.startswith(('GIT_', 'PYTHON', 'CURSOR_PLUGIN_ROOT', 'CLAUDE_PLUGIN_ROOT'))}
        # Only Git is discoverable; Python uses sys.executable. No Node/network
        # dependency is available to the real scanner subprocesses.
        binary = root / 'bin'
        binary.mkdir(mode=0o700)
        git = shutil.which('git')
        assert git, 'Git is required for scanner entry tests'
        (binary / 'git').symlink_to(git)
        self.env.update(PATH=str(binary), HOME=str(self.home),
                        PYTHONPATH=str(self.harness), PYTHONDONTWRITEBYTECODE='1',
                        GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM='1',
                        GIT_TERMINAL_PROMPT='0', CURSOR_PLUGIN_ROOT=str(self.plugin))
        for name in _SCANNER_MODULES:
            (self.source / name).write_bytes((SCRIPT_DIR / name).read_bytes())
        # Extract the literal launcher, keeping its exact production bytes.
        tree = ast.parse((SCRIPT_DIR / 'build_zipapp.py').read_text())
        self.launcher = next(ast.literal_eval(node.value) for node in tree.body
                             if isinstance(node, ast.Assign)
                             and any(isinstance(t, ast.Name) and t.id == 'ZIPAPP_LAUNCHER'
                                     for t in node.targets))
        scripts = self.plugin / 'scripts'
        scripts.mkdir(mode=0o700)
        self.shim = scripts / 'sw-run.py'
        self.shim.write_bytes((SCRIPT_DIR.parent / 'dist/cursor/scripts/sw-run.py').read_bytes())
        self.git('init', '-q', '--object-format=sha1')
        self.git('remote', 'add', 'origin', 'https://github.com/fixture/scanner-entry.git')
        self.git('-c', 'user.name=Fixture', '-c', 'user.email=fixture' + '@' + 'example.invalid',
                 '-c', 'core.hooksPath=/dev/null', 'commit', '--allow-empty', '-qm', 'base')
        self.git('update-ref', 'refs/remotes/origin/main', self.git('rev-parse', 'HEAD').strip())
        self.git('branch', '--set-upstream-to=origin/main')
        self.data = b'user_' + b'id=fixture\n'
        self.commit(self.data)
        # Independent fixture identity from the committed full blob. No mapping
        # or approval helper manufactures the expected scanner decision.
        import secret_patterns
        import secret_scan_exact
        pattern = next(p.pattern for p in secret_patterns.DENY_PATTERNS if p.name == 'SENTRY_PII_KV')
        match = pattern.search(self.data.decode().rstrip('\n'))
        assert match is not None
        record = dict(repoId=_SCANNER_ORIGIN, path='sample.txt', objectFormat='sha1',
                      blobOid=self.git('rev-parse', 'HEAD:sample.txt').strip(),
                      sourceSha256=_scanner_hash(self.data), sourceByteLength=len(self.data),
                      family='SENTRY_PII_KV', sourceLine1Based=1,
                      matchStartByte=match.start(), matchEndByteExclusive=match.end(),
                      ordinalWithinFamilyOnSourceLine1Based=1,
                      matchSha256=_scanner_hash(match.group().encode()),
                      detectorFingerprintSha256=secret_scan_exact.detector_fingerprint(pattern),
                      reviewEvidence=dict(id='synthetic-entry-review-v1',
                                          sha256=_scanner_hash(b'public synthetic scanner fixture v1'),
                                          reviewer='fixture-reviewer',
                                          attestationSha256=_scanner_hash(b'fixture-only approval v1')))
        record['id'] = _scanner_hash(_scanner_json(record))
        self.catalog = _scanner_json(dict(schemaVersion=1, records=[record]))
        self.package()

    def git(self, *args):
        result = _scanner_process(['git', *args], cwd=self.repo, env=self.env, timeout=15)
        assert result.returncode == 0, result.stderr
        return result.stdout

    def commit(self, data):
        (self.repo / 'sample.txt').write_bytes(data)
        self.git('add', 'sample.txt')
        self.git('-c', 'user.name=Fixture', '-c', 'user.email=fixture' + '@' + 'example.invalid',
                 '-c', 'core.hooksPath=/dev/null', 'commit', '-qm', 'fixture')

    def package(self, *, extra=(), omit=None, alter=None):
        with zipfile.ZipFile(self.archive, 'w', zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('__main__.py', self.launcher)
            for name in _SCANNER_MODULES:
                if name != omit:
                    data = (self.source / name).read_bytes()
                    archive.writestr(name, data + b'\n# different member\n' if name == alter else data)
            if omit != _SCANNER_CATALOG:
                archive.writestr(_SCANNER_CATALOG, self.catalog)
            for name, data in extra:
                archive.writestr(name, data)
        self.archive.chmod(0o600)

    def args(self):
        return ['enroll-exact', '--archive-path', str(self.archive), '--release-id', 'fixture-v1',
                '--expected-archive-sha256', _scanner_hash(self.archive.read_bytes()),
                '--expected-catalog-sha256', _scanner_hash(self.catalog),
                '--expected-common-dir', str(self.repo / '.git'),
                '--expected-origin', _SCANNER_ORIGIN, '--authorize-marker-write']

    def invoke(self, entry, args, *, fault=None):
        # sitecustomize is test infrastructure only; no consumer setting changes
        # production trust lookup. The shim's child inherits this fixed fixture.
        bootstrap = ('import os, pwd, types\n'
                     f'pwd.getpwuid = lambda uid: types.SimpleNamespace(pw_dir={str(self.home)!r})\n')
        if fault in ('O_NOFOLLOW', 'O_DIRECTORY', 'O_NONBLOCK', 'O_SYMLINK'):
            bootstrap += f'os.{fault} = 0\n'
        elif fault in ('alias-swap', 'target-change', 'mixed-origin'):
            bootstrap += f'''import sys
from pathlib import Path
fault = {fault!r}
alias = Path({str(self.archive)!r})
def change_origin(frame, event, arg):
    if frame.f_code.co_name != '_current_source_matches':
        return
    if fault == 'mixed-origin' and event == 'call':
        sys.modules['secret_patterns'].__file__ = {str(self.source / 'secret_patterns.py')!r}
        sys.setprofile(None)
    elif event == 'return' and fault != 'mixed-origin':
        sys.setprofile(None)
        if fault == 'alias-swap':
            target = alias.readlink()
            alias.unlink()
            alias.symlink_to(target)
        else:
            with alias.open('ab') as output:
                output.write(b'changed target')
sys.setprofile(change_origin)
'''
        elif fault:
            # Trace the actual helper without replacing its decisions. os._exit
            # models an abrupt process loss on either side of publication.
            bootstrap += f'''import sys
fault = {fault!r}
def crash(frame, event, arg):
    if frame.f_code.co_name != '_atomic_trust_write':
        return
    name = frame.f_locals.get('name')
    if ((fault == 'before-marker' and name == 'shipwright-secret-scan-instance-v1.json' and event == 'call')
        or (fault == 'after-marker' and name == 'shipwright-secret-scan-instance-v1.json' and event == 'return')
        or (fault == 'before-trust' and name == 'trust-v1.json' and event == 'call')):
        os._exit(86)
sys.setprofile(crash)
'''
        (self.harness / 'sitecustomize.py').write_text(bootstrap)
        probe = _scanner_process([sys.executable, '-c',
                                  f'import pwd,os; assert pwd.getpwuid(os.getuid()).pw_dir == {str(self.home)!r}'],
                                 cwd=self.repo, env=self.env, timeout=10)
        assert probe.returncode == 0, 'test account substitution must precede scanner execution'
        entries = {'source': [str(self.source / 'secret_scan.py')],
                   'archive': [str(self.archive), 'secret_scan.py'],
                   'shim': [str(self.shim), 'secret_scan.py']}
        return _scanner_process([sys.executable, *entries[entry], *args], cwd=self.repo, env=self.env)

    def scan_readonly(self, entry, expected, *, fault=None):
        # Harness changes are outside the scanner state snapshot.
        before = self.snapshot()
        result = self.invoke(entry, ['pre-push'], fault=fault)
        assert result.returncode == expected, (result.stdout, result.stderr)
        assert self.snapshot() == before
        if expected == 1:
            assert '[SENTRY_PII_KV]' in result.stderr
        return result

    def snapshot(self):
        result = {}
        for path in self.root.rglob('*'):
            if self.harness in path.parents or path == self.harness:
                continue
            info = path.lstat()
            value = (os.readlink(path) if path.is_symlink() else
                     _scanner_hash(path.read_bytes()) if path.is_file() else None)
            result[str(path.relative_to(self.root))] = (info.st_mode, info.st_ino, value)
        return result

    def enroll(self, entry):
        result = self.invoke(entry, self.args())
        assert result.returncode == 0, (result.stdout, result.stderr)
        assert result.stdout == 'secret-scan: enrollment complete\n'
        assert result.stderr == ''


@pytest.fixture
def scanner_install():
    # Darwin's per-account temporary root has safe ancestry; global /tmp and
    # mutable repository mounts intentionally fail production trust checks.
    with tempfile.TemporaryDirectory(prefix='scanner-entry-') as temporary:
        root = Path(temporary).resolve()
        root.chmod(0o700)
        yield _ScannerInstall(root)


_SCANNER_NATIVE = pytest.mark.skipif(sys.platform != 'darwin',
                                    reason='secure descriptor ACL enrollment supports native Darwin only')


@_SCANNER_NATIVE
@pytest.mark.parametrize('entry', _SCANNER_ENTRIES)
def test_scanner_entries_enroll_scan_and_exit_semantics(scanner_install, entry):
    fixture = scanner_install
    fixture.scan_readonly(entry, 1)
    assert not fixture.marker.exists() and not fixture.trust.exists()
    fixture.enroll(entry)
    marker = json.loads(fixture.marker.read_bytes())
    trust = json.loads(fixture.trust.read_bytes())
    assert len(bytes.fromhex(marker['instanceNonce'])) == 32
    assert trust['repository']['instanceNonce'] == marker['instanceNonce']
    assert stat.S_IMODE(fixture.marker.stat().st_mode) == 0o600
    assert stat.S_IMODE(fixture.trust.stat().st_mode) == 0o600
    for directory in (fixture.home / '.config', fixture.trust.parent.parent, fixture.trust.parent):
        assert stat.S_IMODE(directory.stat().st_mode) == 0o700
    assert sorted(p.name for p in fixture.trust.parent.iterdir()) == ['trust-v1.json']
    assert not list((fixture.repo / '.git').glob('.shipwright-secret-scan-*.tmp'))
    fixture.scan_readonly(entry, 0)
    # Actual baseline path count overflow must exit 2, never a smaller fallback.
    for index in range(513):
        (fixture.repo / f'path-{index}').write_text('plain\n')
    fixture.git('add', '.')
    fixture.git('-c', 'user.name=Fixture', '-c', 'user.email=fixture' + '@' + 'example.invalid',
                '-c', 'core.hooksPath=/dev/null', 'commit', '-qm', 'overflow')
    result = fixture.scan_readonly(entry, 2)
    assert 'secret-scan:' in result.stderr


@_SCANNER_NATIVE
@pytest.mark.parametrize('entry', _SCANNER_ENTRIES)
@pytest.mark.parametrize('flag,value', [('--expected-archive-sha256', '0' * 64),
                                       ('--expected-catalog-sha256', '0' * 64),
                                       ('--expected-origin', 'github.com/other/project'),
                                       ('--expected-common-dir', '/nonexistent'),
                                       ('--authorize-marker-write', None)])
def test_scanner_enrollment_bad_approval_writes_nothing(scanner_install, entry, flag, value):
    fixture = scanner_install
    args = fixture.args()
    if value is None:
        args.remove(flag)
    else:
        args[args.index(flag) + 1] = value
    before = fixture.snapshot()
    result = fixture.invoke(entry, args)
    assert result.returncode == 2
    assert result.stderr == ('secret-scan: enrollment arguments invalid\n' if value is None
                             else 'secret-scan: enrollment refused\n')
    assert fixture.snapshot() == before
    fixture.scan_readonly(entry, 1)


@_SCANNER_NATIVE
@pytest.mark.parametrize('entry', _SCANNER_ENTRIES)
@pytest.mark.parametrize('state', ['nonce', 'marker-mode', 'trust-mode', 'directory-mode',
                                  'marker-symlink', 'trust-symlink', 'missing-marker', 'missing-trust'])
def test_scanner_invalid_state_preserves_denial_without_repair(scanner_install, entry, state):
    fixture = scanner_install
    fixture.enroll(entry)
    if state == 'nonce':
        fixture.marker.write_bytes(_scanner_json(dict(schemaVersion=1, instanceNonce='0' * 64)))
    elif state.endswith('-mode'):
        path = {'marker-mode': fixture.marker, 'trust-mode': fixture.trust,
                'directory-mode': fixture.trust.parent}[state]
        path.chmod(0o770 if path.is_dir() else 0o644)
    elif state.endswith('-symlink'):
        path = fixture.marker if state == 'marker-symlink' else fixture.trust
        saved = path.with_name(path.name + '.saved')
        path.rename(saved)
        path.symlink_to(saved)
    else:
        (fixture.marker if state == 'missing-marker' else fixture.trust).unlink()
    fixture.scan_readonly(entry, 1)


@_SCANNER_NATIVE
@pytest.mark.parametrize('entry', _SCANNER_ENTRIES)
@pytest.mark.parametrize('fault', ['before-marker', 'after-marker', 'before-trust'])
@pytest.mark.parametrize('replace', [False, True])
def test_scanner_interrupted_publication_never_repairs(scanner_install, entry, fault, replace):
    fixture = scanner_install
    if replace:
        fixture.enroll(entry)
    old_marker = fixture.marker.read_bytes() if replace else None
    old_trust = fixture.trust.read_bytes() if replace else None
    result = fixture.invoke(entry, fixture.args() + (['--replace-marker'] if replace else []), fault=fault)
    assert result.returncode == 86
    if fault == 'before-marker':
        assert (fixture.marker.read_bytes() if fixture.marker.exists() else None) == old_marker
    else:
        assert fixture.marker.exists() and fixture.marker.read_bytes() != old_marker
    assert (fixture.trust.read_bytes() if fixture.trust.exists() else None) == old_trust
    # A pre-publication crash during replacement leaves the original valid pair.
    fixture.scan_readonly(entry, 0 if replace and fault == 'before-marker' else 1)


@_SCANNER_NATIVE
@pytest.mark.parametrize('entry', _SCANNER_ENTRIES)
def test_scanner_new_release_requires_actual_reapproval(scanner_install, entry):
    fixture = scanner_install
    fixture.enroll(entry)
    nonce = fixture.marker.read_bytes()
    old_args = fixture.args()
    fixture.package(extra=[('release-note', b'new release')])
    fixture.scan_readonly(entry, 1)
    before = fixture.snapshot()
    assert fixture.invoke(entry, old_args).returncode == 2
    assert fixture.snapshot() == before
    fixture.enroll(entry)
    assert fixture.marker.read_bytes() == nonce
    fixture.scan_readonly(entry, 0)
    assert fixture.invoke(entry, fixture.args() + ['--replace-marker']).returncode == 0
    assert fixture.marker.read_bytes() != nonce
    fixture.scan_readonly(entry, 0)


@pytest.mark.parametrize('entry', _SCANNER_ENTRIES)
@pytest.mark.parametrize('primitive', ['O_NOFOLLOW', 'O_DIRECTORY', 'O_NONBLOCK'])
def test_scanner_unsupported_primitives_decline(scanner_install, entry, primitive):
    fixture = scanner_install
    before = fixture.snapshot()
    result = fixture.invoke(entry, fixture.args(), fault=primitive)
    assert result.returncode == 2
    assert result.stderr == 'secret-scan: enrollment refused\n'
    assert fixture.snapshot() == before
    fixture.scan_readonly(entry, 1, fault=primitive)
    if sys.platform == 'darwin':
        fixture.enroll(entry)
        fixture.scan_readonly(entry, 1, fault=primitive)


@pytest.mark.skipif(sys.platform == 'darwin', reason='native Darwin positive enrollment covered above')
@pytest.mark.parametrize('entry', _SCANNER_ENTRIES)
def test_scanner_unsupported_acl_platform_declines(scanner_install, entry):
    fixture = scanner_install
    before = fixture.snapshot()
    assert fixture.invoke(entry, fixture.args()).returncode == 2
    assert fixture.snapshot() == before
    fixture.scan_readonly(entry, 1)


@_SCANNER_NATIVE
@pytest.mark.parametrize('entry', _SCANNER_ENTRIES)
@pytest.mark.parametrize('damage', ['duplicate', 'traversal', 'missing-catalog', 'catalog-tamper'])
def test_scanner_archive_structure_rejected_at_real_entries(scanner_install, entry, damage):
    fixture = scanner_install
    if damage == 'duplicate':
        with pytest.warns(UserWarning, match='Duplicate name'):
            fixture.package(extra=[(_SCANNER_CATALOG, fixture.catalog)])
    elif damage == 'traversal':
        fixture.package(extra=[('../escape', b'not extracted')])
    elif damage == 'missing-catalog':
        fixture.package(omit=_SCANNER_CATALOG)
    else:
        with zipfile.ZipFile(fixture.archive, 'a') as archive:
            archive.writestr('other', b'changed release bytes')
    args = fixture.args()
    if damage == 'catalog-tamper':
        args[args.index('--expected-catalog-sha256') + 1] = 'f' * 64
    before = fixture.snapshot()
    result = fixture.invoke(entry, args)
    assert result.returncode == 2, (result.stdout, result.stderr)
    assert result.stderr == 'secret-scan: enrollment refused\n'
    assert fixture.snapshot() == before
    fixture.scan_readonly(entry, 1)


@_SCANNER_NATIVE
@pytest.mark.parametrize('module', _SCANNER_MODULES)
def test_scanner_source_module_equality_is_required(scanner_install, module):
    fixture = scanner_install
    fixture.enroll('source')
    source = fixture.source / module
    source.write_bytes(source.read_bytes() + b'\n# changed source\n')
    fixture.scan_readonly('source', 1)
    before = fixture.snapshot()
    assert fixture.invoke('source', fixture.args()).returncode == 2
    assert fixture.snapshot() == before
    fixture.scan_readonly('archive', 0)
    fixture.scan_readonly('shim', 0)


@_SCANNER_NATIVE
@pytest.mark.parametrize('entry', _SCANNER_ENTRIES)
@pytest.mark.parametrize('bound,limit', [('members', 2048), ('catalog', 1048576),
                                        ('directory', 4194304), ('archive', 134217728)])
@pytest.mark.parametrize('delta', [0, 1])
def test_scanner_real_archive_exact_limit_and_plus_one(scanner_install, entry, bound, limit, delta):
    fixture = scanner_install
    amount = limit + delta
    if bound == 'members':
        fixture.package(extra=[(f'padding-{i}', b'') for i in range(amount - 5)])
    elif bound == 'catalog':
        fixture.catalog += b' ' * (amount - len(fixture.catalog))
        fixture.package()
    elif bound == 'directory':
        with zipfile.ZipFile(fixture.archive, 'a') as archive:
            current = sum(46 + len(i.filename.encode()) + len(i.extra) + len(i.comment)
                          for i in archive.infolist())
            remaining = amount - current
            while remaining:
                name = 'padding-' + str(len(archive.infolist()))
                overhead = 46 + len(name)
                if remaining < overhead:
                    archive.infolist()[-1].comment += b'x' * remaining
                    break
                info = zipfile.ZipInfo(name)
                size = min(65500, remaining - overhead)
                info.comment = b'x' * size
                archive.writestr(info, b'')
                remaining -= overhead + size
        raw = fixture.archive.read_bytes()
        end = raw.rfind(b'PK\x05\x06')
        assert struct.unpack_from('<I', raw, end + 12)[0] == amount
    else:
        raw = fixture.archive.read_bytes()
        with fixture.archive.open('wb') as output:
            output.seek(amount - len(raw))
            output.write(raw)
        assert fixture.archive.stat().st_size == amount
    before = fixture.snapshot()
    result = fixture.invoke(entry, fixture.args())
    assert result.returncode == (0 if delta == 0 else 2), (result.stdout, result.stderr)
    if delta:
        assert fixture.snapshot() == before
    fixture.scan_readonly(entry, 0 if delta == 0 else 1)


@_SCANNER_NATIVE
@pytest.mark.parametrize('entry', _SCANNER_ENTRIES)
@pytest.mark.parametrize('module', _SCANNER_MODULES)
@pytest.mark.parametrize('delta', [0, 1])
def test_scanner_real_module_exact_limit_and_plus_one(scanner_install, entry, module, delta):
    fixture = scanner_install
    source = fixture.source / module
    data = source.read_bytes()
    source.write_bytes(data + b'\n' + b' ' * (1048576 + delta - len(data) - 1))
    fixture.package()
    before = fixture.snapshot()
    result = fixture.invoke(entry, fixture.args())
    assert result.returncode == (0 if delta == 0 else 2), (result.stdout, result.stderr)
    if delta:
        assert fixture.snapshot() == before
    fixture.scan_readonly(entry, 0 if delta == 0 else 1)


@_SCANNER_NATIVE
@pytest.mark.parametrize('module', _SCANNER_MODULES)
def test_scanner_missing_pinned_module_refuses_source_enrollment(scanner_install, module):
    fixture = scanner_install
    fixture.package(omit=module)
    before = fixture.snapshot()
    result = fixture.invoke('source', fixture.args())
    assert result.returncode == 2
    assert result.stderr == 'secret-scan: enrollment refused\n'
    assert fixture.snapshot() == before
    fixture.scan_readonly('source', 1)


@_SCANNER_NATIVE
@pytest.mark.parametrize('entry', _SCANNER_ENTRIES)
@pytest.mark.parametrize('unsafe', ['home', 'marker', 'trust-directory'])
def test_scanner_unsafe_preexisting_paths_are_not_repaired(scanner_install, entry, unsafe):
    fixture = scanner_install
    if unsafe == 'home':
        fixture.home.chmod(0o770)
    elif unsafe == 'marker':
        fixture.marker.write_text('{}')
        fixture.marker.chmod(0o644)
    else:
        fixture.trust.parent.mkdir(parents=True, mode=0o770)
        fixture.trust.parent.chmod(0o770)
    before = fixture.snapshot()
    result = fixture.invoke(entry, fixture.args())
    assert result.returncode == 2
    assert result.stderr == 'secret-scan: enrollment refused\n'
    assert fixture.snapshot() == before
    fixture.scan_readonly(entry, 1)


@_SCANNER_NATIVE
@pytest.mark.parametrize('entry', _SCANNER_ENTRIES)
@pytest.mark.parametrize('damage', ['compressed-catalog', 'catalog-bytes'])
def test_scanner_tampered_catalog_member_is_rejected(scanner_install, entry, damage):
    fixture = scanner_install
    if damage == 'catalog-bytes':
        approved = fixture.catalog
        fixture.catalog = _scanner_json(dict(schemaVersion=1, records=[]))
        fixture.package()
        fixture.catalog = approved
    else:
        with zipfile.ZipFile(fixture.archive) as archive:
            offset = archive.getinfo(_SCANNER_CATALOG).header_offset
        raw = bytearray(fixture.archive.read_bytes())
        name_size, extra_size = struct.unpack_from('<HH', raw, offset + 26)
        start = offset + 30 + name_size + extra_size
        raw[start:start + 4] = b'\xff' * 4
        fixture.archive.write_bytes(raw)
    # Approve the actual archive digest so the member's own integrity/catalog
    # gate, rather than an outer stale-release pin, must reject it.
    before = fixture.snapshot()
    result = fixture.invoke(entry, fixture.args())
    assert result.returncode == 2
    assert result.stderr == 'secret-scan: enrollment refused\n'
    assert fixture.snapshot() == before
    fixture.scan_readonly(entry, 1)


@_SCANNER_NATIVE
@pytest.mark.parametrize('entry', _SCANNER_ENTRIES)
def test_scanner_stable_alias_enrollment_and_scan(scanner_install, entry):
    fixture = scanner_install
    target = fixture.archive.with_name('shipwright-fixture-v1.pyz')
    fixture.archive.rename(target)
    fixture.archive.symlink_to(target.name)
    args = fixture.args()
    args[args.index('--archive-path') + 1] = str(target)
    result = fixture.invoke(entry, args)
    assert result.returncode == 0, (result.stdout, result.stderr)
    assert result.stdout == 'secret-scan: enrollment complete\n'
    assert result.stderr == ''
    for scan_entry in _SCANNER_ENTRIES:
        fixture.scan_readonly(scan_entry, 0)
    # The launch alias never becomes a permissible trust pin.
    before = fixture.snapshot()
    denied = fixture.invoke(entry, fixture.args())
    assert denied.returncode == 2
    assert denied.stderr == 'secret-scan: enrollment refused\n'
    assert fixture.snapshot() == before


@_SCANNER_NATIVE
@pytest.mark.parametrize('entry', ('archive', 'shim'))
def test_scanner_stable_alias_wrong_target_denied(scanner_install, entry):
    fixture = scanner_install
    target = fixture.archive.with_name('shipwright-fixture-v1.pyz')
    fixture.archive.rename(target)
    fixture.archive.symlink_to(target.name)
    args = fixture.args()
    args[args.index('--archive-path') + 1] = str(target)
    assert fixture.invoke('source', args).returncode == 0
    wrong = target.with_name('shipwright-other.pyz')
    wrong.write_bytes(target.read_bytes())
    wrong.chmod(0o600)
    fixture.archive.unlink()
    fixture.archive.symlink_to(wrong.name)
    # Even byte-identical archives are not the pinned installed object.
    fixture.scan_readonly(entry, 1)
    before = fixture.snapshot()
    result = fixture.invoke(entry, args)
    assert result.returncode == 2
    assert result.stderr == 'secret-scan: enrollment refused\n'
    assert fixture.snapshot() == before


@_SCANNER_NATIVE
@pytest.mark.parametrize('entry', _SCANNER_ENTRIES)
def test_scanner_enrolled_overlap_retains_individual_findings(scanner_install, entry):
    fixture = scanner_install
    data = b'user_' + b'id=sk_' + b'test_abcdefghijklmnop user_' + b'id=two\n'
    fixture.commit(data)
    import secret_patterns
    pattern = next(p.pattern for p in secret_patterns.DENY_PATTERNS if p.name == 'SENTRY_PII_KV')
    matches = list(pattern.finditer(data.decode().rstrip('\n')))
    assert len(matches) == 2
    record = json.loads(fixture.catalog)['records'][0]
    record.pop('id')
    record.update(blobOid=fixture.git('rev-parse', 'HEAD:sample.txt').strip(),
                  sourceSha256=_scanner_hash(data), sourceByteLength=len(data),
                  matchStartByte=matches[0].start(), matchEndByteExclusive=matches[0].end(),
                  matchSha256=_scanner_hash(matches[0].group().encode()))
    record['id'] = _scanner_hash(_scanner_json(record))
    fixture.catalog = _scanner_json(dict(schemaVersion=1, records=[record]))
    fixture.package()
    baseline = fixture.scan_readonly(entry, 1)
    assert baseline.stderr.count('[SENTRY_PII_KV]') == 2
    assert baseline.stderr.count('[API_SECRET]') == 1
    fixture.enroll(entry)
    result = fixture.scan_readonly(entry, 1)
    assert result.stderr.count('[SENTRY_PII_KV]') == 1
    assert result.stderr.count('[API_SECRET]') == 1


@_SCANNER_NATIVE
@pytest.mark.parametrize('entry', ('archive', 'shim'))
@pytest.mark.parametrize('fault', ('alias-swap', 'target-change', 'mixed-origin', 'O_SYMLINK'))
@pytest.mark.parametrize('command', ('pre-push', 'enroll-exact'))
def test_scanner_stable_alias_changed_origin_denied(scanner_install, entry, fault, command):
    fixture = scanner_install
    target = fixture.archive.with_name('shipwright-fixture-v1.pyz')
    fixture.archive.rename(target)
    fixture.archive.symlink_to(target.name)
    args = fixture.args()
    args[args.index('--archive-path') + 1] = str(target)
    assert fixture.invoke('source', args).returncode == 0
    state = (fixture.marker.read_bytes(), fixture.trust.read_bytes())
    result = fixture.invoke(entry, ['pre-push'] if command == 'pre-push' else args, fault=fault)
    assert result.returncode == (1 if command == 'pre-push' else 2)
    if command == 'pre-push':
        assert '[SENTRY_PII_KV]' in result.stderr
    else:
        assert result.stderr == 'secret-scan: enrollment refused\n'
    assert (fixture.marker.read_bytes(), fixture.trust.read_bytes()) == state


@_SCANNER_NATIVE
@pytest.mark.parametrize('entry', ('archive', 'shim'))
def test_scanner_stable_alias_unsafe_parent_denied(scanner_install, entry):
    fixture = scanner_install
    target = fixture.archive.with_name('shipwright-fixture-v1.pyz')
    fixture.archive.rename(target)
    fixture.archive.symlink_to(target.name)
    args = fixture.args()
    args[args.index('--archive-path') + 1] = str(target)
    assert fixture.invoke('source', args).returncode == 0
    fixture.plugin.chmod(0o770)
    fixture.scan_readonly(entry, 1)
    before = fixture.snapshot()
    result = fixture.invoke(entry, args)
    assert result.returncode == 2
    assert result.stderr == 'secret-scan: enrollment refused\n'
    assert fixture.snapshot() == before


# DOCS / PACKAGE / RELEASE: source documentation drives actual installed entries.
import re
import shlex


def _scanner_documented_commands(root):
    """Check source prose and every local Markdown link; return literal shell argv."""
    directory = root / 'core/documentation'
    docs = {name: (directory / (name + '.md')).read_text()
            for name in ('troubleshooting', 'trust-anchors')}
    headings = {'troubleshooting': '## Pre-push secret scan denial',
                'trust-anchors': '### Scanner exact occurrence enrollment'}
    for name, text in docs.items():
        assert text.count(headings[name]) == 1, (name, 'missing integrated scanner section')
        section = text.split(headings[name], 1)[1].split('\n## ', 1)[0]
        assert not re.search(r'\b(?:PRD\s*\d+|R\d+)\b', section)
        for href in re.findall(r'\]\(([^)]+)\)', text):
            if '://' in href or href.startswith('mailto:'):
                continue
            filename, _, anchor = href.partition('#')
            target = directory / filename if filename else directory / (name + '.md')
            assert target.is_file(), (name, href)
            if anchor:
                slugs = {re.sub(r'[^\w -]', '', line.lstrip('# ').lower()).replace(' ', '-')
                         for line in target.read_text().splitlines() if line.startswith('#')}
                assert anchor in slugs, (name, href)
    troubleshooting = docs['troubleshooting'].lower()
    trust = docs['trust-anchors'].lower()
    for phrase in ('rotate', 'synthetic', 'stock', 'changed', 'approval', 'denial', 'marker'):
        assert phrase in troubleshooting, phrase
    for phrase in ('does not approve', 'empty catalog', 'independent security review',
                   'never enrolls', 'new release', 'darwin', 'unsupported',
                   'deliberate copy', 'reenrollment', 'never create, replace or repair'):
        assert phrase in trust, phrase
    assert 'trust-anchors.md#scanner-exact-occurrence-enrollment' in troubleshooting
    assert 'troubleshooting.md#pre-push-secret-scan-denial' in trust
    blocks = re.findall(r'```sh\n(.*?)```', docs['trust-anchors'], re.S)
    commands = [shlex.split(line) for block in blocks
                for line in block.replace('\\\n', ' ').splitlines()
                if line.strip().startswith('python3 ')]
    prefixes = [('python3', '$SOURCE/scripts/secret_scan.py'),
                ('python3', '$ARCHIVE', 'secret_scan.py'),
                ('python3', '$INSTALL/scripts/sw-run.py', 'secret_scan.py')]
    enroll = ['enroll-exact', '--archive-path', '$ARCHIVE', '--release-id', '$RELEASE_ID',
              '--expected-archive-sha256', '$ARCHIVE_SHA256',
              '--expected-catalog-sha256', '$CATALOG_SHA256',
              '--expected-common-dir', '$COMMON_DIR', '--expected-origin', '$ORIGIN',
              '--authorize-marker-write']
    expected = [list(prefix) + [command] for prefix in prefixes for command in ('pre-push',)]
    expected += [list(prefix) + enroll for prefix in prefixes]
    assert commands == expected, 'documented scan/enrollment argv differ from supported forms'
    return commands


def test_scanner_documentation_source_commands_and_links(repo_root):
    assert len(_scanner_documented_commands(repo_root)) == 6


_SCANNER_RELEASE_MODE = 'release-acceptance-v1'
_SCANNER_EMPTY_CATALOG = b'{\n  "schemaVersion": 1,\n  "records": []\n}\n'
_SCANNER_CURRENT_ARCHIVE_SHA256 = 'df44369dfb7ee95dd5627d0f041cc4e0529f15f4cd2f25a2753580957449ae74'
_SCANNER_CURRENT_CATALOG_SHA256 = 'a9c8d44180dcf5f6686bbd4dee2cfecc63c552418d312723eb47d94aa66be60e'
_SCANNER_RELEASE_IDENTITIES = {}
_SCANNER_IMPLEMENTATION_INVENTORY = None


def _scanner_release_tree(root):
    result = {}
    for directory in (root / 'runtime', root / 'dist'):
        for path in sorted(directory.rglob('*')):
            if not (path.is_file() or path.is_symlink()):
                continue
            info = path.lstat()
            relative = str(path.relative_to(root))
            result[relative] = ({'type': 'symlink', 'mode': stat.S_IMODE(info.st_mode),
                                 'target': os.readlink(path)} if path.is_symlink() else
                                {'type': 'file', 'mode': stat.S_IMODE(info.st_mode),
                                 'bytes': info.st_size,
                                 'sha256': _scanner_hash(path.read_bytes())})
    return result


def _scanner_load_acceptance_pins():
    path_value = os.environ.get('SHIPWRIGHT_TEST_SCANNER_ACCEPTANCE_PINS')
    digest = os.environ.get('SHIPWRIGHT_TEST_SCANNER_ACCEPTANCE_PINS_SHA256')
    assert path_value and digest, 'strict release acceptance requires sealed pins'
    path = Path(path_value)
    raw = path.read_bytes()
    assert _scanner_hash(raw) == digest, 'sealed acceptance pins digest mismatch'
    pins = json.loads(raw)
    assert pins['historical']['role'] == 'historical-first-empty-v1'
    assert pins['current']['role'] == 'current-populated-v1'
    return pins


def _scanner_register_release(root, role, archive_sha256, catalog_sha256):
    resolved = root.resolve()
    _SCANNER_RELEASE_IDENTITIES[str(resolved)] = {
        'role': role,
        'archiveSha256': archive_sha256,
        'catalogSha256': catalog_sha256,
    }
    return resolved


def _scanner_validate_sealed_release(root, expected, *, historical):
    root = Path(root)
    assert root.is_dir() and not root.is_symlink(), 'sealed release root unavailable'
    assert _scanner_release_tree(root) == expected['tree'], 'sealed release tree identity mismatch'
    for name, digest in expected['companionSha256'].items():
        assert _scanner_hash((root / name).read_bytes()) == digest, 'sealed companion identity mismatch'
    proof = json.loads((root / 'proof.json').read_bytes())
    commands = json.loads((root / 'commands.json').read_bytes())
    inventory = json.loads((root / 'causal-output-inventory.json').read_bytes())
    docs = json.loads((root / 'causal-docs-proof.json').read_bytes())
    assert proof['verdict'] == 'pass' and proof['omissions'] == []
    assert commands == proof['commands'] and len(commands) == 2
    assert [row['exitCode'] for row in commands] == expected['receipt']['commandExitCodes']
    assert json.loads((root / 'primary-before.json').read_bytes()) == json.loads(
        (root / 'primary-after.json').read_bytes())
    assert len(inventory) == expected['receipt']['outputCount'] == 866
    assert set(inventory) == set(expected['tree'])
    assert docs == proof['causalDocumentation'] and len(docs) == 4
    for relative, row in docs.items():
        emitted = (root / relative).read_bytes()
        source = (SCRIPT_DIR.parent / row['source']).read_bytes()
        assert emitted == source
        assert row['sourceSha256'] == row['emittedSha256'] == _scanner_hash(emitted)
    for surface in expected['surfaces']:
        archive = root / surface['archive']
        manifest_path = root / surface['manifest']
        manifest = json.loads(manifest_path.read_bytes())
        assert _scanner_hash(archive.read_bytes()) == expected['archiveSha256'] == surface['archiveSha256']
        assert _scanner_hash(manifest_path.read_bytes()) == surface['manifestSha256']
        assert len(manifest['modules']) == surface['moduleCount'] == 897
        with zipfile.ZipFile(archive) as built:
            names = built.namelist()
            assert len(names) == len(set(names)) == surface['memberCount'] == 898
            assert sorted(names) == sorted([*manifest['modules'], '__main__.py'])
            for info in built.infolist():
                with built.open(info) as member:
                    while member.read(1024 * 1024):
                        pass
            for name, digest in surface['requiredMemberSha256'].items():
                assert _scanner_hash(built.read(name)) == digest
            assert _scanner_hash(built.read(_SCANNER_CATALOG)) == expected['catalogSha256']
    for relative, pin in expected['receipt']['phaseSourceInputs'].items():
        observed = (expected['catalogSha256'] if historical and relative == 'scripts/' + _SCANNER_CATALOG
                    else _scanner_hash((SCRIPT_DIR.parent / relative).read_bytes()))
        assert observed == pin['sha256'], 'sealed release source input mismatch'
    return _scanner_register_release(root, 'historical' if historical else 'current',
                                     expected['archiveSha256'], expected['catalogSha256'])


def _scanner_tracked_inventory(root):
    result = {}
    raw = subprocess.check_output(['git', 'ls-files', '--stage', '-z'], cwd=root)
    for record in raw.split(b'\0'):
        if not record:
            continue
        metadata, encoded = record.split(b'\t', 1)
        git_mode, _object_id, stage = metadata.split()
        assert stage == b'0', 'scanner source snapshot contains an unmerged tracked path'
        relative = os.fsdecode(encoded)
        path = root / relative
        info = path.lstat()
        if git_mode == b'120000':
            assert path.is_symlink()
            result[relative] = {'type': 'symlink', 'mode': stat.S_IMODE(info.st_mode),
                                'target': os.readlink(path)}
        else:
            assert path.is_file() and not path.is_symlink()
            result[relative] = {'type': 'file', 'mode': stat.S_IMODE(info.st_mode),
                                'bytes': info.st_size, 'sha256': _scanner_hash(path.read_bytes())}
    return result


def _scanner_make_own_git_source(destination):
    global _SCANNER_IMPLEMENTATION_INVENTORY
    origin = SCRIPT_DIR.parent
    expected = _scanner_tracked_inventory(origin)
    subprocess.check_call(
        ['git', 'clone', '--local', '--no-hardlinks', '--quiet', str(origin), str(destination)])
    assert (destination / '.git').is_dir()
    assert not (destination / '.git/objects/info/alternates').exists()
    common = subprocess.check_output(['git', 'rev-parse', '--git-common-dir'], cwd=destination)
    common_path = Path(os.fsdecode(common).strip())
    common_path = common_path if common_path.is_absolute() else destination / common_path
    assert common_path.resolve() == (destination / '.git').resolve()
    assert subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=destination) == (
        subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=origin))
    raw = subprocess.check_output(['git', 'ls-files', '-z'], cwd=origin)
    for encoded in raw.split(b'\0'):
        if not encoded:
            continue
        relative = Path(os.fsdecode(encoded))
        source = origin / relative
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() or target.is_symlink():
            target.unlink()
        if source.is_symlink():
            target.symlink_to(os.readlink(source))
        else:
            shutil.copy2(source, target)
    observed = _scanner_tracked_inventory(destination)
    assert observed == expected, 'disposable own-Git source inventory mismatch'
    if _SCANNER_IMPLEMENTATION_INVENTORY is None:
        _SCANNER_IMPLEMENTATION_INVENTORY = expected
    else:
        assert expected == _SCANNER_IMPLEMENTATION_INVENTORY, 'scanner fixture implementation snapshot drifted'
    return expected


def _scanner_build_release(source, root):
    from unit_tests.test_zipapp_manifest_completeness import _load_build_zipapp
    assert _load_build_zipapp().build_archive(source, root / 'runtime')['verdict'] == 'pass'
    for host in ('cursor', 'claude-code'):
        _generate_platform_dist(source, root / 'dist', host)


def _scanner_validate_local_release(root, source, *, role, expected_catalog, expected_archive=None):
    archive_digests = set()
    for destination in ('runtime', 'dist/cursor', 'dist/claude-code'):
        plugin = root / destination
        archive = (plugin / 'shipwright.pyz').resolve()
        manifest = json.loads((plugin / 'shipwright.manifest.json').read_bytes())
        archive_digests.add(_scanner_hash(archive.read_bytes()))
        assert sorted(zipfile.ZipFile(archive).namelist()) == sorted([*manifest['modules'], '__main__.py'])
        with zipfile.ZipFile(archive) as built:
            for name in (*_SCANNER_MODULES, _SCANNER_CATALOG):
                assert built.namelist().count(name) == manifest['modules'].count(name) == 1
                assert built.read(name) == (source / 'scripts' / name).read_bytes()
            assert _scanner_hash(built.read(_SCANNER_CATALOG)) == expected_catalog
        if destination.startswith('dist/'):
            host = destination.split('/')[1]
            for name in ('troubleshooting', 'trust-anchors'):
                assert (plugin / f'documentation/{name}.md').read_bytes() == (
                    source / f'core/documentation/{name}.md').read_bytes()
            assert _scripts_tree_is_shim_only(plugin / 'scripts', host)
    assert len(archive_digests) == 1
    archive_sha256 = archive_digests.pop()
    if expected_archive is not None:
        assert archive_sha256 == expected_archive
    return _scanner_register_release(root, role, archive_sha256, expected_catalog)


def _scanner_validate_supplied_current(root):
    root = Path(root)
    assert root.is_dir() and not root.is_symlink(), 'supplied current release root unavailable'
    proof = json.loads((root / 'proof.json').read_bytes())
    commands = json.loads((root / 'commands.json').read_bytes())
    inventory = json.loads((root / 'causal-output-inventory.json').read_bytes())
    docs = json.loads((root / 'causal-docs-proof.json').read_bytes())
    assert proof['verdict'] == 'pass' and proof['omissions'] == []
    assert commands == proof['commands'] and len(commands) == 2
    assert all(command['exitCode'] == 0 for command in commands)
    assert commands[0]['command'][1:5] == ['scripts/build_zipapp.py', '--root', '.', 'build']
    assert commands[1]['command'][1:5] == ['-m', 'sw', 'generate', '--all']
    assert proof['operatorMcpEditsPreserved'] and proof['indexEmptyBeforeAfter']
    assert json.loads((root / 'primary-before.json').read_bytes()) == json.loads(
        (root / 'primary-after.json').read_bytes())
    actual = {str(path.relative_to(root)) for directory in ('runtime', 'dist')
              for path in (root / directory).rglob('*') if path.is_file() or path.is_symlink()}
    assert actual == set(inventory) and len(inventory) == proof['outputCount'] == 866
    for relative, pin in inventory.items():
        path = root / relative
        assert ({'symlink': os.readlink(path)} if path.is_symlink() else
                {'sha256': _scanner_hash(path.read_bytes())}) == pin
    assert docs == proof['causalDocumentation'] and len(docs) == 4
    for relative, pin in docs.items():
        emitted = (root / relative).read_bytes()
        source = (SCRIPT_DIR.parent / pin['source']).read_bytes()
        assert emitted == source
        assert pin['sourceSha256'] == pin['emittedSha256'] == _scanner_hash(emitted)
    for relative, pin in proof['phaseSourceInputs'].items():
        assert _scanner_hash((SCRIPT_DIR.parent / relative).read_bytes()) == pin['sha256']
    return _scanner_validate_local_release(
        root, SCRIPT_DIR.parent, role='current',
        expected_catalog=_SCANNER_CURRENT_CATALOG_SHA256,
        expected_archive=_SCANNER_CURRENT_ARCHIVE_SHA256)


@pytest.fixture(scope='module')
def scanner_documented_release(tmp_path_factory):
    """Return independent synthetic S normally, or sealed historical E in strict mode."""
    mode = os.environ.get('SHIPWRIGHT_TEST_SCANNER_RELEASE_MODE')
    assert mode in (None, '', 'regression', _SCANNER_RELEASE_MODE), 'unsupported scanner release fixture mode'
    if mode == _SCANNER_RELEASE_MODE:
        pins = _scanner_load_acceptance_pins()
        current = os.environ.get('SHIPWRIGHT_TEST_SCANNER_STANDARD_BUILD')
        historical = os.environ.get('SHIPWRIGHT_TEST_SCANNER_FIRST_EMPTY_BUILD')
        assert current and historical, 'strict release acceptance requires C and E bundles'
        _scanner_validate_sealed_release(Path(current), pins['current'], historical=False)
        return _scanner_validate_sealed_release(Path(historical), pins['historical'], historical=True)
    else:
        root = tmp_path_factory.mktemp('scanner-documentation-release')
        source = root / 'tracked-source'
        current_inventory = _scanner_make_own_git_source(source)
        catalog_relative = 'scripts/' + _SCANNER_CATALOG
        assert current_inventory[catalog_relative]['sha256'] == _SCANNER_CURRENT_CATALOG_SHA256
        (source / 'scripts' / _SCANNER_CATALOG).write_bytes(_SCANNER_EMPTY_CATALOG)
        synthetic_inventory = _scanner_tracked_inventory(source)
        assert set(synthetic_inventory) == set(current_inventory)
        assert {relative for relative in current_inventory
                if current_inventory[relative] != synthetic_inventory[relative]} == {catalog_relative}
        assert synthetic_inventory[catalog_relative]['sha256'] == _scanner_hash(_SCANNER_EMPTY_CATALOG)
        _scanner_build_release(source, root)
        return _scanner_validate_local_release(
            root, source, role='synthetic', expected_catalog=_scanner_hash(_SCANNER_EMPTY_CATALOG))


@pytest.fixture(scope='module')
def scanner_current_release(tmp_path_factory):
    """Prove current populated C without any historical or private input."""
    mode = os.environ.get('SHIPWRIGHT_TEST_SCANNER_RELEASE_MODE')
    if mode == _SCANNER_RELEASE_MODE:
        pins = _scanner_load_acceptance_pins()
        current = os.environ.get('SHIPWRIGHT_TEST_SCANNER_STANDARD_BUILD')
        assert current, 'strict release acceptance requires C bundle'
        return _scanner_validate_sealed_release(Path(current), pins['current'], historical=False)
    assert mode in (None, '', 'regression'), 'unsupported scanner release fixture mode'
    supplied = os.environ.get('SHIPWRIGHT_TEST_SCANNER_STANDARD_BUILD')
    if supplied:
        return _scanner_validate_supplied_current(supplied)
    root = tmp_path_factory.mktemp('scanner-current-release')
    source = root / 'tracked-source'
    _scanner_make_own_git_source(source)
    _scanner_build_release(source, root)
    return _scanner_validate_local_release(
        root, source, role='current',
        expected_catalog=_SCANNER_CURRENT_CATALOG_SHA256,
        expected_archive=_SCANNER_CURRENT_ARCHIVE_SHA256)


def _scanner_use_standard_release(fixture, release, host):
    """Copy actual emitted launcher/shim assets into the existing secure fixture."""
    identity = _SCANNER_RELEASE_IDENTITIES.get(str(Path(release).resolve()))
    assert identity is not None, 'release must pass role-specific validation before installation'
    shutil.rmtree(fixture.plugin)
    shutil.copytree(release / 'dist' / host, fixture.plugin, symlinks=True)
    fixture.archive = (fixture.plugin / 'shipwright.pyz').resolve()
    fixture.shim = fixture.plugin / 'scripts/sw-run.py'
    with zipfile.ZipFile(fixture.archive) as built:
        fixture.catalog = built.read(_SCANNER_CATALOG)
        assert _scanner_hash(fixture.archive.read_bytes()) == identity['archiveSha256']
        assert _scanner_hash(fixture.catalog) == identity['catalogSha256']
        assert built.read('_zipapp_launcher.py') == fixture.launcher.encode()
        assert b'_zipapp_launcher.main()' in built.read('__main__.py')
    if host == 'claude-code':
        fixture.env.pop('CURSOR_PLUGIN_ROOT', None)
        fixture.env['CLAUDE_PLUGIN_ROOT'] = str(fixture.plugin)


def _scanner_run_documented(fixture, entry, command):
    values = {'SOURCE': str(fixture.source.parent), 'INSTALL': str(fixture.plugin),
              'ARCHIVE': str(fixture.archive), 'RELEASE_ID': 'fixture-v1',
              'ARCHIVE_SHA256': _scanner_hash(fixture.archive.read_bytes()),
              'CATALOG_SHA256': _scanner_hash(fixture.catalog),
              'COMMON_DIR': str(fixture.repo / '.git'),
              'ORIGIN': fixture.git('remote', 'get-url', 'origin').strip().removeprefix('https://').removesuffix('.git')}
    # The source fixture stores modules directly. Bind SOURCE/scripts to those
    # exact bytes without rewriting the documented command or creating a dispatcher.
    source_root = fixture.root / 'documented-source'
    source_root.mkdir(exist_ok=True)
    if not (source_root / 'scripts').exists():
        (source_root / 'scripts').symlink_to(fixture.source, target_is_directory=True)
    values['SOURCE'] = str(source_root)
    argv = [re.sub(r'\$([A-Z_0-9]+)', lambda match: values[match[1]], token) for token in command]
    prefix = {'source': 2, 'archive': 3, 'shim': 3}[entry]
    assert argv[0] == 'python3'
    assert Path(argv[1]).resolve() == {'source': fixture.source / 'secret_scan.py',
                                     'archive': fixture.archive, 'shim': fixture.shim}[entry].resolve()
    # invoke supplies the existing isolated account harness, then the real entry.
    return fixture.invoke(entry, argv[prefix:])


def test_scanner_current_standard_release_identity(scanner_current_release):
    identity = _SCANNER_RELEASE_IDENTITIES[str(scanner_current_release.resolve())]
    assert identity == {
        'role': 'current',
        'archiveSha256': _SCANNER_CURRENT_ARCHIVE_SHA256,
        'catalogSha256': _SCANNER_CURRENT_CATALOG_SHA256,
    }
    for host in ('cursor', 'claude-code'):
        plugin = scanner_current_release / 'dist' / host
        with zipfile.ZipFile((plugin / 'shipwright.pyz').resolve()) as built:
            assert _scanner_hash(built.read(_SCANNER_CATALOG)) == _SCANNER_CURRENT_CATALOG_SHA256
            assert len(json.loads(built.read(_SCANNER_CATALOG))['records']) == 6


@_SCANNER_NATIVE
@pytest.mark.parametrize('host', ('cursor', 'claude-code'))
@pytest.mark.parametrize('entry', _SCANNER_ENTRIES)
def test_scanner_populated_release_entries(scanner_install, scanner_current_release, host, entry):
    private = os.environ.get('SHIPWRIGHT_TEST_TIERFORGE_REPO')
    if not private:
        pytest.skip('private release acceptance requires original pinned Git authority')
    fixture = scanner_install
    _scanner_use_standard_release(fixture, scanner_current_release, host)
    base = '6e811cd5c56726a5b0f4a8474b8b154b85ca852c'
    target = '574d6097e3f3a9cec08e1c9ab81052307c71b965'
    fixture.git('-c', 'protocol.file.allow=always', 'fetch', '--no-tags', private, base, target)
    fixture.git('reset', '--hard', target)
    fixture.git('update-ref', 'refs/remotes/origin/main', base)
    fixture.git('remote', 'set-url', 'origin', 'https://github.com/grdavies/tierforge.git')
    before = fixture.scan_readonly(entry, 1)
    assert before.stderr.count('[SENTRY_PII_KV]') == 5
    assert before.stderr.count('[DB_URL]') == 1
    commands = _scanner_documented_commands(SCRIPT_DIR.parent)
    result = _scanner_run_documented(fixture, entry, commands[_SCANNER_ENTRIES.index(entry) + 3])
    assert result.returncode == 0
    after = fixture.scan_readonly(entry, 0)
    assert '[SENTRY_PII_KV]' not in after.stderr and '[DB_URL]' not in after.stderr


@pytest.mark.parametrize('case', (
    'swap-empty-current',
    'swap-current-empty',
    'wrong-empty-archive-pin',
    'wrong-empty-catalog-pin',
    'wrong-empty-evidence-pin',
    'current-source-catalog-mismatch',
    'missing-empty-bundle',
    'missing-current-bundle',
))
def test_scanner_acceptance_release_binding_negative(case, tmp_path, tmp_path_factory, monkeypatch):
    if os.environ.get('SHIPWRIGHT_TEST_SCANNER_RELEASE_MODE') != _SCANNER_RELEASE_MODE:
        pytest.skip('strict sealed release inputs required')
    pins_path = Path(os.environ['SHIPWRIGHT_TEST_SCANNER_ACCEPTANCE_PINS'])
    pins = json.loads(pins_path.read_bytes())
    current = os.environ['SHIPWRIGHT_TEST_SCANNER_STANDARD_BUILD']
    historical = os.environ['SHIPWRIGHT_TEST_SCANNER_FIRST_EMPTY_BUILD']
    if case == 'swap-empty-current':
        monkeypatch.setenv('SHIPWRIGHT_TEST_SCANNER_FIRST_EMPTY_BUILD', current)
    elif case == 'swap-current-empty':
        monkeypatch.setenv('SHIPWRIGHT_TEST_SCANNER_STANDARD_BUILD', historical)
    elif case == 'missing-empty-bundle':
        monkeypatch.setenv('SHIPWRIGHT_TEST_SCANNER_FIRST_EMPTY_BUILD', str(tmp_path / 'missing-empty'))
    elif case == 'missing-current-bundle':
        monkeypatch.setenv('SHIPWRIGHT_TEST_SCANNER_STANDARD_BUILD', str(tmp_path / 'missing-current'))
    else:
        if case == 'wrong-empty-archive-pin':
            pins['historical']['archiveSha256'] = '0' * 64
        elif case == 'wrong-empty-catalog-pin':
            pins['historical']['catalogSha256'] = '0' * 64
        elif case == 'wrong-empty-evidence-pin':
            pins['historical']['companionSha256']['proof.json'] = '0' * 64
        elif case == 'current-source-catalog-mismatch':
            pins['current']['catalogSha256'] = '0' * 64
        variant = tmp_path / ('acceptance-pins-' + case + '.json')
        variant.write_text(json.dumps(pins, sort_keys=True, separators=(',', ':')))
        monkeypatch.setenv('SHIPWRIGHT_TEST_SCANNER_ACCEPTANCE_PINS', str(variant))
        monkeypatch.setenv('SHIPWRIGHT_TEST_SCANNER_ACCEPTANCE_PINS_SHA256',
                           _scanner_hash(variant.read_bytes()))
    with pytest.raises(AssertionError):
        scanner_documented_release.__wrapped__(tmp_path_factory)


@_SCANNER_NATIVE
@pytest.mark.parametrize('host', ('cursor', 'claude-code'))
@pytest.mark.parametrize('entry', _SCANNER_ENTRIES)
def test_scanner_documented_empty_release_entries(scanner_install, scanner_documented_release, host, entry):
    fixture = scanner_install
    _scanner_use_standard_release(fixture, scanner_documented_release, host)
    commands = _scanner_documented_commands(SCRIPT_DIR.parent)
    index = _SCANNER_ENTRIES.index(entry)
    # First bind the documented source path, outside the read-only scan snapshot.
    source_root = fixture.root / 'documented-source'
    source_root.mkdir()
    (source_root / 'scripts').symlink_to(fixture.source, target_is_directory=True)
    before = fixture.snapshot()
    result = _scanner_run_documented(fixture, entry, commands[index])
    assert result.returncode == 1 and result.stderr.count('[SENTRY_PII_KV]') == 1
    assert fixture.snapshot() == before
    assert not fixture.marker.exists() and not fixture.trust.exists()
    assert _scanner_run_documented(fixture, entry, commands[index + 3]).returncode == 0
    trust = json.loads(fixture.trust.read_bytes())
    assert trust['archiveSha256'] == _scanner_hash(fixture.archive.read_bytes())
    assert trust['catalogSha256'] == _scanner_hash(fixture.catalog)
    assert stat.S_IMODE(fixture.marker.stat().st_mode) == 0o600
    fixture.scan_readonly(entry, 1)  # Explicit empty enrollment approves nothing.
    before = fixture.snapshot()
    assert fixture.invoke(entry, []).returncode == 1  # Documented default pre-push.
    assert fixture.snapshot() == before
    fixture.marker.unlink()
    fixture.scan_readonly(entry, 1)
    assert not fixture.marker.exists()  # No implicit enrollment repair.


@_SCANNER_NATIVE
@pytest.mark.parametrize('entry', _SCANNER_ENTRIES)
def test_scanner_empty_release_retains_original_private_six(scanner_install, scanner_documented_release, entry):
    private = os.environ.get('SHIPWRIGHT_TEST_TIERFORGE_REPO')
    if not private:
        pytest.skip('private release acceptance requires original pinned Git authority')
    from unit_tests.w4.test_secret_scan import _APPROVED_EXACT_METADATA
    import dataclasses
    import secret_scan
    import secret_scan_exact

    fixture = scanner_install
    _scanner_use_standard_release(fixture, scanner_documented_release, 'cursor')
    base = '6e811cd5c56726a5b0f4a8474b8b154b85ca852c'
    target = '574d6097e3f3a9cec08e1c9ab81052307c71b965'
    # Only read immutable objects from the real repository. All refs, checkout,
    # trust and marker writes below are confined to this private temporary repo.
    fixture.git('-c', 'protocol.file.allow=always', 'fetch', '--no-tags', private, base, target)
    fixture.git('reset', '--hard', target)
    fixture.git('update-ref', 'refs/remotes/origin/main', base)
    fixture.git('remote', 'set-url', 'origin', 'https://github.com/grdavies/tierforge.git')
    patch = fixture.git('diff', '--no-ext-diff', '--no-textconv', base, target)
    assert len(secret_scan.scan_diff(patch, allowlist={})) == 6
    blobs = {}
    for row in _APPROVED_EXACT_METADATA:
        oid = fixture.git('rev-parse', target + ':' + row['path']).strip()
        assert oid == row['blobOid']
        data = fixture.git('cat-file', 'blob', oid).encode()
        assert len(data) == row['sourceByteLength']
        assert _scanner_hash(data) == row['sourceSha256']
        blobs[row['path']] = secret_scan_exact.CommittedBlob(
            row['path'], row['objectFormat'], oid, row['sourceSha256'], data)
    occurrences = secret_scan_exact.map_added_occurrences(patch.encode(), blobs=blobs, repo_id='github.com/grdavies/tierforge')
    assert sorted((dataclasses.asdict(o.identity) for o in occurrences), key=lambda row: (row['path'], row['sourceLine1Based'])) == sorted(
        _APPROVED_EXACT_METADATA, key=lambda row: (row['path'], row['sourceLine1Based']))
    result = fixture.scan_readonly(entry, 1)
    assert result.stderr.count('[SENTRY_PII_KV]') == 5 and result.stderr.count('[DB_URL]') == 1
    args = fixture.args()
    args[args.index('--expected-origin') + 1] = 'github.com/grdavies/tierforge'
    assert fixture.invoke(entry, args).returncode == 0
    result = fixture.scan_readonly(entry, 1)
    assert result.stderr.count('[SENTRY_PII_KV]') == 5 and result.stderr.count('[DB_URL]') == 1
