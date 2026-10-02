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
