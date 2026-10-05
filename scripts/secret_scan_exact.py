"""Bounded committed source acquisition and pure exact-occurrence matching.

Blobs and parsed catalogs describe identities, never approval. No worktree/index
source substitutes are accepted. Read-valid trust pins are separate from
release integrity; enrollment is a separate explicitly authorized operation.
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
import zlib

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

# These pins are only inputs to the future archive integrity check. Nothing in
# this section calls approved_occurrences or changes scanner decisions.
TRUST_JSON_LIMIT = 1024 * 1024
_INSTANCE_MARKER = 'shipwright-secret-scan-instance-v1.json'


@dataclass(frozen=True)
class _PendingReleaseTrust:
    """Read-valid operator pins, NOT verified release or exception authority."""
    archive_path: Path
    release_id: str
    archive_sha256: str
    catalog_sha256: str
    common_dir: Path
    repo_id: str
    instance_nonce: str


class _TrustInvalid(ValueError):
    pass


def _trust_invalid() -> None:
    raise _TrustInvalid('secret-scan: optional trust unavailable')


def _trust_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            _trust_invalid()
        value[key] = item
    return value


def _trust_document(data: bytes, keys: set[str]) -> dict:
    if len(data) > TRUST_JSON_LIMIT:
        _trust_invalid()
    value = json.loads(data.decode('utf-8'), object_pairs_hook=_trust_object,
                       parse_constant=lambda _: _trust_invalid())
    if (type(value) is not dict or set(value) != keys
            or type(value['schemaVersion']) is not int or value['schemaVersion'] != 1):
        _trust_invalid()
    return value


def _absolute_trust_path(value: object) -> Path:
    # Do not silently normalize traversal, separators, or a relative pin.
    if (type(value) is not str or len(value.encode('utf-8')) > 4096
            or not value.startswith('/') or value.startswith('//')
            or any(ord(c) < 32 or ord(c) == 127 for c in value)
            or '\\' in value or any(p in ('', '.', '..') for p in value[1:].split('/'))):
        _trust_invalid()
    return Path(value)


def _normalized_origin(value: str) -> str:
    """A deliberately narrow credential-free GitHub HTTPS/SSH grammar.

    The literal SSH transport user `git` is not an embedded credential. Ports,
    escapes, alternate users, query/fragment, local paths and URL rewrites are
    never normalized into an approved identity.
    """
    match = re.fullmatch(
        r'(?:https://github\.com/|ssh://git@github\.com/|git@github\.com:)'
        r'([A-Za-z0-9_-][A-Za-z0-9._-]*)/([A-Za-z0-9_-][A-Za-z0-9._-]*)',
        value, re.IGNORECASE | re.ASCII)
    if match is None:
        _trust_invalid()
    owner, repo = match.groups()
    if repo.lower().endswith('.git'):
        repo = repo[:-4]
    if not repo or repo in ('.', '..') or owner in ('.', '..'):
        _trust_invalid()
    return 'github.com/' + owner.lower() + '/' + repo.lower()


def _repository_trust_identity(acq: Acquisition, root: Path) -> tuple[Path, str]:
    # These change which repository/config Git reads. Do not let a consumer
    # redirect the fixed marker through process configuration. --local below
    # excludes home/system origins, and --get-all rejects multiple URLs.
    if any(key in os.environ for key in (
            'GIT_DIR', 'GIT_WORK_TREE', 'GIT_COMMON_DIR', 'GIT_CONFIG',
            'GIT_CONFIG_COUNT', 'GIT_CONFIG_PARAMETERS')):
        _trust_invalid()
    common = acq.git(['rev-parse', '--path-format=absolute', '--git-common-dir'],
                     cwd=root, stdout_limit=4097)
    if not common.endswith(b'\n') or b'\n' in common[:-1] or b'\r' in common:
        _trust_invalid()
    directory = _absolute_trust_path(common[:-1].decode('utf-8'))
    # A symlink in the common-dir spelling is ineligible, not a way to bypass
    # the checked no-follow path traversal that follows.
    if directory.resolve(strict=True) != directory:
        _trust_invalid()
    origins = acq.git(['config', '--local', '--null', '--get-all', 'remote.origin.url'],
                      cwd=root, stdout_limit=4096)
    if not origins.endswith(b'\0') or b'\0' in origins[:-1]:
        _trust_invalid()
    return directory, _normalized_origin(origins[:-1].decode('utf-8'))


def _trust_primitives() -> bool:
    return (os.name == 'posix' and hasattr(os, 'getuid') and hasattr(os, 'geteuid')
            and os.getuid() == os.geteuid()
            and all(getattr(os, key, 0) for key in ('O_NOFOLLOW', 'O_DIRECTORY', 'O_NONBLOCK'))
            and os.open in os.supports_dir_fd and os.stat in os.supports_dir_fd
            and os.stat in os.supports_follow_symlinks)


def _stat_identity(info, *, file: bool = False) -> tuple:
    identity = (info.st_dev, info.st_ino, info.st_uid, info.st_gid, info.st_mode)
    # Directory timestamps change in normal Git use and are not lifecycle
    # authority. File mutation during a read, however, invalidates that read.
    return identity + ((info.st_size, info.st_mtime_ns, info.st_ctime_ns, info.st_nlink)
                       if file else ())


class _DarwinAclInspector:
    """Descriptor ACL snapshots via Darwin's system library, never shell tools.

    acl_copy_ext exports the documented big-endian kauth_filesec layout:
    44-byte header and 24-byte entries (sys/acl.h, sys/kauth.h). A closed
    grammar admits only known deny entries. No principal/name lookup is needed.
    Other ACL platforms are intentionally unsupported, not assumed mode-only.
    """
    def __init__(self) -> None:
        import ctypes
        import sys

        if sys.platform != 'darwin':
            _trust_invalid()
        try:
            # Fixed system library, not a consumer path or library search result.
            self.lib = ctypes.CDLL('/usr/lib/libSystem.B.dylib', use_errno=True)
            signatures = (
                ('acl_get_fd_np', [ctypes.c_int, ctypes.c_int], ctypes.c_void_p),
                ('acl_size', [ctypes.c_void_p], ctypes.c_ssize_t),
                ('acl_copy_ext', [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ssize_t], ctypes.c_ssize_t),
                ('acl_free', [ctypes.c_void_p], ctypes.c_int),
            )
            for name, args, result in signatures:
                function = getattr(self.lib, name)
                function.argtypes = args
                function.restype = result
        except (OSError, AttributeError):
            _trust_invalid()

    def _read(self, fd: int) -> bytes:
        import ctypes
        import errno

        ctypes.set_errno(0)
        acl = self.lib.acl_get_fd_np(fd, 0x100)  # ACL_TYPE_EXTENDED
        if not acl:
            # Darwin filesec_get_property reports ENOENT for an absent ACL on
            # an open descriptor. All other failures, including ENOTSUP, deny.
            if ctypes.get_errno() == errno.ENOENT:
                return b''
            _trust_invalid()
        try:
            size = self.lib.acl_size(acl)
            if not 44 <= size <= 44 + 128 * 24:
                _trust_invalid()
            buffer = ctypes.create_string_buffer(size)
            if self.lib.acl_copy_ext(buffer, acl, size) != size:
                _trust_invalid()
            return buffer.raw
        finally:
            if self.lib.acl_free(acl) != 0:
                _trust_invalid()

    def identity(self, fd: int) -> bytes:
        import struct

        data = self._read(fd)
        if data == b'':
            return data  # Known absent ACL, distinct from an explicit empty ACL.
        if not 44 <= len(data) <= 44 + 128 * 24:
            _trust_invalid()
        magic, unused_ids, count, flags = struct.unpack('>I32sII', data[:44])
        if (magic != 0x012cc16d or unused_ids != b'\0' * 32 or count > 128
                or len(data) != 44 + count * 24 or flags & ~0x20000):
            # Only NO_INHERIT is understood; deferred inheritance, private or
            # future ACL-wide flags cannot silently acquire new semantics.
            _trust_invalid()
        for offset in range(44, len(data), 24):
            entry_flags, rights = struct.unpack('>II', data[offset + 16:offset + 24])
            if (entry_flags & 0xf != 2 or entry_flags & ~0x1f2
                    or rights & ~0x103ffe):
                # DENY plus the five known inheritance bits; known file rights
                # only. Even an owner-only or inherit-only ALLOW is declined.
                _trust_invalid()
        return data


class _CheckedTrustPaths:
    """Keep each no-follow directory/file descriptor and its name binding live."""
    def __init__(self, uid: int, acq: Acquisition) -> None:
        self.uid = uid
        self.acq = acq
        self.handles: list[int] = []
        self.bindings: list[tuple[int | None, str, int, tuple, bool, bytes]] = []
        self.acl = _DarwinAclInspector()

    def close(self) -> None:
        for fd in reversed(self.handles):
            os.close(fd)
        self.handles.clear()

    def _deadline(self) -> None:
        if time.monotonic() >= self.acq.deadline:
            _trust_invalid()

    def _open(self, name: str, parent: int | None, *, directory: bool,
              private: bool = False, owner: bool = False) -> int:
        import stat

        self._deadline()
        flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
        if directory:
            flags |= os.O_DIRECTORY
        fd = os.open(name, flags, dir_fd=parent)
        self.handles.append(fd)
        info = os.fstat(fd)
        mode = stat.S_IMODE(info.st_mode)
        if directory:
            if (not stat.S_ISDIR(info.st_mode) or info.st_uid not in (0, self.uid)
                    or mode & 0o022 or (owner and info.st_uid != self.uid)
                    or (private and (info.st_uid != self.uid or mode != 0o700))):
                _trust_invalid()
        elif (not stat.S_ISREG(info.st_mode) or info.st_uid != self.uid
              or mode != 0o600 or info.st_nlink != 1 or info.st_size > TRUST_JSON_LIMIT):
            _trust_invalid()
        identity = _stat_identity(info, file=not directory)
        named = os.stat(name, dir_fd=parent, follow_symlinks=False)
        if _stat_identity(named, file=not directory) != identity:
            _trust_invalid()
        acl_identity = self.acl.identity(fd)
        self.bindings.append((parent, name, fd, identity, not directory, acl_identity))
        return fd

    def directory(self, path: Path, *, private_from: Path | None = None) -> int:
        # Always walk from /; resolving first would erase symlink evidence.
        _absolute_trust_path(str(path))
        fd = self._open('/', None, directory=True)
        prefix = Path('/')
        for part in path.parts[1:]:
            prefix /= part
            private = private_from is not None and (prefix == private_from or private_from in prefix.parents)
            fd = self._open(part, fd, directory=True, private=private, owner=prefix == path)
        return fd

    def read_json(self, parent: int, name: str) -> bytes:
        fd = self._open(name, parent, directory=False)
        result = bytearray()
        while True:
            self._deadline()
            chunk = os.read(fd, min(65536, TRUST_JSON_LIMIT + 1 - len(result)))
            if not chunk:
                break
            result.extend(chunk)
            if len(result) > TRUST_JSON_LIMIT:
                _trust_invalid()
        self.validate()
        return bytes(result)

    def validate(self) -> None:
        self._deadline()
        for parent, name, fd, expected, file, acl_identity in self.bindings:
            if (_stat_identity(os.fstat(fd), file=file) != expected
                    or _stat_identity(os.stat(name, dir_fd=parent, follow_symlinks=False), file=file) != expected
                    or self.acl.identity(fd) != acl_identity):
                _trust_invalid()


def read_pending_release_trust(root: Path) -> _PendingReleaseTrust | None:
    """Read fixed operator/instance pins; NEVER approve exceptions from them.

    The account database, not HOME or XDG_CONFIG_HOME, selects the home. Tests
    may substitute pwd.getpwuid in-process; there is deliberately no production
    path override. Platforms without the checked primitives decline all pins.

    Descriptors and path identities remain checked through both JSON reads and
    a second Git identity acquisition. There are no writes/caches. Phase 4 must
    independently verify the entire pinned archive, catalog and source modules
    before these pins can contribute to a filtering decision.
    """
    paths = None
    try:
        if not _trust_primitives():
            return None
        import pwd

        uid = os.getuid()
        home = _absolute_trust_path(pwd.getpwuid(uid).pw_dir)
        with acquisition_scope() as acq:
            paths = _CheckedTrustPaths(uid, acq)
            directory, origin = _repository_trust_identity(acq, root)
            trust_dir = paths.directory(home / '.config/shipwright/secret-scan',
                                        private_from=home / '.config')
            data = paths.read_json(trust_dir, 'trust-v1.json')
            trust = _trust_document(data, {'schemaVersion', 'archivePath', 'releaseId',
                                         'archiveSha256', 'catalogSha256', 'repository'})
            archive = _absolute_trust_path(trust['archivePath'])
            if (not _token(trust['releaseId']) or not _digest(trust['archiveSha256'])
                    or not _digest(trust['catalogSha256'])):
                _trust_invalid()
            repo = trust['repository']
            if (type(repo) is not dict or set(repo) != {'commonDir', 'origin', 'instanceNonce'}
                    or repo['commonDir'] != str(directory) or repo['origin'] != origin
                    or not _digest(repo['instanceNonce'])):
                _trust_invalid()
            common_fd = paths.directory(directory)
            marker = _trust_document(paths.read_json(common_fd, _INSTANCE_MARKER),
                                     {'schemaVersion', 'instanceNonce'})
            if not _digest(marker['instanceNonce']) or marker['instanceNonce'] != repo['instanceNonce']:
                _trust_invalid()
            if _repository_trust_identity(acq, root) != (directory, origin):
                _trust_invalid()
            paths.validate()
            return _PendingReleaseTrust(archive, trust['releaseId'], trust['archiveSha256'],
                                        trust['catalogSha256'], directory, origin, repo['instanceNonce'])
    except (OSError, ValueError, TypeError, UnicodeError, RuntimeError, KeyError,
            ImportError, NotImplementedError, RecursionError, OverflowError):
        # Optional trust never changes completed baseline findings. No raw JSON,
        # path, origin, source bytes or subprocess stderr enter new diagnostics.
        return None
    finally:
        if paths is not None:
            paths.close()

# Release validation is deliberately separate from read-valid operator pins.
ARCHIVE_LIMIT = 128 * 1024 * 1024
ARCHIVE_MEMBER_LIMIT = 2048
ARCHIVE_DIRECTORY_LIMIT = 4 * 1024 * 1024
MODULE_LIMIT = 1024 * 1024
_CATALOG_MEMBER = 'secret_scan_data/reviewed-occurrences.v1.json'
_SOURCE_MEMBERS = ('secret_scan.py', 'secret_scan_exact.py', 'secret_patterns.py')


@dataclass(frozen=True)
class _VerifiedRelease:
    pins: _PendingReleaseTrust
    catalog: _Catalog


def _bounded_fd(fd: int, limit: int, acq: Acquisition) -> bytes:
    result = bytearray()
    while True:
        if time.monotonic() >= acq.deadline:
            _trust_invalid()
        data = os.read(fd, min(65536, limit + 1 - len(result)))
        if not data:
            return bytes(result)
        result.extend(data)
        if len(result) > limit:
            _trust_invalid()


class _ReleaseArchive:
    """Pinned archive descriptor with bounded metadata and member decompression."""
    def __init__(self, paths: _CheckedTrustPaths, path: Path, digest: str) -> None:
        import stat

        self.paths = paths
        parent = paths.directory(path.parent)
        paths._deadline()
        self.fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        paths.handles.append(self.fd)
        info = os.fstat(self.fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid not in (0, paths.uid)
                or stat.S_IMODE(info.st_mode) & 0o022 or info.st_nlink != 1
                or info.st_size > ARCHIVE_LIMIT or info.st_size < 22):
            _trust_invalid()
        self.size = info.st_size
        expected = _stat_identity(info, file=True)
        paths.bindings.append((parent, path.name, self.fd, expected, True, paths.acl.identity(self.fd)))
        paths.validate()
        self.digest = digest
        self.check_hash()

    def check_hash(self) -> None:
        self.paths.validate()
        os.lseek(self.fd, 0, os.SEEK_SET)
        digest = hashlib.sha256()
        remaining = self.size
        while remaining:
            self.paths._deadline()
            data = os.read(self.fd, min(65536, remaining))
            if not data:
                _trust_invalid()
            digest.update(data)
            remaining -= len(data)
        if os.read(self.fd, 1) or digest.hexdigest() != self.digest:
            _trust_invalid()
        self.paths.validate()

    def read_at(self, offset: int, length: int) -> bytes:
        self.paths._deadline()
        if offset < 0 or length < 0 or offset + length > self.size:
            _trust_invalid()
        os.lseek(self.fd, offset, os.SEEK_SET)
        output = bytearray()
        while len(output) < length:
            self.paths._deadline()
            data = os.read(self.fd, min(65536, length - len(output)))
            if not data:
                _trust_invalid()
            output.extend(data)
        return bytes(output)

    def preflight(self) -> dict[str, tuple[int, int, int, int, int]]:
        import stat
        import struct

        tail = self.read_at(max(0, self.size - 65557), min(self.size, 65557))
        index = tail.rfind(b'PK\x05\x06')
        if index < 0 or index + 22 > len(tail):
            _trust_invalid()
        _, disk, start_disk, disk_count, count, size, offset, comment = struct.unpack(
            '<4s4H2IH', tail[index:index + 22])
        end = self.size - len(tail) + index
        if (disk or start_disk or disk_count != count or not 0 < count <= ARCHIVE_MEMBER_LIMIT
                or size > ARCHIVE_DIRECTORY_LIMIT or index + 22 + comment != len(tail)
                or size > end or offset > end - size):
            _trust_invalid()
        # ZIP64 and split archives have no role in these bounded releases.
        if end >= 20 and self.read_at(end - 20, 4) == b'PK\x06\x07':
            _trust_invalid()
        start = end - size
        prefix = start - offset  # zipapp's optional interpreter prefix
        directory = self.read_at(start, size)
        cursor = 0
        names = set()
        ranges = []
        members = {}
        for _ in range(count):
            self.paths._deadline()
            if cursor + 46 > size or directory[cursor:cursor + 4] != b'PK\x01\x02':
                _trust_invalid()
            values = struct.unpack('<4s6H3I5H2I', directory[cursor:cursor + 46])
            (_, made, needed, flags, method, _, _, crc, compressed, raw,
             name_len, extra_len, comment_len, disk_no, _, attrs, local) = values
            next_cursor = cursor + 46 + name_len + extra_len + comment_len
            if (next_cursor > size or not name_len or disk_no or needed >= 45
                    or compressed == 0xffffffff or raw == 0xffffffff or local == 0xffffffff
                    or flags & ~0x808 or method not in (0, 8)):
                _trust_invalid()
            name_bytes = directory[cursor + 46:cursor + 46 + name_len]
            name = name_bytes.decode('utf-8' if flags & 0x800 else 'cp437')
            normalized = name[:-1] if name.endswith('/') else name
            if (not normalized or normalized in names or '\\' in name or name.startswith('/')
                    or any(ord(c) < 32 or ord(c) == 127 for c in name)
                    or any(p in ('', '.', '..') for p in normalized.split('/'))
                    or ':' in name or stat.S_IFMT(attrs >> 16) not in (0, stat.S_IFREG, stat.S_IFDIR)
                    or (stat.S_ISDIR(attrs >> 16) and not name.endswith('/'))):
                _trust_invalid()
            names.add(normalized)
            if name in (*_SOURCE_MEMBERS, _CATALOG_MEMBER) and raw > MODULE_LIMIT:
                _trust_invalid()
            position = prefix + local
            header = self.read_at(position, 30)
            if header[:4] != b'PK\x03\x04':
                _trust_invalid()
            h = struct.unpack('<4s5H3I2H', header)
            if (h[1] != needed or h[2] != flags or h[3] != method or h[9] != name_len
                    or self.read_at(position + 30, name_len) != name_bytes):
                _trust_invalid()
            if not flags & 8 and (h[6], h[7], h[8]) != (crc, compressed, raw):
                _trust_invalid()
            data_start = position + 30 + name_len + h[10]
            data_end = data_start + compressed
            if position < prefix or data_end > start:
                _trust_invalid()
            if flags & 8:
                descriptor = self.read_at(data_end, 4)
                signed = descriptor == b'PK\x07\x08'
                descriptor = self.read_at(data_end + (4 if signed else 0), 12)
                if struct.unpack('<3I', descriptor) != (crc, compressed, raw):
                    _trust_invalid()
                data_end += 16 if signed else 12
                if data_end > start:
                    _trust_invalid()
            members[name] = (data_start, compressed, raw, crc, method)
            ranges.append((position, data_end))
            cursor = next_cursor
        if cursor != size or not set((*_SOURCE_MEMBERS, _CATALOG_MEMBER)) <= names:
            _trust_invalid()
        ordered = sorted(ranges)
        if any(right[0] < left[1] for left, right in zip(ordered, ordered[1:])):
            _trust_invalid()
        self.paths.validate()
        return members

    def members(self) -> dict[str, bytes]:
        metadata = self.preflight()
        output = {}
        # Parse no archive-controlled metadata twice. Bounded central-directory
        # entries feed a streaming inflater, so a concurrent metadata rewrite
        # cannot make a library allocate an unbounded replacement directory.
        for name in (*_SOURCE_MEMBERS, _CATALOG_MEMBER):
            offset, compressed, raw, crc, method = metadata[name]
            if raw > MODULE_LIMIT or (method == 0 and compressed != raw):
                _trust_invalid()
            inflater = zlib.decompressobj(-15) if method == 8 else None
            data = bytearray()
            consumed = 0
            while consumed < compressed:
                self.paths._deadline()
                chunk = self.read_at(offset + consumed, min(65536, compressed - consumed))
                consumed += len(chunk)
                while chunk:
                    self.paths._deadline()
                    if inflater is None:
                        expanded, chunk = chunk, b''
                    else:
                        expanded = inflater.decompress(chunk, MODULE_LIMIT + 1 - len(data))
                        chunk = inflater.unconsumed_tail
                    data.extend(expanded)
                    if len(data) > MODULE_LIMIT:
                        _trust_invalid()
                    if inflater is not None and inflater.unused_data:
                        _trust_invalid()
            if (len(data) != raw or zlib.crc32(data) != crc
                    or (inflater is not None and not inflater.eof)):
                _trust_invalid()
            output[name] = bytes(data)
        self.check_hash()
        return output


def _current_source_matches(members: dict[str, bytes], archive_path: Path,
                            paths: _CheckedTrustPaths) -> None:
    import stat
    import sys

    parent = Path(os.path.abspath(__file__)).parent
    # Reject mixed module origins in both source and archive dispatch modes.
    for key in ('secret_scan', 'secret_scan_exact', 'secret_patterns', '__main__'):
        module = sys.modules.get(key)
        filename = getattr(module, '__file__', None)
        if (filename and Path(filename).name in _SOURCE_MEMBERS
                and Path(os.path.abspath(filename)).parent != parent):
            _trust_invalid()
    if parent == archive_path:
        # Direct zipapp and emitted shim retain package dispatch's own gate.
        return
    if parent.parent == archive_path.parent and parent.is_symlink():
        # The standard install launches a relative stable alias while trust
        # pins the regular versioned archive. Bind that single alias itself,
        # never follow a symlink pin or normalize an arbitrary target chain.
        if not getattr(os, 'O_SYMLINK', 0) or os.readlink not in os.supports_dir_fd:
            _trust_invalid()
        directory = paths.directory(parent.parent)
        paths._deadline()
        # Darwin O_SYMLINK opens the link object; O_NOFOLLOW in combination
        # instead rejects it. Descriptor type and name identity are mandatory.
        fd = os.open(parent.name, os.O_RDONLY | os.O_SYMLINK | os.O_NONBLOCK,
                     dir_fd=directory)
        paths.handles.append(fd)
        info = os.fstat(fd)
        if (not stat.S_ISLNK(info.st_mode) or info.st_uid not in (0, paths.uid)
                or info.st_nlink != 1):
            _trust_invalid()
        paths.bindings.append((directory, parent.name, fd, _stat_identity(info, file=True),
                               True, paths.acl.identity(fd)))
        paths.validate()
        if os.readlink(parent.name, dir_fd=directory) != archive_path.name:
            _trust_invalid()
        paths.validate()
        return
    for name in _SOURCE_MEMBERS:
        source = parent / name
        fd = os.open(source, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_size > MODULE_LIMIT:
                _trust_invalid()
            before = _stat_identity(info, file=True)
            if (_bounded_fd(fd, MODULE_LIMIT, paths.acq) != members[name]
                    or _stat_identity(os.fstat(fd), file=True) != before
                    or _stat_identity(os.stat(source, follow_symlinks=False), file=True) != before):
                _trust_invalid()
        finally:
            os.close(fd)


def _validated_release(paths: _CheckedTrustPaths, archive_path: Path,
                       archive_digest: str, catalog_digest: str) -> _Catalog:
    archive = _ReleaseArchive(paths, archive_path, archive_digest)
    members = archive.members()
    if hashlib.sha256(members[_CATALOG_MEMBER]).hexdigest() != catalog_digest:
        _trust_invalid()
    _current_source_matches(members, archive_path, paths)
    catalog = parse_catalog(members[_CATALOG_MEMBER])
    paths.validate()
    return catalog


def read_verified_release(root: Path) -> _VerifiedRelease | None:
    """Read-only library API for pre-push; absent integrity retains all findings."""
    paths = None
    try:
        with acquisition_scope() as acq:
            pins = read_pending_release_trust(root)
            if pins is None:
                return None
            import pwd

            home = _absolute_trust_path(pwd.getpwuid(os.getuid()).pw_dir)
            paths = _CheckedTrustPaths(os.getuid(), acq)
            trust_fd = paths.directory(home / '.config/shipwright/secret-scan', private_from=home / '.config')
            paths.read_json(trust_fd, 'trust-v1.json')
            common_fd = paths.directory(pins.common_dir)
            paths.read_json(common_fd, _INSTANCE_MARKER)
            # Re-read the strict binding while the new descriptors are held.
            if read_pending_release_trust(root) != pins:
                _trust_invalid()
            catalog = _validated_release(paths, pins.archive_path, pins.archive_sha256, pins.catalog_sha256)
            if _repository_trust_identity(acq, root) != (pins.common_dir, pins.repo_id):
                _trust_invalid()
            paths.validate()
            return _VerifiedRelease(pins, catalog)
    except (OSError, ValueError, TypeError, UnicodeError, RuntimeError, KeyError,
            ImportError, NotImplementedError, RecursionError, OverflowError, EOFError, zlib.error):
        return None
    finally:
        if paths is not None:
            paths.close()


def _publication_primitives() -> bool:
    return (_trust_primitives() and os.mkdir in os.supports_dir_fd
            and os.unlink in os.supports_dir_fd and os.link in os.supports_dir_fd
            and os.link in os.supports_follow_symlinks
            and os.rename in os.supports_dir_fd and callable(getattr(os, 'fsync', None)))


def _atomic_trust_write(paths: _CheckedTrustPaths, parent: int, name: str,
                        document: dict, *, create_only: bool = False) -> None:
    import secrets

    data = _canonical_json(document) + b'\n'
    if len(data) > TRUST_JSON_LIMIT:
        _trust_invalid()
    paths.validate()
    temporary = '.shipwright-secret-scan-' + secrets.token_hex(32) + '.tmp'
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_NONBLOCK,
                 0o600, dir_fd=parent)
    try:
        # Do not chmod even a temporary file: restrictive umasks must fail safe.
        info = os.fstat(fd)
        if (info.st_uid != paths.uid or info.st_mode & 0o7777 != 0o600 or info.st_nlink != 1):
            _trust_invalid()
        acl = paths.acl.identity(fd)
        offset = 0
        while offset < len(data):
            paths._deadline()
            written = os.write(fd, data[offset:])
            if written <= 0:
                _trust_invalid()
            offset += written
        os.fsync(fd)
        paths.validate()
        if (_stat_identity(os.stat(temporary, dir_fd=parent, follow_symlinks=False), file=True)
                != _stat_identity(os.fstat(fd), file=True) or paths.acl.identity(fd) != acl):
            _trust_invalid()
        if create_only:
            os.link(temporary, name, src_dir_fd=parent, dst_dir_fd=parent, follow_symlinks=False)
        else:
            os.replace(temporary, name, src_dir_fd=parent, dst_dir_fd=parent)
        # Existing file descriptors refer to the intentionally replaced inode.
        paths.bindings[:] = [b for b in paths.bindings if not (b[0] == parent and b[1] == name)]
    finally:
        os.close(fd)
        try:
            os.unlink(temporary, dir_fd=parent)
        except FileNotFoundError:
            pass
    os.fsync(parent)
    paths.read_json(parent, name)


def enroll_exact(root: Path, *, archive_path: Path, release_id: str,
                 expected_archive_sha256: str, expected_catalog_sha256: str,
                 expected_common_dir: Path, expected_origin: str,
                 authorize_marker_write: bool = False, replace_marker: bool = False) -> bool:
    """Explicit scanner-only enrollment; callers supply human-approved actual pins.

    This API never discovers approval from installed bytes. Account home and
    marker/trust names are fixed. False is a private, payload-free refusal.
    """
    paths = None
    try:
        if (authorize_marker_write is not True or type(replace_marker) is not bool
                or not _publication_primitives() or not _token(release_id)
                or not _digest(expected_archive_sha256) or not _digest(expected_catalog_sha256)
                or not _repo_id(expected_origin)):
            return False
        import pwd
        import secrets

        archive_path = _absolute_trust_path(str(archive_path))
        expected_common_dir = _absolute_trust_path(str(expected_common_dir))
        home = _absolute_trust_path(pwd.getpwuid(os.getuid()).pw_dir)
        with acquisition_scope() as acq:
            directory, origin = _repository_trust_identity(acq, root)
            if (directory, origin) != (expected_common_dir, expected_origin):
                _trust_invalid()
            paths = _CheckedTrustPaths(os.getuid(), acq)
            common_fd = paths.directory(directory)
            home_fd = paths.directory(home)
            _validated_release(paths, archive_path, expected_archive_sha256, expected_catalog_sha256)
            try:
                marker = _trust_document(paths.read_json(common_fd, _INSTANCE_MARKER),
                                         {'schemaVersion', 'instanceNonce'})
                if not _digest(marker['instanceNonce']):
                    _trust_invalid()
                nonce = marker['instanceNonce']
                existing = True
            except FileNotFoundError:
                nonce = None
                existing = False
            # Inspect every existing directory and trust file before any write.
            parent = home_fd
            missing = []
            for name in ('.config', 'shipwright', 'secret-scan'):
                if missing:
                    missing.append(name)
                    continue
                try:
                    parent = paths._open(name, parent, directory=True, private=True)
                except FileNotFoundError:
                    missing.append(name)
            if not missing:
                try:
                    paths.read_json(parent, 'trust-v1.json')
                except FileNotFoundError:
                    pass
            if _repository_trust_identity(acq, root) != (directory, origin):
                _trust_invalid()
            paths.validate()
            # All expected pins, identity and existing state are validated now.
            for name in missing:
                paths.validate()
                os.mkdir(name, 0o700, dir_fd=parent)
                os.fsync(parent)
                parent = paths._open(name, parent, directory=True, private=True)
            if nonce is None or replace_marker:
                nonce = secrets.token_hex(32)
                _atomic_trust_write(paths, common_fd, _INSTANCE_MARKER,
                                    {'schemaVersion': 1, 'instanceNonce': nonce}, create_only=not existing)
            trust = {'schemaVersion': 1, 'archivePath': str(archive_path), 'releaseId': release_id,
                     'archiveSha256': expected_archive_sha256, 'catalogSha256': expected_catalog_sha256,
                     'repository': {'commonDir': str(directory), 'origin': origin, 'instanceNonce': nonce}}
            paths.validate()
            if _repository_trust_identity(acq, root) != (directory, origin):
                _trust_invalid()
            _atomic_trust_write(paths, parent, 'trust-v1.json', trust)
            paths.validate()
            return True
    except (OSError, ValueError, TypeError, UnicodeError, RuntimeError, KeyError,
            ImportError, NotImplementedError, RecursionError, OverflowError, EOFError, zlib.error):
        return False
    finally:
        if paths is not None:
            paths.close()
