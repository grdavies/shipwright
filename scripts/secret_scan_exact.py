"""Bounded, read-only Git acquisition for the committed pre-push scanner.

Acquired blobs are source context only, never approval. No worktree/index reads,
trust loading, catalog filtering or enrollment are performed here.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
import hashlib
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
