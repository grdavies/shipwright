"""Bounded committed source acquisition and pure exact-occurrence matching.

Blobs and parsed catalogs describe identities, never approval. No worktree/index
source reads, trust loading or enrollment are performed here.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import selectors
import signal
import subprocess
import time

PATCH_LIMIT = 16 * 1024 * 1024
PATH_LIMIT = 512
BLOB_LIMIT = 2 * 1024 * 1024
BLOB_TOTAL_LIMIT = 16 * 1024 * 1024
STDERR_LIMIT = 1024 * 1024
CHILD_SECONDS = 10.0
TOTAL_SECONDS = 30.0


class AcquisitionError(RuntimeError):
    """Fatal incomplete baseline; must never be caught as an absent candidate."""


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: bytes
    stderr: bytes


@dataclass(frozen=True)
class CommittedBlob:
    path: str
    object_format: str
    oid: str
    sha256: str
    data: bytes


class Acquisition:
    def __init__(self) -> None:
        self.deadline = time.monotonic() + TOTAL_SECONDS
        self.patch_bytes = 0
        self.blob_bytes = 0
        self.paths: set[bytes] = set()
        self._raw_patches: list[bytes] = []

    def run(self, args: list[str], *, cwd: Path | None = None,
            stdout_limit: int = PATCH_LIMIT, stderr_limit: int = STDERR_LIMIT) -> CommandResult:
        """Drain both pipes incrementally; never use reader threads or unbounded communicate.

        Every child owns a new process group. Even if its leader exited, kill the
        group before closing pipes and reap the leader. Descendants cannot keep
        this scanner blocked by retaining a pipe. Unsupported platforms fail closed.
        """
        if os.name != 'posix' or not hasattr(os, 'killpg'):
            raise AcquisitionError('secret-scan: acquisition platform unsupported')
        end = min(self.deadline, time.monotonic() + CHILD_SECONDS)
        if time.monotonic() >= end:
            raise AcquisitionError('secret-scan: acquisition timeout')
        env = dict(os.environ, GIT_NO_REPLACE_OBJECTS='1', GIT_TERMINAL_PROMPT='0')
        try:
            selector = selectors.DefaultSelector()
        except OSError as exc:
            raise AcquisitionError('secret-scan: acquisition setup failed') from exc
        try:
            proc = subprocess.Popen(args, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                    start_new_session=True)
        except OSError as exc:
            selector.close()
            raise AcquisitionError('secret-scan: acquisition unavailable') from exc
        output = [bytearray(), bytearray()]
        limits = [stdout_limit, stderr_limit]
        try:
            for index, pipe in enumerate((proc.stdout, proc.stderr)):
                os.set_blocking(pipe.fileno(), False)
                selector.register(pipe, selectors.EVENT_READ, index)
            while selector.get_map() or proc.poll() is None:
                remaining = end - time.monotonic()
                if remaining <= 0:
                    raise AcquisitionError('secret-scan: acquisition timeout')
                for key, _ in selector.select(min(remaining, .05)):
                    index = key.data
                    data = os.read(key.fd, min(65536, limits[index] - len(output[index]) + 1))
                    if not data:
                        selector.unregister(key.fileobj)
                        continue
                    output[index].extend(data)
                    if len(output[index]) > limits[index]:
                        raise AcquisitionError('secret-scan: acquisition output limit')
            return CommandResult(proc.returncode, bytes(output[0]), bytes(output[1]))
        except OSError as exc:
            raise AcquisitionError('secret-scan: acquisition incomplete') from exc
        finally:
            # Do not predicate group cleanup on poll(): a dead leader can leave
            # living grandchildren holding stdout/stderr open.
            cleanup_failed = False
            # Reap an already-dead leader first: macOS can report EPERM for a
            # zombie-only process group. Still kill its group unconditionally.
            proc.poll()
            try:
                for attempt in range(2):
                    try:
                        os.killpg(proc.pid, signal.SIGKILL)
                        break
                    except ProcessLookupError:
                        break
                    except PermissionError:
                        # The leader may become a zombie between poll and kill.
                        # Reap and retry once; never ignore a persistent denial.
                        if not attempt:
                            try:
                                proc.wait(timeout=.1)
                            except subprocess.TimeoutExpired:
                                pass
                        else:
                            cleanup_failed = True
                    except OSError:
                        cleanup_failed = True
                        break
                if cleanup_failed:
                    try:
                        proc.kill()
                    except OSError:
                        pass
            finally:
                selector.close()
                proc.stdout.close()
                proc.stderr.close()
                try:
                    proc.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    cleanup_failed = True
            if cleanup_failed:
                raise AcquisitionError('secret-scan: acquisition cleanup failed')

    def git(self, args: list[str], *, cwd: Path | None = None,
            stdout_limit: int = PATCH_LIMIT) -> bytes:
        result = self.run(['git', '--no-replace-objects', *args], cwd=cwd,
                          stdout_limit=stdout_limit)
        if result.returncode:
            # Ordinary missing refs/probes can fall back. Baseline callers must
            # promote this to AcquisitionError, without exposing stderr payloads.
            raise RuntimeError('secret-scan: git acquisition failed')
        return result.stdout

    def patch(self, args: list[str], *, cwd: Path) -> bytes:
        """Acquire baseline patch plus exact NUL path inventory for the same OIDs."""
        safe = [args[0], '--no-ext-diff', '--no-textconv', *args[1:]]
        names = [arg for arg in safe if arg != '-p']
        names[1:1] = ['--name-only', '-z']
        try:
            data = self.git(safe, cwd=cwd, stdout_limit=PATCH_LIMIT - self.patch_bytes)
            selected = nul_paths(self.git(names, cwd=cwd))
        except RuntimeError as exc:
            if isinstance(exc, AcquisitionError):
                raise
            raise AcquisitionError('secret-scan: baseline acquisition failed') from exc
        self.patch_bytes += len(data)
        self.paths.update(selected)
        if len(self.paths) > PATH_LIMIT:
            raise AcquisitionError('secret-scan: selected path limit')
        self._raw_patches.append(data)
        return data


_ACTIVE: ContextVar[Acquisition | None] = ContextVar('secret_scan_acquisition', default=None)


def acquisition_active() -> bool:
    return _ACTIVE.get() is not None


@contextmanager
def acquisition_scope():
    """Nested scanner calls share the earliest deadline; no per-command reset."""
    current = _ACTIVE.get()
    if current is not None:
        yield current
        return
    current = Acquisition()
    context_handle = _ACTIVE.set(current)
    try:
        yield current
    finally:
        _ACTIVE.reset(context_handle)


def nul_paths(data: bytes) -> list[bytes]:
    if not data:
        return []
    if not data.endswith(b'\0'):
        raise AcquisitionError('secret-scan: incomplete path metadata')
    paths = data[:-1].split(b'\0')
    if any(not path for path in paths):
        raise AcquisitionError('secret-scan: invalid path metadata')
    return paths


def git_text(args: list[str], *, cwd: Path | None = None) -> str:
    with acquisition_scope() as acq:
        is_patch = args[0] == 'diff' or (args[0] == 'log' and '-p' in args)
        data = acq.patch(args, cwd=cwd) if is_patch else acq.git(args, cwd=cwd)
        try:
            # Preserve subprocess text=True's legacy universal-newline behavior.
            return data.decode('utf-8').replace('\r\n', '\n').replace('\r', '\n')
        except UnicodeError as exc:
            raise AcquisitionError('secret-scan: acquisition encoding invalid') from exc


def _oid(value: str, object_format: str) -> bool:
    return bool(re.fullmatch('[0-9a-f]{' + str(40 if object_format == 'sha1' else 64) + '}', value))


def _safe_path(path: str) -> bool:
    return (isinstance(path, str) and bool(path) and '\0' not in path and '\\' not in path
            and not path.startswith('/') and all(p not in ('', '.', '..') for p in path.split('/')))


def _selected_paths(acq: Acquisition, root: Path, selection) -> set[bytes]:
    if selection.kind == 'root' and selection.base_oid is None:
        args = ['diff-tree', '--root', '--no-commit-id', '-r', '--name-only', '-z',
                '--no-ext-diff', '--no-textconv', selection.target_oid]
    elif selection.kind in ('upstream', 'resolver', 'unpushed', 'triple-dot', 'last-commit') and selection.base_oid:
        args = ['diff', '--name-only', '-z', '--no-ext-diff', '--no-textconv',
                selection.base_oid, selection.target_oid]
    else:
        raise ValueError('unsupported selection')
    paths = set(nul_paths(acq.git(args, cwd=root)))
    if len(paths) > PATH_LIMIT:
        raise ValueError('path limit')
    return paths


def acquire_blobs(root: Path, selection, candidate_paths: list[str]) -> dict[str, CommittedBlob]:
    """Return complete verified regular blobs, or no optional context on failure.

    Caller names merely narrow acquisition. Selection metadata and target tree
    independently establish membership and object identity; none grants approval.
    Run within the pre-push acquisition_scope to share its original deadline.
    """
    try:
        with acquisition_scope() as acq:
            if selection.kind in ('uncommitted', 'merge-commit') or not selection.target_oid:
                return {}
            if len(candidate_paths) > PATH_LIMIT:
                return {}
            fmt = acq.git(['rev-parse', '--show-object-format'], cwd=root, stdout_limit=128).decode('ascii').strip()
            if fmt not in ('sha1', 'sha256') or not _oid(selection.target_oid, fmt):
                return {}
            if selection.base_oid is not None and not _oid(selection.base_oid, fmt):
                return {}
            selected = _selected_paths(acq, root, selection)
            blobs: dict[str, CommittedBlob] = {}
            for path in dict.fromkeys(candidate_paths):
                if not _safe_path(path) or path.encode('utf-8') not in selected:
                    continue
                metadata = acq.git(['--literal-pathspecs', 'ls-tree', '-z', '--full-tree',
                                     selection.target_oid, '--', path], cwd=root)
                rows = nul_paths(metadata)
                if len(rows) != 1:
                    continue
                header, actual_path = rows[0].split(b'\t', 1)
                mode, kind, oid_bytes = header.split(b' ')
                oid = oid_bytes.decode('ascii')
                if actual_path != path.encode('utf-8') or mode not in (b'100644', b'100755') or kind != b'blob' or not _oid(oid, fmt):
                    continue
                size_raw = acq.git(['cat-file', '-s', oid], cwd=root, stdout_limit=128)
                if not re.fullmatch(rb'[0-9]+\n', size_raw):
                    return {}
                size = int(size_raw)
                if size > BLOB_LIMIT or acq.blob_bytes + size > BLOB_TOTAL_LIMIT:
                    return {}
                data = acq.git(['cat-file', 'blob', oid], cwd=root, stdout_limit=BLOB_LIMIT)
                acq.blob_bytes += len(data)
                if len(data) != size or hashlib.new(fmt, b'blob ' + str(size).encode('ascii') + b'\0' + data).hexdigest() != oid:
                    return {}
                if b'\0' in data:
                    continue
                data.decode('utf-8')
                blobs[path] = CommittedBlob(path, fmt, oid, hashlib.sha256(data).hexdigest(), data)
            return blobs
    except (RuntimeError, ValueError, UnicodeError, OSError):
        # Optional failure never changes or truncates the already acquired patch.
        return {}

# Catalog validation and mapping are deliberately separate from trust. A parsed
# catalog describes identities; only the later pinned-release caller may use it.
CATALOG_JSON_LIMIT = 1024 * 1024
CATALOG_RECORD_LIMIT = 1024


class CatalogError(ValueError):
    """Invalid optional catalog; callers retain every baseline occurrence."""


@dataclass(frozen=True)
class _Identity:
    repoId: str
    path: str
    objectFormat: str
    blobOid: str
    sourceSha256: str
    sourceByteLength: int
    family: str
    sourceLine1Based: int
    matchStartByte: int
    matchEndByteExclusive: int
    ordinalWithinFamilyOnSourceLine1Based: int
    matchSha256: str
    detectorFingerprintSha256: str


@dataclass(frozen=True)
class _ReviewEvidence:
    id: str
    sha256: str
    reviewer: str
    attestationSha256: str


@dataclass(frozen=True)
class _CatalogRecord:
    id: str
    identity: _Identity
    reviewEvidence: _ReviewEvidence


@dataclass(frozen=True)
class _Catalog:
    records: tuple[_CatalogRecord, ...]


@dataclass(frozen=True)
class _Occurrence:
    """One regex match, before any legacy Finding projection or allowlist.

    patch_line is one-based in the raw patch; added_line is one-based within
    its file chunk (the legacy diagnostic coordinate). Character spans refer
    to the added source line, while identity spans refer to the whole blob.
    Neither this object nor catalog errors retain raw source/match values.
    """
    identity: _Identity
    patch_line: int
    added_line: int
    start_char: int
    end_char: int


# Frozen PRD 367 durable approval table, EO-01. Policy, not an active record.
# No pattern, localhost, test-path or approval-boolean heuristic can widen it.
_EO01 = _Identity(
    repoId='github.com/grdavies/tierforge',
    path='docs/ops/integration-test-profiles.md',
    objectFormat='sha1',
    blobOid='267a3f86199209cc5ab1bd008a951e68a7a70a38',
    sourceSha256='d8213ee9a990e777c56d050a06f2d7fc22be9c513799eb6683574ed85bf4523c',
    sourceByteLength=35041,
    family='DB_URL',
    sourceLine1Based=149,
    matchStartByte=32071,
    matchEndByteExclusive=32126,
    ordinalWithinFamilyOnSourceLine1Based=1,
    matchSha256='fddbf46293be99a7ac345f976d31117177068752ff59233de6fba99fb90c0750',
    detectorFingerprintSha256='caaea4acfe1bc72b585333e1578e5834064af906d3b42b5d82b4a2bea86bf0ed',
)


def _canonical_json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=False, allow_nan=False).encode('utf-8')


def _catalog_invalid() -> None:
    raise CatalogError('secret-scan: catalog invalid')


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            _catalog_invalid()
        result[key] = value
    return result


def _keys(value: object, expected: set[str]) -> None:
    if type(value) is not dict or set(value) != expected:
        _catalog_invalid()


def _digest(value: object) -> bool:
    return type(value) is str and re.fullmatch('[0-9a-f]{64}', value) is not None


def _token(value: object) -> bool:
    # Opaque review identifiers/attestations only; never free-form source text.
    return type(value) is str and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:/#-]{0,255}', value) is not None


def _repo_id(value: object) -> bool:
    # An already canonical host/owner/repository, not a URL or local pathname.
    return (type(value) is str and len(value) <= 512
            and re.fullmatch(r'[a-z0-9]+(?:[.-][a-z0-9]+)+/[A-Za-z0-9_-][A-Za-z0-9._-]*/[A-Za-z0-9_-][A-Za-z0-9._-]*', value) is not None)


def _catalog_path(path: object) -> bool:
    return (_safe_path(path) and len(path.encode('utf-8')) <= 4096
            and re.match(r'^[A-Za-z]:', path) is None
            and not any(ord(c) < 32 or ord(c) == 127 for c in path))


def _parse_identity(record: dict) -> _Identity:
    values = {name: record[name] for name in _Identity.__dataclass_fields__}
    for key in ('sourceSha256', 'matchSha256', 'detectorFingerprintSha256'):
        if not _digest(values[key]):
            _catalog_invalid()
    if (not _repo_id(values['repoId']) or not _catalog_path(values['path'])
            or values['objectFormat'] not in ('sha1', 'sha256')
            or type(values['blobOid']) is not str
            or not _oid(values['blobOid'], values['objectFormat'])):
        _catalog_invalid()
    for key in ('sourceByteLength', 'sourceLine1Based', 'matchStartByte',
                'matchEndByteExclusive', 'ordinalWithinFamilyOnSourceLine1Based'):
        minimum = 0 if key == 'matchStartByte' else 1
        if type(values[key]) is not int or not minimum <= values[key] <= BLOB_LIMIT:
            _catalog_invalid()
    if not values['matchStartByte'] < values['matchEndByteExclusive'] <= values['sourceByteLength']:
        _catalog_invalid()
    identity = _Identity(**values)
    if identity.family != 'SENTRY_PII_KV' and identity != _EO01:
        _catalog_invalid()
    return identity


def parse_catalog(data: bytes) -> _Catalog:
    """Validate a bounded v1 catalog; raise only fixed, source-free errors.

    Record IDs are SHA-256 of compact, sorted, UTF-8 JSON excluding only `id`.
    Review evidence is immutable metadata, never authority to activate a record.
    No file, config, environment, trust or enrollment access occurs here.
    """
    try:
        if type(data) is not bytes or len(data) > CATALOG_JSON_LIMIT:
            _catalog_invalid()
        document = json.loads(data.decode('utf-8'), object_pairs_hook=_unique_object,
                              parse_constant=lambda _: _catalog_invalid())
        _keys(document, {'schemaVersion', 'records'})
        if type(document['schemaVersion']) is not int or document['schemaVersion'] != 1:
            _catalog_invalid()
        records = document['records']
        if type(records) is not list or len(records) > CATALOG_RECORD_LIMIT:
            _catalog_invalid()
        parsed = []
        ids, positions, spans = set(), set(), set()
        sources = {}
        evidence_digests = {}
        fields = set(_Identity.__dataclass_fields__) | {'id', 'reviewEvidence'}
        for record in records:
            _keys(record, fields)
            if not _digest(record['id']):
                _catalog_invalid()
            evidence = record['reviewEvidence']
            _keys(evidence, {'id', 'sha256', 'reviewer', 'attestationSha256'})
            if (not _token(evidence['id']) or not _token(evidence['reviewer'])
                    or not _digest(evidence['sha256']) or not _digest(evidence['attestationSha256'])):
                _catalog_invalid()
            if evidence['id'] in evidence_digests and evidence_digests[evidence['id']] != evidence['sha256']:
                _catalog_invalid()
            evidence_digests[evidence['id']] = evidence['sha256']
            identity = _parse_identity(record)
            expected = hashlib.sha256(_canonical_json({k: v for k, v in record.items() if k != 'id'})).hexdigest()
            if expected != record['id'] or expected in ids:
                _catalog_invalid()
            source_key = (identity.repoId, identity.path)
            source = (identity.objectFormat, identity.blobOid, identity.sourceSha256, identity.sourceByteLength)
            if source_key in sources and sources[source_key] != source:
                _catalog_invalid()
            position = (*source_key, identity.family, identity.sourceLine1Based,
                        identity.ordinalWithinFamilyOnSourceLine1Based)
            span = (*source_key, identity.family, identity.matchStartByte, identity.matchEndByteExclusive)
            if position in positions or span in spans:
                _catalog_invalid()
            ids.add(expected)
            sources[source_key] = source
            positions.add(position)
            spans.add(span)
            parsed.append(_CatalogRecord(expected, identity, _ReviewEvidence(**evidence)))
        return _Catalog(tuple(parsed))
    except (ValueError, TypeError, UnicodeError, RecursionError, OverflowError):
        # json decoder messages can include consumer-controlled data. Do not leak
        # them through the exception message or chained exception traceback.
        raise CatalogError('secret-scan: catalog invalid') from None


def detector_fingerprint(pattern: re.Pattern[str]) -> str:
    return hashlib.sha256(_canonical_json({'regex': pattern.pattern, 'flags': pattern.flags})).hexdigest()


def raw_selected_patch() -> bytes | None:
    """Exact bytes already acquired in this scope; no re-selection or Git call.

    Future pre-push plumbing must stay inside acquisition_scope through mapping.
    Multiple patches (or no active scope) are deliberately ineligible. This
    bounded ephemeral capture never changes git_text's legacy newline behavior.
    """
    acq = _ACTIVE.get()
    if acq is None or len(acq._raw_patches) != 1:
        return None
    return acq._raw_patches[0]


def _git_path_spellings(path: bytes) -> set[bytes]:
    """Only encodings Git emits with core.quotePath either true or false."""
    escapes = {7: b'\\a', 8: b'\\b', 9: b'\\t', 10: b'\\n', 11: b'\\v',
               12: b'\\f', 13: b'\\r', 34: b'\\"', 92: b'\\\\'}
    spellings = set()
    for quote_high in (False, True):
        quoted = bytearray()
        required = False
        for byte in path:
            if byte in escapes:
                quoted.extend(escapes[byte])
                required = True
            elif byte < 32 or byte == 127 or (quote_high and byte >= 128):
                quoted.extend(('\\%03o' % byte).encode('ascii'))
                required = True
            else:
                quoted.append(byte)
        spellings.add(b'"' + bytes(quoted) + b'"' if required else path)
    return spellings


def _patch_path(raw: bytes, prefix: bytes) -> tuple[str | None, bytes]:
    # Git adds a tab terminator to some unquoted space-containing header paths.
    raw = raw.removesuffix(b'\t')
    encoded = raw
    if raw.startswith(b'"'):
        if len(raw) < 2 or not raw.endswith(b'"'):
            raise ValueError('path')
        result = bytearray()
        escaped = {ord(k): v for k, v in {'a': 7, 'b': 8, 't': 9, 'n': 10,
                   'v': 11, 'f': 12, 'r': 13, '"': 34, '\\': 92}.items()}
        i = 1
        while i < len(raw) - 1:
            byte = raw[i]
            if byte == 34 or byte < 32:
                raise ValueError('path')
            if byte == 92:
                i += 1
                if i >= len(raw) - 1:
                    raise ValueError('path')
                if raw[i] in escaped:
                    byte = escaped[raw[i]]
                else:
                    octal = raw[i:i + 3]
                    if len(octal) != 3 or re.fullmatch(rb'[0-3][0-7]{2}', octal) is None:
                        raise ValueError('path')
                    byte = int(octal, 8)
                    i += 2
            result.append(byte)
            i += 1
        encoded = bytes(result)
    elif b'"' in raw or b'\\' in raw or b'\t' in raw:
        raise ValueError('path')
    if raw not in _git_path_spellings(encoded):
        raise ValueError('path encoding')
    if encoded == b'/dev/null':
        return None, raw
    if not encoded.startswith(prefix):
        raise ValueError('path')
    path = encoded[len(prefix):].decode('utf-8')
    if not _catalog_path(path) or path.encode('utf-8') != encoded[len(prefix):]:
        raise ValueError('path')
    return path, raw


def _blob_lines(blob: CommittedBlob, path: str) -> tuple[list[bytes], list[int]]:
    data = blob.data
    if (blob.path != path or blob.object_format not in ('sha1', 'sha256')
            or len(data) > BLOB_LIMIT or b'\0' in data
            or hashlib.sha256(data).hexdigest() != blob.sha256
            or hashlib.new(blob.object_format, b'blob ' + str(len(data)).encode('ascii') + b'\0' + data).hexdigest() != blob.oid):
        raise ValueError('blob')
    data.decode('utf-8')
    lines = data.split(b'\n')
    lines = [line + b'\n' for line in lines[:-1]] + ([lines[-1]] if lines[-1] else [])
    offsets = []
    offset = 0
    for line in lines:
        offsets.append(offset)
        offset += len(line)
    return lines, offsets


_HUNK = re.compile(rb'@@ -([0-9]{1,8})(?:,([0-9]{1,8}))? \+([0-9]{1,8})(?:,([0-9]{1,8}))? @@(?: .*)?\n')


def _map_file(section: list[tuple[int, bytes]], repo_id: str,
              blobs: dict[str, CommittedBlob]) -> tuple[str | None, list[_Occurrence]]:
    from secret_patterns import DENY_PATTERNS

    fingerprints = {deny.name: detector_fingerprint(deny.pattern) for deny in DENY_PATTERNS}
    header = section[0][1].removesuffix(b'\n')
    old_path = new_path = None
    old_raw = new_raw = None
    hunk_at = len(section)
    for index, (_, line) in enumerate(section[1:], 1):
        if line.startswith(b'@@'):
            hunk_at = index
            break
        if line.startswith(b'--- '):
            if old_raw is not None:
                raise ValueError('header')
            old_path, old_raw = _patch_path(line[4:].removesuffix(b'\n'), b'a/')
        elif line.startswith(b'+++ '):
            if new_raw is not None or old_raw is None:
                raise ValueError('header')
            new_path, new_raw = _patch_path(line[4:].removesuffix(b'\n'), b'b/')
        elif not line.startswith((b'index ', b'new file mode ', b'deleted file mode ',
                                  b'old mode ', b'new mode ', b'similarity index ',
                                  b'rename from ', b'rename to ', b'Binary files ', b'GIT binary patch')):
            raise ValueError('header')
    if hunk_at == len(section):
        return new_path, []
    if old_raw is None or new_raw is None or (old_path is None and new_path is None):
        raise ValueError('header')
    # Match the entire header to the independently parsed old/new path tokens.
    # New/deleted files use the surviving path on both sides of diff --git.
    old_token = old_raw if old_path is not None else new_raw.replace(b'b/', b'a/', 1)
    new_token = new_raw if new_path is not None else old_raw.replace(b'a/', b'b/', 1)
    if header != b'diff --git ' + old_token + b' ' + new_token:
        raise ValueError('header')
    blob = blobs.get(new_path)
    lines, offsets = _blob_lines(blob, new_path) if blob is not None else ([], [])
    result = []
    added_line = 0
    previous_old_end = previous_new_end = 1
    index = hunk_at
    while index < len(section):
        match = _HUNK.fullmatch(section[index][1])
        if match is None:
            raise ValueError('hunk')
        old_start, old_count, new_start, new_count = [int(value) if value is not None else 1 for value in match.groups()]
        old_anchor = old_start + (old_count == 0)
        new_anchor = new_start + (new_count == 0)
        if (not (old_count or new_count)
                or old_path is None and (old_start or old_count)
                or new_path is None and (new_start or new_count)
                or old_start == 0 and old_count or new_start == 0 and new_count
                or old_anchor < previous_old_end or new_anchor < previous_new_end
                or old_anchor - previous_old_end != new_anchor - previous_new_end):
            raise ValueError('hunk')
        previous_old_end = old_anchor + old_count
        previous_new_end = new_anchor + new_count
        old_seen = new_seen = 0
        index += 1
        while index < len(section) and not section[index][1].startswith(b'@@'):
            patch_line, raw = section[index]
            if raw[:1] not in (b' ', b'+', b'-') or not raw.endswith(b'\n'):
                raise ValueError('hunk')
            kind, payload = raw[:1], raw[1:]
            index += 1
            if index < len(section) and section[index][1] == b'\\ No newline at end of file\n':
                payload = payload[:-1]
                index += 1
            if kind in (b' ', b'-'):
                old_seen += 1
            if kind in (b' ', b'+'):
                source_line = new_start + new_seen
                new_seen += 1
                if blob is not None and (source_line < 1 or source_line > len(lines) or lines[source_line - 1] != payload):
                    raise ValueError('mapping')
            if old_seen > old_count or new_seen > new_count:
                raise ValueError('hunk')
            if kind != b'+':
                continue
            # Legacy diff_added_lines_only excludes +++ lines. Non-LF line
            # separators also alter legacy splitlines coordinates: decline them.
            if raw.startswith(b'+++'):
                raise ValueError('legacy mapping')
            added_line += 1
            if blob is None:
                continue
            content = payload.removesuffix(b'\n').removesuffix(b'\r')
            text = content.decode('utf-8')
            if any(c in text for c in '\r\n\v\f\x1c\x1d\x1e\x85\u2028\u2029'):
                raise ValueError('legacy mapping')
            for deny in DENY_PATTERNS:
                char_cursor, byte_cursor = 0, offsets[source_line - 1]
                for ordinal, found in enumerate(deny.pattern.finditer(text), 1):
                    # Advance once per family, avoiding quadratic re-encoding
                    # when one long source line contains many occurrences.
                    start = byte_cursor + len(text[char_cursor:found.start()].encode('utf-8'))
                    matched = found.group().encode('utf-8')
                    end = start + len(matched)
                    char_cursor, byte_cursor = found.end(), end
                    if blob.data[start:end] != matched:
                        raise ValueError('span')
                    identity = _Identity(repo_id, new_path, blob.object_format, blob.oid,
                                         blob.sha256, len(blob.data), deny.name, source_line,
                                         start, end, ordinal, hashlib.sha256(matched).hexdigest(),
                                         fingerprints[deny.name])
                    result.append(_Occurrence(identity, patch_line, added_line, found.start(), found.end()))
        if (old_seen, new_seen) != (old_count, new_count):
            raise ValueError('hunk')
    return new_path, result


def map_added_occurrences(patch: bytes, *, repo_id: str,
                          blobs: dict[str, CommittedBlob]) -> tuple[_Occurrence, ...]:
    """Map exact added bytes to complete verified blobs, or grant no context.

    Takes only the raw, already selected patch and independently acquired blobs.
    Unsupported/malformed optional context returns empty; the caller must retain
    its baseline findings. Includes ALL detector families before allowlisting.
    """
    try:
        if type(patch) is not bytes or len(patch) > PATCH_LIMIT or not _repo_id(repo_id):
            return ()
        if len(blobs) > PATH_LIMIT or sum(len(b.data) for b in blobs.values()) > BLOB_TOTAL_LIMIT:
            return ()
        raw_lines = patch.split(b'\n')
        if raw_lines[-1]:
            return ()
        sections = []
        for number, raw in enumerate(raw_lines[:-1], 1):
            line = raw + b'\n'
            if line.startswith(b'diff --git '):
                sections.append([])
            if sections:
                sections[-1].append((number, line))
        if len(sections) > PATH_LIMIT:
            return ()
        result, seen = [], set()
        for section in sections:
            path, occurrences = _map_file(section, repo_id, blobs)
            if path is not None:
                if path in seen:
                    return ()
                seen.add(path)
            result.extend(occurrences)
        return tuple(result)
    except (ValueError, TypeError, UnicodeError, OverflowError):
        return ()


def approved_occurrences(catalog: _Catalog, occurrences: tuple[_Occurrence, ...]) -> tuple[_Occurrence, ...]:
    """Pure exact matching for a caller that separately verified release trust.

    No trust is inferred here. The current scanner does not call this function.
    Retain all occurrences outside the returned tuple before Finding projection.
    """
    identities = {record.identity for record in catalog.records}
    return tuple(occurrence for occurrence in occurrences if occurrence.identity in identities)
