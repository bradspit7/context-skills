#!/usr/bin/env python
"""Build and verify complete exact-content sanction packets.

This helper is intentionally evidence-only.  It freezes a declared scope,
derives filesystem/Git evidence, renders the full review artifacts, and verifies
that the reviewed state remains current.  It NEVER applies target bytes, stages,
rolls back, commits, or authenticates that an owner actually approved anything.

Its strongest claim is deliberately narrow:

    mechanically complete for owner-approved declared scope

CLI:
    sanction-packet.py build SPEC.json --out ABSOLUTE_DIR [--hmac-key-file FILE]
    sanction-packet.py decision LOCK.json --verdict approved|rejected
        --evidence-file FILE [--hmac-key-file FILE]
    sanction-packet.py verify LOCK.json --phase pre-decision|pre-apply|
        adoption-freshness|mixed-freshness|post-apply|pre-commit|post-commit
        [--commits FILE] [--hmac-key-file FILE]
    sanction-packet.py receipt LOCK.json --out RECEIPT.md
        --failure-point TEXT [--hmac-key-file FILE]
"""

from __future__ import annotations

import argparse
import datetime as dt
import difflib
import errno
import hashlib
import hmac
import html
import json
import os
import platform
import re
import secrets
import stat
import subprocess
import sys
import unicodedata
from pathlib import Path, PurePosixPath
from typing import Any

if os.name == "nt":
    import ctypes
    from ctypes import wintypes


VERSION = "1.1.0"
SCHEMA = "sanction-packet/v1"
DECISION_SCHEMA = "sanction-decision/v1"
CLAIM = "mechanically complete for owner-approved declared scope"
EXIT_INVALID = 2
EXIT_INCOMPLETE = 3

# --- Task 7: the ordered, one-use lifecycle -------------------------------
#
# `pre-decision` is a repeatable pre-approval diagnostic and is deliberately
# NOT a chain member.  The chain root is the owner decision record; every
# later phase chains to its predecessor's receipt binding.
PHASE_PRE_DECISION = "pre-decision"
LIFECYCLE_PHASES = (
    "pre-apply",
    "adoption-freshness",
    "mixed-freshness",
    "post-apply",
    "pre-commit",
    "post-commit",
)
ALL_PHASES = (PHASE_PRE_DECISION, *LIFECYCLE_PHASES)

# The live leg is selected by the packet's entry composition; the commit leg is
# appended only when the packet actually has Git commit candidates, which makes
# the plan's "no Git commit candidates" row fall out as non-membership.
_LIVE_SEQUENCE = {
    "all-pre-apply": ("pre-apply", "post-apply"),
    "all-already-applied": ("adoption-freshness",),
    "mixed": ("mixed-freshness", "post-apply"),
}
_COMMIT_SEQUENCE = ("pre-commit", "post-commit")

# Phases whose gate asserts the declared *entry* state rather than the applied
# target state.  Each is reachable only from its own entry composition, which
# sequence membership enforces.
_ENTRY_PHASES = frozenset({"pre-apply", "adoption-freshness", "mixed-freshness"})

LIFECYCLE_SCHEMA = "sanction-lifecycle/v1"

# Task 8: semantic staged-byte review is an ATTESTATION, not authentication.
# The reviewer/agent states which exact candidate identity set they reviewed;
# the helper recomputes that set from the lock and demands exact equality. It
# proves the review names THIS packet's exact bytes -- it does NOT prove who
# wrote it, and no signature here would: the reviewer's own judgement is not
# mechanically checkable. Treat a match as "the attestation is about the right
# artifact", never as "the review is correct".
SEMANTIC_SCHEMA = "sanction-semantic-review/v1"
INVALIDATION_SCHEMA = "sanction-invalidation/v1"
# One keyset, two consumers: _semantic_evidence validates exactly these fields
# and emit_semantic_template emits exactly these fields -- shared so the
# skeleton and the gate cannot silently drift apart.
SEMANTIC_ATTESTATION_FIELDS = (
    "schema",
    "packet_id",
    "nonce",
    "helper_sha256",
    "reviewer",
    "scope_reviewed",
    "exclusions",
    "timestamp",
    "candidate_identity",
)


class SanctionError(RuntimeError):
    """A fail-closed manifest, evidence, freshness, or decision error."""


class _DriftError(SanctionError):
    """The observed world no longer matches the frozen packet evidence.

    Distinct from an operator-input error so that Task 7 can invalidate the
    packet on drift alone.  The honest threat boundary concedes that a process
    able to rewrite and restore every local input between observations is not
    defeated; refusing to resume a chain once drift has been *observed* is that
    concession's mitigation, so a restored world must not silently resume.
    """


class _PhysicalMissing(FileNotFoundError):
    """An expected physical path is absent (distinct from an unsafe path)."""


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


_WINDOWS_RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL", "CLOCK$",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}

# These primitives pin and validate the user-mode path for one read/create
# operation. They do not defend against a privileged kernel/device-namespace
# adversary, a non-cooperating same-security-principal process that repeatedly
# rewrites names/bytes between operations, or an attacker that rewrites every
# local artifact after the operation. Such environments require an external
# snapshot/sandbox boundary; this helper fails closed on observed interference.


def _lexical_absolute(path: Path, label: str) -> Path:
    """Return a normalized absolute spelling without resolving links/reparse points."""
    expanded = path.expanduser()
    if not expanded.is_absolute():
        raise SanctionError(f"{label} must be absolute: {expanded}")
    raw = str(expanded)
    if "\0" in raw:
        raise SanctionError(f"{label} contains a NUL path byte")
    if os.name == "nt":
        if raw.startswith(("\\\\?\\", "\\\\.\\", "\\??\\", "\\\\")):
            raise SanctionError(f"{label} rejects device and UNC path namespaces: {expanded}")
        drive, _tail = os.path.splitdrive(raw)
        if not re.fullmatch(r"[A-Za-z]:", drive):
            raise SanctionError(f"{label} requires an unambiguous local drive path: {expanded}")
        for component in expanded.parts[1:]:
            if component in {".", ".."} or not component:
                raise SanctionError(f"{label} contains an ambiguous path component: {expanded}")
            if (
                component.endswith((" ", "."))
                or ":" in component
                or any(ord(ch) < 32 or ch in '<>"|?*' for ch in component)
            ):
                raise SanctionError(f"{label} contains a Win32-ambiguous path component: {component!r}")
            device_stem = component.split(".", 1)[0].upper()
            if device_stem in _WINDOWS_RESERVED_NAMES:
                raise SanctionError(f"{label} contains a reserved Win32 device name: {component!r}")
    return Path(os.path.abspath(raw))


if os.name == "nt":
    _KERNEL32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
    _GENERIC_READ = 0x80000000
    _GENERIC_WRITE = 0x40000000
    _FILE_READ_ATTRIBUTES = 0x0080
    _FILE_SHARE_READ = 0x00000001
    _FILE_SHARE_WRITE = 0x00000002
    _CREATE_NEW = 1
    _OPEN_EXISTING = 3
    _FILE_ATTRIBUTE_DIRECTORY = 0x00000010
    _FILE_ATTRIBUTE_NORMAL = 0x00000080
    _FILE_ATTRIBUTE_REPARSE_POINT = 0x00000400
    _FILE_FLAG_WRITE_THROUGH = 0x80000000
    _FILE_FLAG_SEQUENTIAL_SCAN = 0x08000000
    _FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
    _FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000
    _FILE_TYPE_DISK = 0x0001
    _ERROR_FILE_NOT_FOUND = 2
    _ERROR_PATH_NOT_FOUND = 3
    _ERROR_FILE_EXISTS = 80
    _ERROR_ALREADY_EXISTS = 183

    class _FILE_ATTRIBUTE_TAG_INFO(ctypes.Structure):
        _fields_ = [("FileAttributes", wintypes.DWORD), ("ReparseTag", wintypes.DWORD)]

    class _BY_HANDLE_FILE_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("dwFileAttributes", wintypes.DWORD),
            ("ftCreationTime", wintypes.FILETIME),
            ("ftLastAccessTime", wintypes.FILETIME),
            ("ftLastWriteTime", wintypes.FILETIME),
            ("dwVolumeSerialNumber", wintypes.DWORD),
            ("nFileSizeHigh", wintypes.DWORD),
            ("nFileSizeLow", wintypes.DWORD),
            ("nNumberOfLinks", wintypes.DWORD),
            ("nFileIndexHigh", wintypes.DWORD),
            ("nFileIndexLow", wintypes.DWORD),
        ]

    _KERNEL32.CreateFileW.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
        wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
    ]
    _KERNEL32.CreateFileW.restype = wintypes.HANDLE
    _KERNEL32.CreateDirectoryW.argtypes = [wintypes.LPCWSTR, wintypes.LPVOID]
    _KERNEL32.CreateDirectoryW.restype = wintypes.BOOL
    _KERNEL32.CloseHandle.argtypes = [wintypes.HANDLE]
    _KERNEL32.CloseHandle.restype = wintypes.BOOL
    _KERNEL32.GetFileInformationByHandleEx.argtypes = [
        wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD,
    ]
    _KERNEL32.GetFileInformationByHandleEx.restype = wintypes.BOOL
    _KERNEL32.GetFileInformationByHandle.argtypes = [
        wintypes.HANDLE, ctypes.POINTER(_BY_HANDLE_FILE_INFORMATION),
    ]
    _KERNEL32.GetFileInformationByHandle.restype = wintypes.BOOL
    _KERNEL32.GetFinalPathNameByHandleW.argtypes = [
        wintypes.HANDLE, wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD,
    ]
    _KERNEL32.GetFinalPathNameByHandleW.restype = wintypes.DWORD
    _KERNEL32.GetFileType.argtypes = [wintypes.HANDLE]
    _KERNEL32.GetFileType.restype = wintypes.DWORD
    _KERNEL32.ReadFile.argtypes = [
        wintypes.HANDLE, wintypes.LPVOID, wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID,
    ]
    _KERNEL32.ReadFile.restype = wintypes.BOOL
    _KERNEL32.SetFilePointerEx.argtypes = [
        wintypes.HANDLE, ctypes.c_longlong, ctypes.POINTER(ctypes.c_longlong), wintypes.DWORD,
    ]
    _KERNEL32.SetFilePointerEx.restype = wintypes.BOOL
    _KERNEL32.WriteFile.argtypes = [
        wintypes.HANDLE, wintypes.LPCVOID, wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID,
    ]
    _KERNEL32.WriteFile.restype = wintypes.BOOL
    _KERNEL32.FlushFileBuffers.argtypes = [wintypes.HANDLE]
    _KERNEL32.FlushFileBuffers.restype = wintypes.BOOL


def _win_long(path: Path) -> str:
    return "\\\\?\\" + str(path)


def _win_error(action: str, path: Path, code: int | None = None) -> SanctionError:
    if code is None:
        code = ctypes.get_last_error()
    return SanctionError(f"{action} {path} failed with Win32 error {code}: {ctypes.FormatError(code).strip()}")


def _win_close_all(handles: list[int]) -> None:
    for handle in reversed(handles):
        if handle not in (None, _INVALID_HANDLE_VALUE):
            _KERNEL32.CloseHandle(handle)


def _win_final_path(handle: int, label: str) -> Path:
    size = 32768
    buffer = ctypes.create_unicode_buffer(size)
    length = _KERNEL32.GetFinalPathNameByHandleW(handle, buffer, size, 0)
    if not length:
        raise _win_error(f"cannot canonicalize {label}", Path("."))
    if length >= size:
        size = length + 1
        buffer = ctypes.create_unicode_buffer(size)
        length = _KERNEL32.GetFinalPathNameByHandleW(handle, buffer, size, 0)
        if not length or length >= size:
            raise _win_error(f"cannot canonicalize {label}", Path("."))
    value = buffer.value
    if value.startswith("\\\\?\\UNC\\"):
        value = "\\\\" + value[8:]
    elif value.startswith("\\\\?\\"):
        value = value[4:]
    if value.startswith("\\"):
        raise SanctionError(f"{label} resolved into an unsupported UNC/device namespace: {value}")
    return Path(os.path.normpath(value))


def _win_tag_info(handle: int, path: Path, label: str) -> _FILE_ATTRIBUTE_TAG_INFO:
    info = _FILE_ATTRIBUTE_TAG_INFO()
    if not _KERNEL32.GetFileInformationByHandleEx(handle, 9, ctypes.byref(info), ctypes.sizeof(info)):
        raise _win_error(f"cannot inspect {label}", path)
    if info.FileAttributes & _FILE_ATTRIBUTE_REPARSE_POINT:
        raise SanctionError(f"{label} crosses a reparse/symlink path component: {path}")
    return info


def _win_check_handle(handle: int, path: Path, label: str, expected: str | None) -> _FILE_ATTRIBUTE_TAG_INFO:
    info = _win_tag_info(handle, path, label)
    is_dir = bool(info.FileAttributes & _FILE_ATTRIBUTE_DIRECTORY)
    if expected == "dir" and not is_dir:
        raise SanctionError(f"{label} is not a physical directory: {path}")
    if expected == "file" and (is_dir or _KERNEL32.GetFileType(handle) != _FILE_TYPE_DISK):
        raise SanctionError(f"{label} is not a regular physical file: {path}")
    if expected is None and not is_dir and _KERNEL32.GetFileType(handle) != _FILE_TYPE_DISK:
        raise SanctionError(f"{label} is not a regular file or directory: {path}")
    final = _win_final_path(handle, label)
    if os.path.normcase(os.path.normpath(str(final))) != os.path.normcase(os.path.normpath(str(path))):
        raise SanctionError(f"{label} canonical path differs from its declared lexical path: {path} -> {final}")
    return info


def _win_open_existing(path: Path, label: str, expected: str | None, *, read: bool = False) -> int:
    access = _GENERIC_READ if read else _FILE_READ_ATTRIBUTES
    share = _FILE_SHARE_READ if read else _FILE_SHARE_READ | _FILE_SHARE_WRITE
    flags = _FILE_FLAG_OPEN_REPARSE_POINT | _FILE_FLAG_BACKUP_SEMANTICS
    if read:
        flags |= _FILE_FLAG_SEQUENTIAL_SCAN
    handle = _KERNEL32.CreateFileW(
        _win_long(path), access, share,
        None, _OPEN_EXISTING, flags, None,
    )
    if handle == _INVALID_HANDLE_VALUE:
        code = ctypes.get_last_error()
        if code in {_ERROR_FILE_NOT_FOUND, _ERROR_PATH_NOT_FOUND}:
            raise _PhysicalMissing(str(path))
        raise _win_error(f"cannot open {label}", path)
    try:
        _win_check_handle(handle, path, label, expected)
    except BaseException:
        _KERNEL32.CloseHandle(handle)
        raise
    return handle


def _win_file_stamp(handle: int, path: Path, label: str) -> tuple[int, int, int, int, int]:
    info = _BY_HANDLE_FILE_INFORMATION()
    if not _KERNEL32.GetFileInformationByHandle(handle, ctypes.byref(info)):
        raise _win_error(f"cannot inspect read stability for {label}", path)
    inode = (int(info.nFileIndexHigh) << 32) | int(info.nFileIndexLow)
    size = (int(info.nFileSizeHigh) << 32) | int(info.nFileSizeLow)
    written = (int(info.ftLastWriteTime.dwHighDateTime) << 32) | int(info.ftLastWriteTime.dwLowDateTime)
    return int(info.dwVolumeSerialNumber), inode, size, written, int(info.nNumberOfLinks)


def _win_open_directory_chain(path: Path, label: str, *, create: bool) -> list[int]:
    path = _lexical_absolute(path, label)
    anchor = Path(path.anchor)
    if not path.anchor:
        raise SanctionError(f"{label} must be absolute: {path}")
    handles: list[int] = []
    current = anchor
    try:
        handles.append(_win_open_existing(current, label, "dir"))
        for component in path.parts[1:]:
            current = current / component
            try:
                handle = _win_open_existing(current, label, "dir")
            except _PhysicalMissing:
                if not create:
                    raise
                if not _KERNEL32.CreateDirectoryW(_win_long(current), None):
                    code = ctypes.get_last_error()
                    if code not in {_ERROR_ALREADY_EXISTS, _ERROR_FILE_EXISTS}:
                        raise _win_error(f"cannot create {label}", current)
                handle = _win_open_existing(current, label, "dir")
            handles.append(handle)
        return handles
    except BaseException:
        _win_close_all(handles)
        raise


def _win_validate(path: Path, label: str, expected: str | None, *, allow_missing: bool) -> bool:
    path = _lexical_absolute(path, label)
    if path == Path(path.anchor):
        handles = _win_open_directory_chain(path, label, create=False)
        _win_close_all(handles)
        return True
    try:
        handles = _win_open_directory_chain(path.parent, label, create=False)
    except _PhysicalMissing:
        if allow_missing:
            return False
        raise SanctionError(f"{label} does not exist: {path}")
    try:
        try:
            leaf = _win_open_existing(path, label, expected)
        except _PhysicalMissing:
            if allow_missing:
                return False
            raise SanctionError(f"{label} does not exist: {path}")
        handles.append(leaf)
        return True
    finally:
        _win_close_all(handles)


def _win_read_snapshot(
    path: Path,
    label: str,
    *,
    missing_ok: bool,
) -> tuple[bytes, str, dict[str, int]] | None:
    path = _lexical_absolute(path, label)
    try:
        handles = _win_open_directory_chain(path.parent, label, create=False)
        try:
            handles.append(_win_open_existing(path, label, "file", read=True))
        except BaseException:
            _win_close_all(handles)
            raise
    except _PhysicalMissing:
        if missing_ok:
            return None
        raise SanctionError(f"{label} is not an accessible regular file: {path}")
    handle = handles[-1]
    try:
        before = _win_file_stamp(handle, path, label)

        def read_once() -> bytes:
            chunks: list[bytes] = []
            while True:
                buffer = ctypes.create_string_buffer(1024 * 1024)
                read_count = wintypes.DWORD()
                if not _KERNEL32.ReadFile(handle, buffer, len(buffer), ctypes.byref(read_count), None):
                    raise _win_error(f"cannot read {label}", path)
                if read_count.value == 0:
                    return b"".join(chunks)
                chunks.append(buffer.raw[:read_count.value])

        first = read_once()
        middle = _win_file_stamp(handle, path, label)
        new_position = ctypes.c_longlong()
        if not _KERNEL32.SetFilePointerEx(handle, 0, ctypes.byref(new_position), 0):
            raise _win_error(f"cannot rewind exact read for {label}", path)
        second = read_once()
        after = _win_file_stamp(handle, path, label)
        if first != second or before != middle or middle != after:
            raise SanctionError(f"{label} changed while its exact bytes were being read: {path}")
        return second, "100644", {"device": before[0], "inode": before[1]}
    finally:
        _win_close_all(handles)


def _win_write_new(path: Path, data: bytes) -> None:
    path = _lexical_absolute(path, "evidence artifact")
    try:
        handles = _win_open_directory_chain(path.parent, "evidence artifact parent", create=True)
    except _PhysicalMissing as exc:
        raise SanctionError(f"cannot establish physical parent for evidence artifact: {path}") from exc
    handle = _KERNEL32.CreateFileW(
        _win_long(path), _GENERIC_WRITE | _FILE_READ_ATTRIBUTES, 0, None,
        _CREATE_NEW,
        _FILE_ATTRIBUTE_NORMAL | _FILE_FLAG_OPEN_REPARSE_POINT | _FILE_FLAG_WRITE_THROUGH,
        None,
    )
    if handle == _INVALID_HANDLE_VALUE:
        code = ctypes.get_last_error()
        _win_close_all(handles)
        if code in {_ERROR_ALREADY_EXISTS, _ERROR_FILE_EXISTS}:
            raise SanctionError(f"refusing to overwrite existing evidence artifact: {path}")
        raise _win_error("cannot create evidence artifact", path, code)
    handles.append(handle)
    try:
        _win_check_handle(handle, path, "evidence artifact", "file")
        offset = 0
        while offset < len(data):
            chunk = data[offset:offset + 1024 * 1024]
            buffer = ctypes.create_string_buffer(chunk)
            written = wintypes.DWORD()
            if not _KERNEL32.WriteFile(handle, buffer, len(chunk), ctypes.byref(written), None):
                raise _win_error("cannot write evidence artifact", path)
            if written.value != len(chunk):
                raise SanctionError(f"short write while creating evidence artifact {path}")
            offset += written.value
        if not _KERNEL32.FlushFileBuffers(handle):
            raise _win_error("cannot flush evidence artifact", path)
    finally:
        _win_close_all(handles)


def _posix_close_all(fds: list[int]) -> None:
    for fd in reversed(fds):
        try:
            os.close(fd)
        except OSError:
            pass


def _posix_dir_flags() -> int:
    required = ("O_DIRECTORY", "O_NOFOLLOW")
    if (
        any(not hasattr(os, name) for name in required)
        or os.open not in os.supports_dir_fd
        or os.mkdir not in os.supports_dir_fd
    ):
        raise SanctionError("platform cannot establish no-follow directory-handle containment")
    return os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)


def _posix_open_directory_chain(path: Path, label: str, *, create: bool) -> list[int]:
    path = _lexical_absolute(path, label)
    flags = _posix_dir_flags()
    try:
        fds = [os.open("/", flags)]
    except OSError as exc:
        raise SanctionError(f"cannot pin filesystem root for {label}: {exc}") from exc
    try:
        for component in path.parts[1:]:
            try:
                fd = os.open(component, flags, dir_fd=fds[-1])
            except FileNotFoundError:
                if not create:
                    raise _PhysicalMissing(str(path))
                try:
                    os.mkdir(component, 0o777, dir_fd=fds[-1])
                except FileExistsError:
                    pass
                except OSError as exc:
                    raise SanctionError(f"cannot create physical directory for {label} {path}: {exc}") from exc
                try:
                    fd = os.open(component, flags, dir_fd=fds[-1])
                except OSError as exc:
                    if exc.errno in {errno.ELOOP, errno.ENOTDIR}:
                        raise SanctionError(f"{label} crosses a reparse/symlink path component: {path}") from exc
                    raise SanctionError(f"cannot open physical directory for {label} {path}: {exc}") from exc
            except OSError as exc:
                if exc.errno in {errno.ELOOP, errno.ENOTDIR}:
                    raise SanctionError(f"{label} crosses a reparse/symlink path component: {path}") from exc
                raise SanctionError(f"cannot open physical directory for {label} {path}: {exc}") from exc
            if not stat.S_ISDIR(os.fstat(fd).st_mode):
                os.close(fd)
                raise SanctionError(f"{label} is not a physical directory: {path}")
            fds.append(fd)
        return fds
    except BaseException:
        _posix_close_all(fds)
        raise


def _posix_open_leaf(parent_fd: int, name: str, label: str, *, read: bool) -> int:
    del read  # O_NONBLOCK is harmless for regular files and prevents FIFO/device hangs before fstat.
    flags = os.O_RDONLY | getattr(os, "O_NONBLOCK", 0)
    flags |= os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
    try:
        return os.open(name, flags, dir_fd=parent_fd)
    except FileNotFoundError as exc:
        raise _PhysicalMissing(name) from exc
    except OSError as exc:
        if exc.errno in {errno.ELOOP, errno.ENOTDIR}:
            raise SanctionError(f"{label} crosses a reparse/symlink path component: {name}") from exc
        raise SanctionError(f"cannot open {label} {name}: {exc}") from exc


def _posix_validate(path: Path, label: str, expected: str | None, *, allow_missing: bool) -> bool:
    path = _lexical_absolute(path, label)
    if path == Path("/"):
        fds = _posix_open_directory_chain(path, label, create=False)
        _posix_close_all(fds)
        return True
    try:
        fds = _posix_open_directory_chain(path.parent, label, create=False)
    except _PhysicalMissing:
        if allow_missing:
            return False
        raise SanctionError(f"{label} does not exist: {path}")
    try:
        try:
            fd = _posix_open_leaf(fds[-1], path.name, label, read=False)
        except _PhysicalMissing:
            if allow_missing:
                return False
            raise SanctionError(f"{label} does not exist: {path}")
        fds.append(fd)
        mode = os.fstat(fd).st_mode
        if expected == "dir" and not stat.S_ISDIR(mode):
            raise SanctionError(f"{label} is not a physical directory: {path}")
        if expected == "file" and not stat.S_ISREG(mode):
            raise SanctionError(f"{label} is not a regular physical file: {path}")
        if expected is None and not (stat.S_ISDIR(mode) or stat.S_ISREG(mode)):
            raise SanctionError(f"{label} is not a regular file or directory: {path}")
        return True
    finally:
        _posix_close_all(fds)


def _posix_read_snapshot(
    path: Path,
    label: str,
    *,
    missing_ok: bool,
) -> tuple[bytes, str, dict[str, int]] | None:
    path = _lexical_absolute(path, label)
    try:
        fds = _posix_open_directory_chain(path.parent, label, create=False)
        try:
            try:
                name_before = os.stat(path.name, dir_fd=fds[-1], follow_symlinks=False)
            except FileNotFoundError as exc:
                raise _PhysicalMissing(path.name) from exc
            if not stat.S_ISREG(name_before.st_mode):
                raise SanctionError(f"{label} is not a regular physical file: {path}")
            fd = _posix_open_leaf(fds[-1], path.name, label, read=True)
        except BaseException:
            _posix_close_all(fds)
            raise
        fds.append(fd)
    except _PhysicalMissing:
        if missing_ok:
            return None
        raise SanctionError(f"{label} is not an accessible regular file: {path}")
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode):
            raise SanctionError(f"{label} is not a regular physical file: {path}")

        def read_once() -> bytes:
            chunks: list[bytes] = []
            while True:
                chunk = os.read(fd, 1024 * 1024)
                if not chunk:
                    return b"".join(chunks)
                chunks.append(chunk)

        try:
            first = read_once()
            middle = os.fstat(fd)
            os.lseek(fd, 0, os.SEEK_SET)
            second = read_once()
        except OSError as exc:
            raise SanctionError(f"cannot read {label} {path}: {exc}") from exc
        after = os.fstat(fd)
        try:
            name_after = os.stat(path.name, dir_fd=fds[-2], follow_symlinks=False)
        except OSError as exc:
            raise SanctionError(f"{label} path changed while its exact bytes were being read: {path}") from exc
        stable_fields = ("st_dev", "st_ino", "st_mode", "st_size", "st_mtime_ns", "st_ctime_ns")
        if (
            first != second
            or any(getattr(before, field) != getattr(middle, field) for field in stable_fields)
            or any(getattr(middle, field) != getattr(after, field) for field in stable_fields)
            or (name_before.st_dev, name_before.st_ino, name_before.st_mode)
            != (before.st_dev, before.st_ino, before.st_mode)
            or (name_after.st_dev, name_after.st_ino, name_after.st_mode)
            != (after.st_dev, after.st_ino, after.st_mode)
        ):
            raise SanctionError(f"{label} changed while its exact bytes were being read: {path}")
        mode = "100755" if before.st_mode & stat.S_IXUSR else "100644"
        return second, mode, {"device": int(before.st_dev), "inode": int(before.st_ino)}
    finally:
        _posix_close_all(fds)


def _posix_write_new(path: Path, data: bytes) -> None:
    path = _lexical_absolute(path, "evidence artifact")
    fds = _posix_open_directory_chain(path.parent, "evidence artifact parent", create=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
    try:
        try:
            fd = os.open(path.name, flags, 0o666, dir_fd=fds[-1])
        except FileExistsError as exc:
            raise SanctionError(f"refusing to overwrite existing evidence artifact: {path}") from exc
        except OSError as exc:
            if exc.errno in {errno.ELOOP, errno.ENOTDIR}:
                raise SanctionError(f"evidence artifact crosses a reparse/symlink path component: {path}") from exc
            raise SanctionError(f"cannot create evidence artifact {path}: {exc}") from exc
        fds.append(fd)
        offset = 0
        try:
            while offset < len(data):
                written = os.write(fd, data[offset:offset + 1024 * 1024])
                if written <= 0:
                    raise SanctionError(f"short write while creating evidence artifact {path}")
                offset += written
            os.fsync(fd)
        except OSError as exc:
            raise SanctionError(f"cannot write or flush evidence artifact {path}: {exc}") from exc
    finally:
        _posix_close_all(fds)


def _physical_validate(path: Path, label: str, expected: str | None, *, allow_missing: bool = False) -> bool:
    if os.name == "nt":
        return _win_validate(path, label, expected, allow_missing=allow_missing)
    return _posix_validate(path, label, expected, allow_missing=allow_missing)


def _read_snapshot_physical(
    path: Path,
    label: str,
    *,
    missing_ok: bool = False,
) -> tuple[bytes, str, dict[str, int]] | None:
    if os.name == "nt":
        return _win_read_snapshot(path, label, missing_ok=missing_ok)
    return _posix_read_snapshot(path, label, missing_ok=missing_ok)


def _read_snapshot(path: Path, label: str, *, missing_ok: bool = False) -> tuple[bytes, str] | None:
    snapshot = _read_snapshot_physical(path, label, missing_ok=missing_ok)
    if snapshot is None:
        return None
    return snapshot[0], snapshot[1]


def _read(path: Path, label: str) -> bytes:
    snapshot = _read_snapshot(path, label)
    assert snapshot is not None
    return snapshot[0]


def _write_bytes(path: Path, data: bytes) -> None:
    if os.name == "nt":
        _win_write_new(path, data)
    else:
        _posix_write_new(path, data)


def _ensure_physical_directory(path: Path, label: str, *, create: bool) -> Path:
    path = _lexical_absolute(path, label)
    try:
        handles = (
            _win_open_directory_chain(path, label, create=create)
            if os.name == "nt"
            else _posix_open_directory_chain(path, label, create=create)
        )
    except _PhysicalMissing as exc:
        raise SanctionError(f"{label} does not exist: {path}") from exc
    if os.name == "nt":
        _win_close_all(handles)
    else:
        _posix_close_all(handles)
    return path


def _create_physical_directory_exclusive(path: Path, label: str) -> Path:
    path = _lexical_absolute(path, label)
    if path == Path(path.anchor):
        raise SanctionError(f"{label} cannot be a filesystem root: {path}")
    handles = (
        _win_open_directory_chain(path.parent, f"{label} parent", create=True)
        if os.name == "nt"
        else _posix_open_directory_chain(path.parent, f"{label} parent", create=True)
    )
    try:
        if os.name == "nt":
            if not _KERNEL32.CreateDirectoryW(_win_long(path), None):
                code = ctypes.get_last_error()
                if code in {_ERROR_ALREADY_EXISTS, _ERROR_FILE_EXISTS}:
                    raise SanctionError(f"{label} must be absent; refusing existing directory: {path}")
                raise _win_error(f"cannot create {label}", path, code)
            handles.append(_win_open_existing(path, label, "dir"))
        else:
            try:
                os.mkdir(path.name, 0o777, dir_fd=handles[-1])
            except FileExistsError as exc:
                raise SanctionError(f"{label} must be absent; refusing existing directory: {path}") from exc
            except OSError as exc:
                raise SanctionError(f"cannot create {label} {path}: {exc}") from exc
            try:
                fd = os.open(path.name, _posix_dir_flags(), dir_fd=handles[-1])
            except OSError as exc:
                raise SanctionError(f"cannot pin newly created {label} {path}: {exc}") from exc
            handles.append(fd)
        return path
    finally:
        if os.name == "nt":
            _win_close_all(handles)
        else:
            _posix_close_all(handles)


def _physical_directory_identity(path: Path, label: str) -> dict[str, int]:
    path = _lexical_absolute(path, label)
    handles = (
        _win_open_directory_chain(path, label, create=False)
        if os.name == "nt"
        else _posix_open_directory_chain(path, label, create=False)
    )
    try:
        if os.name == "nt":
            info = _BY_HANDLE_FILE_INFORMATION()
            if not _KERNEL32.GetFileInformationByHandle(handles[-1], ctypes.byref(info)):
                raise _win_error(f"cannot identify {label}", path)
            inode = (int(info.nFileIndexHigh) << 32) | int(info.nFileIndexLow)
            return {"device": int(info.dwVolumeSerialNumber), "inode": inode}
        st = os.fstat(handles[-1])
        return {"device": int(st.st_dev), "inode": int(st.st_ino)}
    finally:
        if os.name == "nt":
            _win_close_all(handles)
        else:
            _posix_close_all(handles)


def _physical_file_identity(path: Path, label: str) -> dict[str, int]:
    """Read a regular file's native identity without reading its content."""
    path = _lexical_absolute(path, label)
    if os.name == "nt":
        handles = _win_open_directory_chain(path.parent, label, create=False)
        try:
            handles.append(_win_open_existing(path, label, "file", read=False))
            stamp = _win_file_stamp(handles[-1], path, label)
            return {"device": stamp[0], "inode": stamp[1]}
        finally:
            _win_close_all(handles)
    fds = _posix_open_directory_chain(path.parent, label, create=False)
    try:
        fds.append(_posix_open_leaf(fds[-1], path.name, label, read=False))
        st = os.fstat(fds[-1])
        if not stat.S_ISREG(st.st_mode):
            raise SanctionError(f"{label} is not a regular physical file: {path}")
        return {"device": int(st.st_dev), "inode": int(st.st_ino)}
    finally:
        _posix_close_all(fds)


def _write_text(path: Path, text: str) -> None:
    _write_bytes(path, text.encode("utf-8"))


def _json_load(path: Path, label: str) -> Any:
    try:
        return json.loads(_read(path, label).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SanctionError(f"invalid UTF-8 JSON in {label} {path}: {exc}") from exc


def _json_write(path: Path, value: Any) -> None:
    _write_text(path, json.dumps(value, indent=2, ensure_ascii=False) + "\n")


def _expect_object(value: Any, where: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise SanctionError(f"{where} must be an object")
    return value


def _expect_list(value: Any, where: str) -> list[Any]:
    if not isinstance(value, list):
        raise SanctionError(f"{where} must be a list")
    return value


def _keys(obj: dict[str, Any], required: set[str], allowed: set[str], where: str) -> None:
    missing = sorted(required - obj.keys())
    unknown = sorted(obj.keys() - allowed)
    if missing:
        raise SanctionError(f"{where} missing required fields: {', '.join(missing)}")
    if unknown:
        raise SanctionError(f"{where} has unknown fields: {', '.join(unknown)}")


def _nonempty(value: Any, where: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SanctionError(f"{where} must be a non-empty string")
    return value.strip()


def _single_line(value: Any, where: str) -> str:
    text = _nonempty(value, where)
    forbidden_categories = {"Cc", "Cf", "Zl", "Zp"}
    if any(unicodedata.category(character) in forbidden_categories for character in text):
        raise SanctionError(
            f"{where} must be a single-line string without control, format, or line-separator characters"
        )
    return text


def _choice(value: Any, choices: set[str], where: str) -> str:
    text = _nonempty(value, where)
    if text not in choices:
        raise SanctionError(f"{where} must be one of {sorted(choices)}, got {text!r}")
    return text


def _absolute(value: Any, where: str, *, must_exist: bool = True) -> Path:
    path = _lexical_absolute(Path(_nonempty(value, where)), where)
    if must_exist:
        _physical_validate(path, where, None, allow_missing=False)
    return path


def _relative(value: Any, where: str) -> str:
    text = _nonempty(value, where).replace("\\", "/")
    pure = PurePosixPath(text)
    if pure.is_absolute() or any(part in ("", ".", "..") for part in pure.parts):
        raise SanctionError(f"{where} must be a lexical root-relative path without traversal: {text}")
    return pure.as_posix()


def _within(path: Path, root: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(root.resolve(strict=True))
        return True
    except (ValueError, OSError):
        return False


def _root_relative_physical_path(root: Path, relative: str, label: str) -> Path:
    """Validate a root-relative path without resolving away a declared root alias."""
    root = _lexical_absolute(root, f"{label} declared root")
    _physical_validate(root, f"{label} declared root", "dir", allow_missing=False)
    candidate = root.joinpath(*PurePosixPath(relative).parts)
    _physical_validate(candidate, label, None, allow_missing=True)
    return candidate


def _absolute_create_path(value: Path, label: str) -> Path:
    path = _lexical_absolute(value, label)
    _physical_validate(path, label, None, allow_missing=True)
    return path


def _is_reparse_or_symlink(path: Path) -> bool:
    try:
        if path.is_symlink():
            return True
        attrs = getattr(path.lstat(), "st_file_attributes", 0)
        flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
        return bool(attrs & flag)
    except OSError as exc:
        raise SanctionError(f"cannot inspect reparse/symlink status for {path}: {exc}") from exc


def _safe_component(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in value)
    return cleaned or "item"


def _identity(data: bytes) -> dict[str, Any]:
    return {"algorithm": "sha256", "value": _sha(data), "bytes": len(data)}


def _hmac_identity(data: bytes, key: bytes, nonce: str, target_id: str, role: str) -> dict[str, Any]:
    # The tag must compare the same bytes across base/target/current roles, so the
    # domain binds packet + target but deliberately not the observation role.
    domain = f"sanction-packet/v1\0{nonce}\0{target_id}\0content\0".encode("utf-8")
    tag = hmac.new(key, domain + data, hashlib.sha256).hexdigest()
    # Length is deliberately withheld for low-entropy sensitive material.
    return {"algorithm": "hmac-sha256", "value": tag, "bytes": "withheld"}


def _scoped_identity(
    data: bytes,
    *,
    sensitive: bool,
    key: bytes | None,
    nonce: str,
    scope: str,
) -> dict[str, Any]:
    if not sensitive:
        return _identity(data)
    if key is None:
        raise SanctionError(f"sensitive identity {scope} requires --hmac-key-file")
    domain = f"sanction-packet/v1\0{nonce}\0{scope}\0".encode("utf-8")
    tag = hmac.new(key, domain + data, hashlib.sha256).hexdigest()
    # Keep the target-content emitter's exact mutation literal unique.
    return {"algorithm": "hmac-sha256", "bytes": "withheld", "value": tag}


def _decision_warning(classification: str) -> str:
    if classification == "sensitive":
        return (
            "Agent-recorded attestation only. HMAC-SHA-256 authenticates possession of the "
            "separately held key, not the human owner, and does not defeat an attacker who can "
            "rewrite every local artifact consistently."
        )
    return (
        "Agent-recorded attestation only. SHA-256 supplies local consistency and does not "
        "authenticate the human owner or defeat an attacker who can rewrite every local "
        "artifact consistently."
    )


def _decision_binding(
    data: bytes,
    *,
    lock: dict[str, Any],
    classification: str,
    key: bytes | None,
    purpose: str,
) -> dict[str, Any]:
    if purpose not in {"evidence", "record", "lifecycle", "invalidation"}:
        raise SanctionError(f"unsupported decision-binding purpose: {purpose}")
    domain = (
        f"{DECISION_SCHEMA}\0{lock['packet_id']}\0{lock['helper']['sha256']}\0"
        f"{lock['nonce']}\0{purpose}\0"
    ).encode("utf-8")
    if classification == "sensitive":
        if key is None:
            raise SanctionError("sensitive decision evidence requires --hmac-key-file")
        tag = hmac.new(key, domain + data, hashlib.sha256).hexdigest()
        # Deliberately use a different literal order from the target-content
        # emitter so the mutation harness can address that emitter precisely.
        return {"algorithm": "hmac-sha256", "bytes": "withheld", "value": tag}
    if classification != "non-sensitive":
        raise SanctionError(f"unsupported decision evidence classification: {classification}")
    return {
        "algorithm": "sha256",
        "value": hashlib.sha256(domain + data).hexdigest(),
        "bytes": len(data),
    }


def _validate_decision_binding(
    stored_value: Any,
    expected: dict[str, Any],
    label: str,
) -> dict[str, Any]:
    stored = _expect_object(stored_value, label)
    fields = {"algorithm", "value", "bytes"}
    _keys(stored, fields, fields, label)
    algorithm = _nonempty(stored["algorithm"], f"{label}.algorithm")
    value = _nonempty(stored["value"], f"{label}.value")
    expected_value = str(expected["value"])
    value_matches = hmac.compare_digest(value, expected_value)
    if (
        algorithm != expected["algorithm"]
        or stored["bytes"] != expected["bytes"]
        or not value_matches
    ):
        raise SanctionError(f"{label} mismatch")
    return stored


def _packet_key_confirmation(
    key: bytes,
    *,
    nonce: str,
    helper_sha256: str,
    manifest_sha256: str,
) -> dict[str, Any]:
    domain = (
        f"{SCHEMA}\0{nonce}\0{helper_sha256}\0{manifest_sha256}\0key-confirmation\0"
    ).encode("utf-8")
    tag = hmac.new(key, domain, hashlib.sha256).hexdigest()
    return {"algorithm": "hmac-sha256", "bytes": "withheld", "value": tag}


def _validate_packet_key(
    lock: dict[str, Any],
    spec: dict[str, Any],
    key: bytes | None,
) -> None:
    confirmation = lock.get("key_confirmation")
    if not spec["_sensitive"]:
        if confirmation is not None:
            raise SanctionError("non-sensitive packet unexpectedly contains a key confirmation")
        return
    if key is None:
        raise SanctionError("sensitive targets or decision evidence require --hmac-key-file")
    expected = _packet_key_confirmation(
        key,
        nonce=lock["nonce"],
        helper_sha256=lock["helper"]["sha256"],
        manifest_sha256=lock["manifest"]["sha256"],
    )
    _validate_decision_binding(confirmation, expected, "packet key confirmation")


def _key(path_value: str | None, required: bool) -> bytes | None:
    if not path_value:
        if required:
            raise SanctionError("sensitive targets or decision evidence require --hmac-key-file")
        return None
    path = _absolute(path_value, "--hmac-key-file")
    data = _read(path, "HMAC key")
    if len(data) < 32:
        raise SanctionError("HMAC key must contain at least 32 random bytes")
    return data


def _helper_path() -> Path:
    return Path(__file__).resolve()


def _helper_sha() -> str:
    return _sha(_read(_helper_path(), "helper"))


def _git_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(
        GIT_CONFIG_NOSYSTEM="1",
        GIT_CONFIG_GLOBAL=os.devnull,
        GIT_TERMINAL_PROMPT="0",
    )
    if extra:
        env.update(extra)
    return env


def _git(
    root: Path,
    *args: str,
    input_bytes: bytes | None = None,
    extra_env: dict[str, str] | None = None,
    pass_fds: tuple[int, ...] = (),
    check: bool = True,
) -> subprocess.CompletedProcess[bytes]:
    kwargs: dict[str, Any] = {}
    if pass_fds:
        if os.name == "nt":
            raise SanctionError("descriptor-relative Git workspace paths are unsupported on Windows")
        kwargs["pass_fds"] = pass_fds
    cp = subprocess.run(
        ["git", "-c", "commit.gpgsign=false", "-c", f"core.hooksPath={os.devnull}", *args],
        cwd=root,
        env=_git_env(extra_env),
        input=input_bytes,
        capture_output=True,
        **kwargs,
    )
    if check and cp.returncode:
        err = cp.stderr.decode("utf-8", "replace").strip()
        raise SanctionError(f"git {' '.join(args)} failed in {root}: {err}")
    return cp


def _zpaths(raw: bytes) -> set[str]:
    return {part.decode("utf-8", "surrogateescape") for part in raw.split(b"\0") if part}


def _git_status(root: Path) -> dict[str, list[str]]:
    return {
        "staged": sorted(_zpaths(_git(root, "diff", "--cached", "--name-only", "-z").stdout)),
        "unstaged": sorted(_zpaths(_git(root, "diff", "--name-only", "-z").stdout)),
        "untracked": sorted(_zpaths(_git(root, "ls-files", "--others", "--exclude-standard", "-z").stdout)),
    }


def _parse_index_entries(raw: bytes, where: str) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    for record in raw.split(b"\0"):
        if not record:
            continue
        meta, sep, path = record.partition(b"\t")
        if not sep:
            raise SanctionError(f"cannot parse index entry in {where}")
        bits = meta.decode("ascii", "strict").split()
        if len(bits) != 3:
            raise SanctionError(f"cannot parse index metadata in {where}: {meta!r}")
        mode, oid, stage = bits
        entries.append(
            {
                "path": path.decode("utf-8", "surrogateescape"),
                "mode": mode,
                "oid": oid,
                "stage": stage,
            }
        )
    return entries


def _parse_index_flags(raw: bytes, where: str) -> list[dict[str, str]]:
    flags: list[dict[str, str]] = []
    for record in raw.split(b"\0"):
        if not record:
            continue
        tag, sep, path = record.partition(b" ")
        if not sep or len(tag) != 1:
            raise SanctionError(f"cannot parse index flag in {where}: {record!r}")
        flags.append(
            {
                "path": path.decode("utf-8", "surrogateescape"),
                "tag": tag.decode("ascii", "strict"),
            }
        )
    return flags


def _index_snapshot(root: Path) -> dict[str, Any]:
    entries_raw = _git(root, "ls-files", "--stage", "-z").stdout
    flags_raw = _git(root, "ls-files", "-v", "-z").stdout
    return {
        "sha256": _sha(entries_raw),
        "entries": _parse_index_entries(entries_raw, str(root)),
        "flags_sha256": _sha(flags_raw),
        "flags": _parse_index_flags(flags_raw, str(root)),
    }


def _parse_tree_entries(raw: bytes, where: str) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    for record in raw.split(b"\0"):
        if not record:
            continue
        meta, sep, path = record.partition(b"\t")
        if not sep:
            raise SanctionError(f"cannot parse tree entry in {where}")
        bits = meta.decode("ascii", "strict").split()
        if len(bits) != 3:
            raise SanctionError(f"cannot parse tree metadata in {where}: {meta!r}")
        mode, _kind, oid = bits
        entries.append(
            {
                "path": path.decode("utf-8", "surrogateescape"),
                "mode": mode,
                "oid": oid,
                "stage": "0",
            }
        )
    return entries


def _tree_entries(root: Path, revision: str) -> list[dict[str, str]]:
    raw = _git(root, "ls-tree", "-r", "-z", "--full-tree", revision).stdout
    return _parse_tree_entries(raw, f"{root}:{revision}")


def _validate_git_index_baseline(
    spec: dict[str, Any], roots_obs: dict[str, Any]
) -> None:
    for root_id, root in spec["_roots"].items():
        if root["kind"] != "git":
            continue
        index = roots_obs[root_id]["index"]
        hidden = [row for row in index["flags"] if row["tag"] != "H"]
        if hidden:
            raise SanctionError(
                f"Git root {root_id} has hidden or special index flags "
                f"(assume-unchanged/skip-worktree and similar states are unsupported): {hidden}"
            )

        live_only_paths: set[str] = set()
        for target in spec["_targets"].values():
            if target["root"] != root_id or target["commit"]:
                continue
            live_only_paths.add(target["path"])
            if target["_operation"] == "rename":
                live_only_paths.add(target["old_path"])
        if not live_only_paths:
            continue

        current_entries = sorted(
            (row for row in index["entries"] if row["path"] in live_only_paths),
            key=lambda row: (row["path"], row["stage"], row["mode"], row["oid"]),
        )
        base_entries = sorted(
            (
                row
                for row in _tree_entries(root["_path"], roots_obs[root_id]["head"])
                if row["path"] in live_only_paths
            ),
            key=lambda row: (row["path"], row["stage"], row["mode"], row["oid"]),
        )
        if current_entries != base_entries:
            raise SanctionError(
                f"commit:false Git target index must equal its declared base tree in {root_id}: "
                f"{sorted(live_only_paths)}"
            )


def _git_blob_at(root: Path, revision: str, path: str) -> tuple[bytes | None, str]:
    probe = _git(root, "cat-file", "-e", f"{revision}:{path}", check=False)
    if probe.returncode:
        return None, "absent"
    data = _git(root, "show", f"{revision}:{path}").stdout
    raw = _git(root, "ls-tree", "-z", revision, "--", path).stdout
    if not raw:
        raise SanctionError(f"cannot derive mode for {revision}:{path}")
    first = raw.split(b"\0", 1)[0]
    meta = first.split(b"\t", 1)[0].decode("ascii", "strict").split()
    if len(meta) < 1:
        raise SanctionError(f"cannot parse mode for {revision}:{path}")
    mode = meta[0]
    if mode == "160000":
        raise SanctionError(f"submodule target is unsupported in v1: {path}")
    return data, mode


def _decode_text(data: bytes, encoding: str, where: str) -> str:
    try:
        return data.decode(encoding, "strict")
    except (LookupError, UnicodeDecodeError) as exc:
        raise SanctionError(f"{where} is not strict {encoding} text: {exc}") from exc


def _inventory(root: Path) -> dict[str, dict[str, Any]]:
    _physical_validate(root, "generated-run root", "dir", allow_missing=False)
    result: dict[str, dict[str, Any]] = {}
    for path in sorted(root.rglob("*")):
        if _is_reparse_or_symlink(path):
            raise SanctionError(f"generated inventory rejects reparse/symlink: {path}")
        if path.is_dir():
            continue
        rel = path.relative_to(root).as_posix()
        result[rel] = _identity(_read(path, "generated output"))
    return result


def _artifact(path: Path) -> dict[str, Any]:
    data = _read(path, "packet artifact")
    return {
        "path": str(path.resolve()),
        "sha256": _sha(data),
        "bytes": len(data),
        "lines": data.count(b"\n") + (1 if data and not data.endswith(b"\n") else 0),
        "hunks": sum(1 for line in data.splitlines() if line.startswith(b"@@ ")),
    }


def _validate_content(
    value: Any,
    where: str,
) -> tuple[dict[str, Any], str, str, str]:
    """Validate independent representation, provenance, and confidentiality."""
    content = _expect_object(value, where)
    dimensions = {"representation", "provenance", "confidentiality"}
    _keys(content, dimensions, dimensions, where)

    representation = _expect_object(content["representation"], f"{where}.representation")
    representation_kind = _choice(
        representation.get("kind"), {"text", "binary"}, f"{where}.representation.kind"
    )
    representation["kind"] = representation_kind
    if representation_kind == "text":
        _keys(
            representation,
            {"kind", "encoding"},
            {"kind", "encoding"},
            f"{where}.representation",
        )
        _nonempty(representation["encoding"], f"{where}.representation.encoding")
    else:
        _keys(
            representation,
            {"kind", "owner_access", "inspector"},
            {"kind", "owner_access", "inspector"},
            f"{where}.representation",
        )
        _nonempty(
            representation["owner_access"], f"{where}.representation.owner_access"
        )
        inspector = _expect_object(
            representation["inspector"], f"{where}.representation.inspector"
        )
        inspector_fields = {"tool", "scope", "limitations", "result_locator"}
        _keys(
            inspector,
            inspector_fields,
            inspector_fields,
            f"{where}.representation.inspector",
        )
        for name in sorted(inspector_fields):
            _nonempty(inspector[name], f"{where}.representation.inspector.{name}")

    provenance = _expect_object(content["provenance"], f"{where}.provenance")
    provenance_kind = _choice(
        provenance.get("kind"), {"authored", "generated"}, f"{where}.provenance.kind"
    )
    provenance["kind"] = provenance_kind
    if provenance_kind == "authored":
        _keys(provenance, {"kind"}, {"kind"}, f"{where}.provenance")
    else:
        _keys(
            provenance,
            {"kind", "group", "relative_output"},
            {"kind", "group", "relative_output"},
            f"{where}.provenance",
        )
        _nonempty(provenance["group"], f"{where}.provenance.group")
        provenance["relative_output"] = _relative(
            provenance["relative_output"], f"{where}.provenance.relative_output"
        )

    confidentiality = _expect_object(
        content["confidentiality"], f"{where}.confidentiality"
    )
    confidentiality_kind = _choice(
        confidentiality.get("kind"),
        {"non-sensitive", "sensitive"},
        f"{where}.confidentiality.kind",
    )
    confidentiality["kind"] = confidentiality_kind
    if confidentiality_kind == "non-sensitive":
        _keys(
            confidentiality,
            {"kind"},
            {"kind"},
            f"{where}.confidentiality",
        )
    else:
        confidentiality_fields = {"kind", "binding", "key_ref", "owner_access"}
        _keys(
            confidentiality,
            confidentiality_fields,
            confidentiality_fields,
            f"{where}.confidentiality",
        )
        if confidentiality["binding"] != "hmac-sha256":
            raise SanctionError(f"{where}.confidentiality requires hmac-sha256 binding")
        _nonempty(confidentiality["key_ref"], f"{where}.confidentiality.key_ref")
        _nonempty(
            confidentiality["owner_access"], f"{where}.confidentiality.owner_access"
        )

    return content, representation_kind, provenance_kind, confidentiality_kind


def _validate_classified_artifact(value: Any, where: str) -> dict[str, Any]:
    artifact = _expect_object(value, f"{where} classified artifact")
    _keys(artifact, {"path", "content"}, {"path", "content"}, where)
    path = _absolute(artifact["path"], f"{where}.path")
    _physical_validate(path, f"{where}.path", "file", allow_missing=False)
    (
        _content,
        representation_kind,
        provenance_kind,
        confidentiality_kind,
    ) = _validate_content(artifact["content"], f"{where}.content")
    artifact["_path"] = path
    artifact["_representation_kind"] = representation_kind
    artifact["_provenance_kind"] = provenance_kind
    artifact["_confidentiality_kind"] = confidentiality_kind
    return artifact


def _derive_exact_mirror_groups(
    targets: dict[str, dict[str, Any]],
) -> dict[str, list[str]]:
    groups: dict[str, list[str]] = {}
    for target_id, target in targets.items():
        relationship = target["relationship"]
        if relationship["kind"] == "exact-mirror":
            groups.setdefault(relationship["group"], []).append(target_id)

    for group_id, members in groups.items():
        if len(members) < 2:
            raise SanctionError(
                f"exact-mirror group {group_id} is a mirror singleton; at least two exact members are required"
            )
        first = targets[members[0]]
        manifest_axes = {
            "path": first["path"],
            "old-path": first.get("old_path"),
            "operation": first["_operation"],
            "representation": first["_representation_kind"],
            "provenance": first["_provenance_kind"],
            "confidentiality": first["_confidentiality_kind"],
        }
        for member_id in members[1:]:
            member = targets[member_id]
            member_axes = {
                "path": member["path"],
                "old-path": member.get("old_path"),
                "operation": member["_operation"],
                "representation": member["_representation_kind"],
                "provenance": member["_provenance_kind"],
                "confidentiality": member["_confidentiality_kind"],
            }
            for axis, expected in manifest_axes.items():
                if member_axes[axis] != expected:
                    raise SanctionError(
                        f"exact-mirror group {group_id} mirror {axis} mismatch: "
                        f"{members[0]}={expected!r}, {member_id}={member_axes[axis]!r}"
                    )
    return {group_id: sorted(members) for group_id, members in sorted(groups.items())}


def _validate_selector(value: Any, where: str) -> dict[str, str]:
    selector = _expect_object(value, where)
    fields = {"identity", "role"}
    _keys(selector, fields, fields, where)
    return {
        "identity": _single_line(selector["identity"], f"{where}.identity"),
        "role": _single_line(selector["role"], f"{where}.role"),
    }


def _validate_attestation_verification(value: Any, where: str) -> dict[str, str]:
    verification = _expect_object(value, where)
    fields = {"method", "evidence_locator"}
    _keys(verification, fields, fields, where)
    return {
        "method": _single_line(verification["method"], f"{where}.method"),
        "evidence_locator": _single_line(
            verification["evidence_locator"], f"{where}.evidence_locator"
        ),
    }


def _validate_base_attestation(
    value: Any,
    where: str,
    expected_locator: dict[str, str],
) -> dict[str, Any]:
    attestation = _expect_object(value, where)
    fields = {"selected_by", "authority", "locator", "verification"}
    _keys(attestation, fields, fields, where)
    locator = _expect_object(attestation["locator"], f"{where}.locator")
    if locator != expected_locator:
        raise SanctionError(
            f"{where}.locator must exactly equal the declared authoritative base locator: "
            f"{_canonical(expected_locator).decode('utf-8')}"
        )
    return {
        "selected_by": _validate_selector(
            attestation["selected_by"], f"{where}.selected_by"
        ),
        "authority": _single_line(attestation["authority"], f"{where}.authority"),
        "locator": dict(expected_locator),
        "verification": _validate_attestation_verification(
            attestation["verification"], f"{where}.verification"
        ),
    }


def _validate_residue_rows(
    value: Any,
    roots: dict[str, dict[str, Any]],
    where: str,
) -> list[dict[str, Any]]:
    residue: list[dict[str, Any]] = []
    for i, raw_row in enumerate(_expect_list(value, where)):
        row_where = f"{where}[{i}]"
        row = _expect_object(raw_row, row_where)
        fields = {"root", "path", "states", "disposition", "reason"}
        _keys(row, fields, fields, row_where)
        root_id = _single_line(row["root"], f"{row_where}.root")
        if root_id not in roots or roots[root_id]["kind"] != "git":
            raise SanctionError(f"{row_where} must name a Git root")
        path = _relative(row["path"], f"{row_where}.path")
        states = [
            _choice(
                state,
                {"staged", "unstaged", "untracked"},
                f"{row_where}.states[]",
            )
            for state in _expect_list(row["states"], f"{row_where}.states")
        ]
        if not states or len(states) != len(set(states)):
            raise SanctionError(f"{row_where}.states must be non-empty and unique")
        residue.append(
            {
                "root": root_id,
                "path": path,
                "states": sorted(states),
                "disposition": _choice(
                    row["disposition"],
                    {"excluded", "preserve", "leave"},
                    f"{row_where}.disposition",
                ),
                "reason": _single_line(row["reason"], f"{row_where}.reason"),
            }
        )
    return residue


def _validate_denominator_attestation(
    value: Any,
    decision: dict[str, Any],
    roots: dict[str, dict[str, Any]],
    residue: list[dict[str, Any]],
) -> dict[str, Any]:
    where = "denominator_attestation"
    attestation = _expect_object(value, where)
    fields = {
        "selected_by",
        "selection_basis",
        "root_ids",
        "target_ids",
        "residue",
        "exclusions",
        "omission_check",
    }
    _keys(attestation, fields, fields, where)

    root_ids = [
        _single_line(value, f"{where}.root_ids[]")
        for value in _expect_list(attestation["root_ids"], f"{where}.root_ids")
    ]
    if root_ids != decision["root_ids"]:
        raise SanctionError(
            f"{where}.root_ids must exactly equal decision.root_ids in declared order"
        )
    target_ids = [
        _single_line(value, f"{where}.target_ids[]")
        for value in _expect_list(attestation["target_ids"], f"{where}.target_ids")
    ]
    if target_ids != decision["target_ids"]:
        raise SanctionError(
            f"{where}.target_ids must exactly equal decision.target_ids in declared order"
        )
    attested_residue = _validate_residue_rows(
        attestation["residue"], roots, f"{where}.residue"
    )
    if attested_residue != residue:
        raise SanctionError(
            f"{where}.residue must exactly equal the declared residue denominator"
        )

    exclusions: list[dict[str, str]] = []
    exclusion_locators: set[str] = set()
    for i, value in enumerate(
        _expect_list(attestation["exclusions"], f"{where}.exclusions")
    ):
        item_where = f"{where}.exclusions[{i}]"
        exclusion = _expect_object(value, item_where)
        exclusion_fields = {"locator", "reason"}
        _keys(exclusion, exclusion_fields, exclusion_fields, item_where)
        locator = _single_line(exclusion["locator"], f"{item_where}.locator")
        if locator in exclusion_locators:
            raise SanctionError(f"duplicate {where}.exclusions locator: {locator}")
        exclusion_locators.add(locator)
        exclusions.append(
            {
                "locator": locator,
                "reason": _single_line(exclusion["reason"], f"{item_where}.reason"),
            }
        )

    return {
        "selected_by": _validate_selector(
            attestation["selected_by"], f"{where}.selected_by"
        ),
        "selection_basis": _single_line(
            attestation["selection_basis"], f"{where}.selection_basis"
        ),
        "root_ids": root_ids,
        "target_ids": target_ids,
        "residue": attested_residue,
        "exclusions": exclusions,
        "omission_check": _validate_attestation_verification(
            attestation["omission_check"], f"{where}.omission_check"
        ),
    }


def _json_clone(value: Any) -> Any:
    return json.loads(_canonical(value).decode("utf-8"))


def _manifest_contract(spec: dict[str, Any]) -> dict[str, Any]:
    """Project every manifest-derived owner-visible decision field."""
    roots: dict[str, dict[str, Any]] = {}
    for root_id in spec["decision"]["root_ids"]:
        root = spec["_roots"][root_id]
        roots[root_id] = {
            "id": root_id,
            "kind": root["kind"],
            "path": str(root["_path"]),
            "base_revision": root.get("base_revision"),
            "base_attestation": _json_clone(root["base_attestation"]),
        }

    targets: dict[str, dict[str, Any]] = {}
    for target_id in spec["decision"]["target_ids"]:
        target = spec["_targets"][target_id]
        targets[target_id] = {
            "id": target_id,
            "root": target["root"],
            "path": target["path"],
            "old_path": target.get("old_path"),
            "entry": target["_entry"],
            "operation": target["_operation"],
            "representation_kind": target["_representation_kind"],
            "provenance_kind": target["_provenance_kind"],
            "confidentiality_kind": target["_confidentiality_kind"],
            "commit": target["commit"],
            "relationship": _json_clone(target["relationship"]),
            "base_attestation": _json_clone(target["base_attestation"]),
            "base_source": (
                str(target["_base_source"])
                if "_base_source" in target
                else None
            ),
            "target_source": (
                str(target["_target_source"])
                if "_target_source" in target
                else None
            ),
            "declared_target_mode": target.get("target_mode"),
            "content": _json_clone(target["content"]),
        }

    return {
        "decision": _json_clone(spec["decision"]),
        "denominator_attestation": _json_clone(
            spec["_denominator_attestation"]
        ),
        "residue": _json_clone(spec["_residue"]),
        "roots": roots,
        "targets": targets,
    }


def _validate_manifest(raw: Any) -> dict[str, Any]:
    spec = _expect_object(raw, "manifest")
    manifest_fields = {
        "schema", "decision", "denominator_attestation", "roots", "targets",
        "residue", "generated_groups",
    }
    _keys(spec, manifest_fields, manifest_fields, "manifest")
    if spec["schema"] != SCHEMA:
        raise SanctionError(f"manifest.schema must be {SCHEMA!r}")

    decision = _expect_object(spec["decision"], "decision")
    decision_fields = {
        "gate", "evidence_classification", "actions", "scope", "root_ids", "target_ids"
    }
    _keys(decision, decision_fields, decision_fields, "decision")
    gate = _expect_object(decision["gate"], "decision.gate")
    _keys(gate, {"kind", "locator"}, {"kind", "locator"}, "decision.gate")
    gate["kind"] = _choice(
        gate["kind"],
        {"explicit-user", "project-rule", "built-in-stop"},
        "decision.gate.kind",
    )
    gate["locator"] = _single_line(gate["locator"], "decision.gate.locator")
    actions = [_choice(v, {"apply", "adopt", "commit", "publish", "canonicalize"}, "decision.actions[]") for v in _expect_list(decision["actions"], "decision.actions")]
    if not actions or len(actions) != len(set(actions)):
        raise SanctionError("decision.actions must be non-empty and unique")
    decision["actions"] = actions
    if decision["scope"] != "exact-bytes":
        raise SanctionError("decision.scope must be exact-bytes")
    evidence_classification = _choice(
        decision["evidence_classification"],
        {"sensitive", "non-sensitive"},
        "decision.evidence_classification",
    )
    decision["evidence_classification"] = evidence_classification

    roots: dict[str, dict[str, Any]] = {}
    physical_roots: dict[tuple[int, int], str] = {}
    for i, value in enumerate(_expect_list(spec["roots"], "roots")):
        root = _expect_object(value, f"roots[{i}]")
        required_root_fields = {"id", "kind", "path", "base_attestation"}
        _keys(
            root,
            required_root_fields,
            required_root_fields | {"base_revision"},
            f"roots[{i}]",
        )
        ident = _single_line(root["id"], f"roots[{i}].id")
        if ident in roots:
            raise SanctionError(f"duplicate root id: {ident}")
        kind = _choice(root["kind"], {"git", "filesystem"}, f"roots[{i}].kind")
        root["id"] = ident
        root["kind"] = kind
        path = _absolute(root["path"], f"roots[{i}].path")
        _physical_validate(path, f"roots[{i}].path", "dir", allow_missing=False)
        physical_identity = _physical_directory_identity(path, f"roots[{i}].path")
        physical_key = (
            physical_identity["device"],
            physical_identity["inode"],
        )
        if physical_key in physical_roots:
            raise SanctionError(
                f"duplicate physical root denominator: {physical_roots[physical_key]} and {ident}"
            )
        physical_roots[physical_key] = ident
        if kind == "git":
            base_expression = _single_line(
                root.get("base_revision"), f"roots[{i}].base_revision"
            )
            resolved_cp = _git(
                path,
                "rev-parse",
                "--verify",
                "--end-of-options",
                f"{base_expression}^{{commit}}",
                check=False,
            )
            resolved_revision = resolved_cp.stdout.decode().strip().lower()
            if resolved_cp.returncode != 0 or not re.fullmatch(
                r"[0-9a-f]{40}", resolved_revision
            ):
                raise SanctionError(
                    f"roots[{i}].base_revision does not resolve to one concrete Git commit"
                )
            root["_base_revision_expression"] = base_expression
            root["base_revision"] = resolved_revision
            expected_locator = {
                "kind": "git-revision",
                "revision": root["base_revision"],
            }
        elif "base_revision" in root:
            raise SanctionError(f"filesystem root {ident} cannot declare base_revision")
        else:
            expected_locator = {"kind": "filesystem-root", "path": str(path)}
        root["base_attestation"] = _validate_base_attestation(
            root["base_attestation"],
            f"roots[{i}].base_attestation",
            expected_locator,
        )
        root["_path"] = path
        root["_physical_identity"] = physical_identity
        roots[ident] = root

    declared_roots = [_single_line(v, "decision.root_ids[]") for v in _expect_list(decision["root_ids"], "decision.root_ids")]
    if len(declared_roots) != len(set(declared_roots)) or set(declared_roots) != set(roots):
        raise SanctionError("decision.root_ids must exactly equal the unique roots denominator")
    decision["root_ids"] = declared_roots

    targets: dict[str, dict[str, Any]] = {}
    path_keys: set[tuple[str, str]] = set()
    endpoint_paths: dict[str, tuple[str, str]] = {}
    endpoint_files: dict[tuple[int, int], tuple[str, str]] = {}

    def register_endpoint(
        path: Path,
        target_id: str,
        role: str,
        label: str,
    ) -> None:
        resolved = str(path.resolve(strict=False))
        path_key = resolved.casefold() if os.name == "nt" else resolved
        prior = endpoint_paths.get(path_key)
        if prior is not None and prior[0] != target_id:
            raise SanctionError(
                f"duplicate physical target endpoint: {prior[0]} {prior[1]} and {target_id} {role}"
            )
        endpoint_paths[path_key] = (target_id, role)
        if _physical_validate(path, label, "file", allow_missing=True):
            identity = _physical_file_identity(path, label)
            identity_key = (identity["device"], identity["inode"])
            prior = endpoint_files.get(identity_key)
            if prior is not None and prior[0] != target_id:
                raise SanctionError(
                    f"duplicate physical target endpoint: {prior[0]} {prior[1]} and {target_id} {role}"
                )
            endpoint_files[identity_key] = (target_id, role)

    sensitive = False
    for i, value in enumerate(_expect_list(spec["targets"], "targets")):
        target = _expect_object(value, f"targets[{i}]")
        allowed = {"id", "root", "path", "entry", "operation", "base_attestation", "content", "commit", "relationship", "target_source", "base_source", "old_path", "target_mode"}
        _keys(target, {"id", "root", "path", "entry", "operation", "base_attestation", "content", "commit", "relationship"}, allowed, f"targets[{i}]")
        ident = _single_line(target["id"], f"targets[{i}].id")
        if ident in targets:
            raise SanctionError(f"duplicate target id: {ident}")
        root_id = _single_line(target["root"], f"targets[{i}].root")
        if root_id not in roots:
            raise SanctionError(f"target {ident} names unknown root {root_id}")
        rel = _relative(target["path"], f"targets[{i}].path")
        target_endpoint = _root_relative_physical_path(
            roots[root_id]["_path"], rel, f"targets[{i}].path"
        )
        key = (root_id, rel.casefold() if os.name == "nt" else rel)
        if key in path_keys:
            raise SanctionError(f"duplicate target path in root {root_id}: {rel}")
        path_keys.add(key)
        entry = _choice(target["entry"], {"pre-apply", "already-applied"}, f"targets[{i}].entry")
        operation = _choice(target["operation"], {"add", "modify", "delete", "rename", "mode-change"}, f"targets[{i}].operation")
        target["id"] = ident
        target["root"] = root_id
        target["entry"] = entry
        target["operation"] = operation
        register_endpoint(target_endpoint, ident, "path", f"targets[{i}].path")
        if not isinstance(target["commit"], bool):
            raise SanctionError(f"targets[{i}].commit must be boolean")
        if roots[root_id]["kind"] == "filesystem" and target["commit"]:
            raise SanctionError(f"filesystem target {ident} cannot be marked commit=true")
        if operation == "delete":
            if "target_source" in target:
                raise SanctionError(f"delete target {ident} cannot have target_source")
        else:
            target["_target_source"] = _absolute(
                target.get("target_source"),
                f"targets[{i}].target_source",
                must_exist=False,
            )
        if roots[root_id]["kind"] == "filesystem" and operation != "add":
            target["_base_source"] = _absolute(
                target.get("base_source"),
                f"targets[{i}].base_source",
                must_exist=False,
            )
        elif "base_source" in target:
            raise SanctionError(f"target {ident} may not declare base_source for this root/operation")
        if operation == "rename":
            target["old_path"] = _relative(target.get("old_path"), f"targets[{i}].old_path")
            old_endpoint = _root_relative_physical_path(
                roots[root_id]["_path"], target["old_path"], f"targets[{i}].old_path"
            )
            register_endpoint(
                old_endpoint, ident, "old_path", f"targets[{i}].old_path"
            )
        elif "old_path" in target:
            raise SanctionError(f"non-rename target {ident} cannot declare old_path")
        if "target_mode" in target:
            mode = _choice(target["target_mode"], {"100644", "100755"}, f"targets[{i}].target_mode")
            target["target_mode"] = mode

        if roots[root_id]["kind"] == "git":
            base_path = target.get("old_path", rel)
            expected_locator = {
                "kind": "git-absence" if operation == "add" else "git-object",
                "root": root_id,
                "revision": roots[root_id]["base_revision"],
                "path": base_path,
            }
        elif operation == "add":
            expected_locator = {
                "kind": "filesystem-absence",
                "root": root_id,
                "path": rel,
            }
        else:
            expected_locator = {
                "kind": "filesystem-file",
                "path": str(target["_base_source"]),
            }
        target["base_attestation"] = _validate_base_attestation(
            target["base_attestation"],
            f"targets[{i}].base_attestation",
            expected_locator,
        )

        (
            content,
            representation_kind,
            provenance_kind,
            confidentiality_kind,
        ) = _validate_content(target["content"], f"targets[{i}].content")
        if confidentiality_kind == "sensitive":
            sensitive = True
            if roots[root_id]["kind"] == "git" and target["commit"]:
                raise SanctionError(f"sensitive Git commit target {ident} is unsupported by default")

        relation = _expect_object(target["relationship"], f"targets[{i}].relationship")
        _keys(relation, {"kind"}, {"kind", "group"}, f"targets[{i}].relationship")
        relation_kind = _choice(relation["kind"], {"canonical", "exact-mirror", "adaptation", "independent"}, f"targets[{i}].relationship.kind")
        relation["kind"] = relation_kind
        if relation_kind in {"exact-mirror", "adaptation"}:
            relation["group"] = _single_line(
                relation.get("group"), f"targets[{i}].relationship.group"
            )
        elif "group" in relation:
            raise SanctionError(f"relationship.group only applies to mirror/adaptation target {ident}")

        target["path"] = rel
        target["_entry"] = entry
        target["_operation"] = operation
        target["_representation_kind"] = representation_kind
        target["_provenance_kind"] = provenance_kind
        target["_confidentiality_kind"] = confidentiality_kind
        targets[ident] = target

    mirror_groups = _derive_exact_mirror_groups(targets)
    for target in targets.values():
        if target["_operation"] != "delete":
            _physical_validate(
                target["_target_source"],
                f"target {target['id']} target_source",
                "file",
                allow_missing=False,
            )
        if "_base_source" in target:
            _physical_validate(
                target["_base_source"],
                f"target {target['id']} base_source",
                "file",
                allow_missing=False,
            )

    declared_targets = [_single_line(v, "decision.target_ids[]") for v in _expect_list(decision["target_ids"], "decision.target_ids")]
    if len(declared_targets) != len(set(declared_targets)) or set(declared_targets) != set(targets):
        raise SanctionError("decision.target_ids must exactly equal the unique targets denominator")
    decision["target_ids"] = declared_targets

    residue = _validate_residue_rows(spec["residue"], roots, "residue")
    denominator_attestation = _validate_denominator_attestation(
        spec["denominator_attestation"], decision, roots, residue
    )

    groups: dict[str, dict[str, Any]] = {}
    sensitive_generated_artifacts = False
    for i, value in enumerate(_expect_list(spec["generated_groups"], "generated_groups")):
        group = _expect_object(value, f"generated_groups[{i}]")
        group_fields = {
            "id", "generator", "generator_source", "command_display",
            "tool_versions", "inputs", "outputs", "determinism",
        }
        _keys(group, group_fields, group_fields, f"generated_groups[{i}]")
        ident = _nonempty(group["id"], f"generated_groups[{i}].id")
        if ident in groups:
            raise SanctionError(f"duplicate generated group: {ident}")
        _nonempty(group["generator"], f"generated_groups[{i}].generator")
        generator_source = _validate_classified_artifact(
            group["generator_source"], f"generated_groups[{i}].generator_source"
        )
        group["_generator_source"] = generator_source["_path"]
        _nonempty(group["command_display"], f"generated_groups[{i}].command_display")
        versions = [_nonempty(v, f"generated_groups[{i}].tool_versions[]") for v in _expect_list(group["tool_versions"], f"generated_groups[{i}].tool_versions")]
        if not versions:
            raise SanctionError(f"generated_groups[{i}].tool_versions cannot be empty")
        input_artifacts = [
            _validate_classified_artifact(value, f"generated_groups[{i}].inputs[{j}]")
            for j, value in enumerate(
                _expect_list(group["inputs"], f"generated_groups[{i}].inputs")
            )
        ]
        group["_input_artifacts"] = input_artifacts
        group["_inputs"] = [artifact["_path"] for artifact in input_artifacts]
        artifact_paths = [
            os.path.normcase(str(generator_source["_path"].resolve(strict=True))),
            *(
                os.path.normcase(str(artifact["_path"].resolve(strict=True)))
                for artifact in input_artifacts
            ),
        ]
        if len(artifact_paths) != len(set(artifact_paths)):
            raise SanctionError(
                f"generated group {ident} generator_source and inputs must name unique files"
            )
        sensitive_generated_artifacts = sensitive_generated_artifacts or any(
            artifact["_confidentiality_kind"] == "sensitive"
            for artifact in (generator_source, *input_artifacts)
        )
        outputs = [_nonempty(v, f"generated_groups[{i}].outputs[]") for v in _expect_list(group["outputs"], f"generated_groups[{i}].outputs")]
        if not outputs or len(outputs) != len(set(outputs)):
            raise SanctionError(f"generated_groups[{i}].outputs must be non-empty and unique")
        det = _expect_object(group["determinism"], f"generated_groups[{i}].determinism")
        _keys(
            det,
            {"promised", "run_a"},
            {"promised", "run_a", "run_b", "reason"},
            f"generated_groups[{i}].determinism",
        )
        if not isinstance(det["promised"], bool):
            raise SanctionError(f"generated_groups[{i}].determinism.promised must be boolean")
        group["_run_a"] = _absolute(det["run_a"], f"generated_groups[{i}].determinism.run_a")
        if det["promised"]:
            if "run_b" not in det:
                raise SanctionError(f"generated group {ident} promises determinism but omits run_b")
            if "reason" in det:
                raise SanctionError(f"generated group {ident} promises determinism and cannot include a no-promise reason")
            group["_run_b"] = _absolute(det["run_b"], f"generated_groups[{i}].determinism.run_b")
            run_a_identity = _physical_directory_identity(
                group["_run_a"], f"generated group {ident} run_a"
            )
            run_b_identity = _physical_directory_identity(
                group["_run_b"], f"generated group {ident} run_b"
            )
            if run_a_identity == run_b_identity:
                raise SanctionError(
                    f"generated group {ident} run_a and run_b must be physically distinct captures"
                )
            if _within(group["_run_a"], group["_run_b"]) or _within(
                group["_run_b"], group["_run_a"]
            ):
                raise SanctionError(
                    f"generated group {ident} run_a and run_b must be independent, non-nested captures"
                )
        else:
            if "run_b" in det:
                raise SanctionError(f"generated group {ident} does not promise determinism and cannot claim a second-run comparison")
            group["_determinism_reason"] = _nonempty(
                det.get("reason"), f"generated_groups[{i}].determinism.reason"
            )
        groups[ident] = group

    generated_targets = {
        tid for tid, target in targets.items() if target["_provenance_kind"] == "generated"
    }
    owners: dict[str, str] = {}
    for group_id, group in groups.items():
        relative_outputs: dict[str, str] = {}
        for target_id in group["outputs"]:
            if target_id in owners:
                raise SanctionError(
                    f"generated target {target_id} has multiple group owners: "
                    f"{owners[target_id]} and {group_id} (duplicate ownership)"
                )
            owners[target_id] = group_id
            if target_id not in targets:
                continue
            target = targets[target_id]
            if target["_provenance_kind"] != "generated":
                continue
            relative_output = target["content"]["provenance"]["relative_output"]
            if relative_output in relative_outputs:
                raise SanctionError(
                    f"generated group {group_id} has duplicate relative_output {relative_output!r} "
                    f"for {relative_outputs[relative_output]} and {target_id}"
                )
            relative_outputs[relative_output] = target_id
        group["_relative_outputs"] = relative_outputs

    group_outputs = set(owners)
    if generated_targets != group_outputs:
        raise SanctionError("generated group outputs must exactly enumerate every generated target")
    for tid in generated_targets:
        group_id = targets[tid]["content"]["provenance"]["group"]
        if group_id not in groups or tid not in groups[group_id]["outputs"]:
            raise SanctionError(f"generated target {tid} is not owned by its declared group {group_id}")
    for group_id, group in groups.items():
        capture_roots = [("run_a", group["_run_a"])]
        if "_run_b" in group:
            capture_roots.append(("run_b", group["_run_b"]))
        classified_artifacts = [
            ("generator source", group["generator_source"]),
            *(
                (f"generator input {index}", artifact)
                for index, artifact in enumerate(group["_input_artifacts"])
            ),
        ]
        for artifact_role, artifact in classified_artifacts:
            for run_name, capture_root in capture_roots:
                if _within(artifact["_path"], capture_root):
                    raise SanctionError(
                        f"generated group {group_id} {artifact_role} is inside the {run_name} capture"
                    )
        for target_id in group["outputs"]:
            target_source = targets[target_id].get("_target_source")
            if target_source is None:
                continue
            for run_name, capture_root in capture_roots:
                if _within(target_source, capture_root):
                    raise SanctionError(
                        f"generated target {target_id} target_source is inside the {run_name} capture"
                    )

    spec["_roots"] = roots
    spec["_targets"] = targets
    spec["_residue"] = residue
    spec["_denominator_attestation"] = denominator_attestation
    spec["_groups"] = groups
    spec["_mirror_groups"] = mirror_groups
    spec["_sensitive_targets"] = sensitive
    spec["_sensitive_generated_artifacts"] = sensitive_generated_artifacts
    spec["_decision_sensitive"] = evidence_classification == "sensitive"
    spec["_sensitive"] = (
        sensitive
        or sensitive_generated_artifacts
        or spec["_decision_sensitive"]
    )
    spec["_manifest_contract"] = _manifest_contract(spec)
    return spec


def _mode_for_file(path: Path) -> str:
    snapshot = _read_snapshot(path, "mode observation", missing_ok=True)
    return "absent" if snapshot is None else snapshot[1]


def _worktree_mode_observable(root: dict[str, Any]) -> bool:
    """Return whether this worktree can supply authoritative executable-mode evidence."""
    if root["kind"] == "git":
        cp = _git(root["_path"], "config", "--bool", "core.filemode", check=False)
        if cp.returncode == 0:
            return cp.stdout.decode().strip().lower() == "true"
    return os.name != "nt"


def _mode_matches(observed: str, expected: str, *, observable: bool) -> bool:
    """Compare live mode only where the filesystem can actually represent it."""
    if observed == "absent" or expected == "absent":
        return observed == expected
    return observed == expected if observable else True


def _path_identity_and_mode(
    path: Path,
    *,
    sensitive: bool,
    key: bytes | None,
    nonce: str,
    target_id: str,
    role: str,
) -> tuple[dict[str, Any], str]:
    snapshot = _read_snapshot(path, f"target {target_id} {role}", missing_ok=True)
    if snapshot is None:
        return {"algorithm": "absent"}, "absent"
    data, mode = snapshot
    if sensitive:
        if key is None:
            raise SanctionError("sensitive identity requested without HMAC key")
        return _hmac_identity(data, key, nonce, target_id, role), mode
    return _identity(data), mode


def _path_identity(path: Path, *, sensitive: bool, key: bytes | None, nonce: str, target_id: str, role: str) -> dict[str, Any]:
    identity, _mode = _path_identity_and_mode(
        path, sensitive=sensitive, key=key, nonce=nonce, target_id=target_id, role=role
    )
    return identity


def _same_identity(left: dict[str, Any], right: dict[str, Any]) -> bool:
    return left.get("algorithm") == right.get("algorithm") and left.get("value") == right.get("value") and left.get("bytes") == right.get("bytes")


def _freeze(path: Path, data: bytes, *, sensitive: bool) -> str | None:
    if sensitive:
        return None
    _write_bytes(path, data)
    return str(path.resolve())


def _capture_target_material(spec: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Read every proposed source exactly once for one build/verify phase."""
    material: dict[str, dict[str, Any]] = {}
    for target_id in spec["decision"]["target_ids"]:
        target = spec["_targets"][target_id]
        root = spec["_roots"][target["root"]]
        operation = target["_operation"]
        base_path = target.get("old_path", target["path"])
        base_physical: dict[str, int] | None = None
        target_physical: dict[str, int] | None = None

        if root["kind"] == "git":
            base_bytes, base_mode = _git_blob_at(
                root["_path"], root["base_revision"], base_path
            )
        elif operation == "add":
            base_bytes, base_mode = None, "absent"
        else:
            base_snapshot = _read_snapshot_physical(
                target["_base_source"], f"target {target_id} base source"
            )
            assert base_snapshot is not None
            base_bytes, base_mode, base_physical = base_snapshot

        if operation == "add" and base_bytes is not None:
            raise SanctionError(f"add target {target_id} already exists in its declared base")
        if operation != "add" and base_bytes is None:
            raise SanctionError(f"{operation} target {target_id} is absent from its declared base")

        if operation == "delete":
            target_bytes, target_mode = None, "absent"
        else:
            target_snapshot = _read_snapshot_physical(
                target["_target_source"], f"target {target_id} source"
            )
            assert target_snapshot is not None
            target_bytes, source_mode, target_physical = target_snapshot
            if "target_mode" in target:
                target_mode = target["target_mode"]
            elif operation == "add":
                target_mode = "100644"
            else:
                target_mode = base_mode
        if target_mode == "160000" or base_mode == "160000":
            raise SanctionError(f"submodule mode is unsupported for target {target_id}")
        material[target_id] = {
            "base_bytes": base_bytes,
            "base_mode": base_mode,
            "base_physical": base_physical,
            "target_bytes": target_bytes,
            "target_mode": target_mode,
            "target_physical": target_physical,
        }
    return material


def _current_state(
    spec: dict[str, Any],
    target: dict[str, Any],
    key: bytes | None,
    nonce: str,
) -> dict[str, Any]:
    root = spec["_roots"][target["root"]]
    current = _root_relative_physical_path(
        root["_path"], target["path"], f"target {target['id']} current path"
    )
    sensitive = target["_confidentiality_kind"] == "sensitive"
    mode_observable = _worktree_mode_observable(root)
    current_identity, current_mode = _path_identity_and_mode(
        current,
        sensitive=sensitive,
        key=key,
        nonce=nonce,
        target_id=target["id"],
        role="current",
    )
    result: dict[str, Any] = {
        "path": str(current),
        "identity": current_identity,
        "mode": current_mode,
        "mode_observable": mode_observable,
    }
    if target["_operation"] == "rename":
        old = _root_relative_physical_path(
            root["_path"], target["old_path"], f"target {target['id']} old current path"
        )
        old_identity, old_mode = _path_identity_and_mode(
            old,
            sensitive=sensitive,
            key=key,
            nonce=nonce,
            target_id=target["id"],
            role="old-current",
        )
        result["old_path"] = str(old)
        result["old_identity"] = old_identity
        result["old_mode"] = old_mode
        result["old_mode_observable"] = mode_observable
    return result


def _freshness_state(target: dict[str, Any], observation: dict[str, Any]) -> str:
    op = target["_operation"]
    entry = target["_entry"]
    current = observation["current"]
    base = observation["base"]
    proposed = observation["target"]
    if entry == "pre-apply":
        if op == "rename":
            good = (
                _same_identity(current["old_identity"], base)
                and _mode_matches(
                    current["old_mode"],
                    observation["base_mode"],
                    observable=current["old_mode_observable"],
                )
                and current["identity"]["algorithm"] == "absent"
            )
        else:
            good = _same_identity(current["identity"], base) and _mode_matches(
                current["mode"], observation["base_mode"], observable=current["mode_observable"]
            )
        return "BASE" if good else "DRIFT"
    if op == "delete":
        good = current["identity"]["algorithm"] == "absent" and current["mode"] == "absent"
    elif op == "rename":
        good = (
            _same_identity(current["identity"], proposed)
            and _mode_matches(
                current["mode"], observation["target_mode"], observable=current["mode_observable"]
            )
            and current["old_identity"]["algorithm"] == "absent"
        )
    else:
        good = _same_identity(current["identity"], proposed) and _mode_matches(
            current["mode"], observation["target_mode"], observable=current["mode_observable"]
        )
    return "TARGET" if good else "DRIFT"


def _observe_roots(spec: dict[str, Any]) -> dict[str, Any]:
    observed: dict[str, Any] = {}
    for root_id, root in spec["_roots"].items():
        path = root["_path"]
        row: dict[str, Any] = {
            "id": root_id,
            "kind": root["kind"],
            "path": str(path),
            "base_revision": root.get("base_revision"),
            "base_attestation": root["base_attestation"],
            "physical": _physical_directory_identity(path, f"root {root_id}"),
        }
        if root["kind"] == "git":
            inside = _git(path, "rev-parse", "--is-inside-work-tree").stdout.decode().strip()
            if inside != "true":
                raise SanctionError(f"Git root is not a work tree: {path}")
            head = _git(path, "rev-parse", "HEAD").stdout.decode().strip()
            declared = _git(path, "rev-parse", root["base_revision"]).stdout.decode().strip()
            if len(declared) != 40 or head != declared:
                raise SanctionError(f"Git root {root_id} HEAD/base drift: declared {declared}, current {head}")
            branch_cp = _git(path, "symbolic-ref", "--quiet", "--short", "HEAD", check=False)
            branch = branch_cp.stdout.decode().strip() if branch_cp.returncode == 0 else "DETACHED"
            git_dir_text = _git(path, "rev-parse", "--absolute-git-dir").stdout.decode().strip()
            object_text = _git(path, "rev-parse", "--git-path", "objects").stdout.decode().strip()
            object_path = Path(object_text)
            if not object_path.is_absolute():
                object_path = path / object_path
            row.update(
                head=head,
                branch=branch,
                git_dir=str(Path(git_dir_text).resolve()),
                object_dir=str(object_path.resolve()),
                status=_git_status(path),
                index=_index_snapshot(path),
            )
        observed[root_id] = row
    return observed


def _validate_residue(
    spec: dict[str, Any],
    roots_obs: dict[str, Any],
    *,
    allow_all_targets: bool = False,
) -> None:
    expected: dict[tuple[str, str], set[str]] = {}
    for row in spec["_residue"]:
        key = (row["root"], row["path"])
        if key in expected:
            raise SanctionError(f"duplicate residue declaration: {row['root']}:{row['path']}")
        expected[key] = set(row["states"])

    covered: dict[str, dict[str, set[str]]] = {
        root_id: {} for root_id in spec["_roots"]
    }
    live_only_paths: dict[str, set[str]] = {
        root_id: set() for root_id in spec["_roots"]
    }
    for target in spec["_targets"].values():
        if spec["_roots"][target["root"]]["kind"] != "git":
            continue
        paths = {target["path"]}
        if target["_operation"] == "rename":
            paths.add(target["old_path"])
        if not target["commit"]:
            live_only_paths[target["root"]].update(paths)
        if allow_all_targets or target["_entry"] == "already-applied":
            allowed_states = (
                {"unstaged", "untracked"}
                if not target["commit"]
                else {"staged", "unstaged", "untracked"}
            )
            for path in paths:
                covered[target["root"]].setdefault(path, set()).update(
                    allowed_states
                )

    actual: dict[tuple[str, str], set[str]] = {}
    for root_id, root in spec["_roots"].items():
        if root["kind"] != "git":
            continue
        for state, paths in roots_obs[root_id]["status"].items():
            for path in paths:
                if state == "staged" and path in live_only_paths[root_id]:
                    raise SanctionError(
                        f"commit:false Git target must remain unstaged: {root_id}:{path}"
                    )
                if state in covered[root_id].get(path, set()):
                    continue
                # A pre-apply target already dirty is a base conflict, not residue.
                matching = [
                    target for target in spec["_targets"].values()
                    if target["root"] == root_id and target["_entry"] == "pre-apply"
                    and path in {target["path"], target.get("old_path")}
                ]
                if matching:
                    raise SanctionError(f"pre-apply target already has Git {state} state: {root_id}:{path}")
                actual.setdefault((root_id, path), set()).add(state)
    if actual != expected:
        def show(value: dict[tuple[str, str], set[str]]) -> dict[str, list[str]]:
            return {f"{root}:{path}": sorted(states) for (root, path), states in sorted(value.items())}
        raise SanctionError(f"Git residue denominator mismatch; declared={show(expected)} actual={show(actual)}")


def _enumerate_generated_tree(
    root: Path,
    label: str,
) -> tuple[dict[str, int], dict[str, dict[str, Any]]]:
    """Enumerate names/types/metadata without reading any file contents."""
    root_identity = _physical_directory_identity(root, label)
    rows: dict[str, dict[str, Any]] = {}

    def walk(directory: Path, prefix: PurePosixPath) -> None:
        _physical_validate(directory, label, "dir", allow_missing=False)
        try:
            with os.scandir(directory) as iterator:
                entries = sorted(list(iterator), key=lambda item: item.name)
        except OSError as exc:
            raise SanctionError(f"cannot enumerate exact generated inventory for {label}: {exc}") from exc
        for entry in entries:
            path = directory / entry.name
            relative = (prefix / entry.name).as_posix()
            if _is_reparse_or_symlink(path):
                raise SanctionError(
                    f"exact generated inventory for {label} crosses a reparse/symlink entry: {relative}"
                )
            try:
                st = entry.stat(follow_symlinks=False)
            except OSError as exc:
                raise SanctionError(
                    f"cannot inspect exact generated inventory entry {label}:{relative}: {exc}"
                ) from exc
            stamp = {
                "mode": int(st.st_mode),
                "size": int(st.st_size),
                "mtime_ns": int(getattr(st, "st_mtime_ns", 0)),
                "ctime_ns": int(getattr(st, "st_ctime_ns", 0)),
            }
            if entry.is_dir(follow_symlinks=False):
                physical = _physical_directory_identity(
                    path, f"generated inventory directory {label}:{relative}"
                )
                rows[relative] = {
                    "type": "directory",
                    "physical": physical,
                    "_stamp": stamp,
                }
                walk(path, PurePosixPath(relative))
            elif entry.is_file(follow_symlinks=False):
                physical = _physical_file_identity(
                    path, f"generated inventory file {label}:{relative}"
                )
                rows[relative] = {
                    "type": "file",
                    "mode": (
                        "100755"
                        if os.name != "nt" and st.st_mode & stat.S_IXUSR
                        else "100644"
                    ),
                    "mode_observable": os.name != "nt",
                    "physical": physical,
                    "_stamp": stamp,
                }
            else:
                raise SanctionError(
                    f"exact generated inventory for {label} contains unsupported entry type: {relative}"
                )
    walk(root, PurePosixPath())
    if _physical_directory_identity(root, label) != root_identity:
        raise SanctionError(f"{label} capture identity changed during exact inventory enumeration")
    return root_identity, rows


def _expected_generated_entries(relative_outputs: set[str]) -> set[str]:
    expected = set(relative_outputs)
    for relative in relative_outputs:
        parent = PurePosixPath(relative).parent
        while parent.as_posix() not in {"", "."}:
            expected.add(parent.as_posix())
            parent = parent.parent
    return expected


def _capture_generated_run(
    *,
    group_id: str,
    run_name: str,
    root: Path,
    relative_outputs: dict[str, str],
    spec: dict[str, Any],
    key: bytes | None,
    nonce: str,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    root_identity, before = _enumerate_generated_tree(
        root, f"generated group {group_id} {run_name}"
    )
    expected = _expected_generated_entries(set(relative_outputs))
    actual = set(before)
    missing = sorted(expected - actual)
    extra = sorted(actual - expected)
    if missing:
        raise SanctionError(
            f"generated {run_name} exact inventory is missing declared entries: {missing}"
        )
    if extra:
        raise SanctionError(
            f"generated {run_name} exact inventory has undeclared extra entries: {extra}"
        )

    raw: dict[str, dict[str, Any]] = {}
    public_inventory: dict[str, dict[str, Any]] = {}
    for relative, row in sorted(before.items()):
        if relative not in relative_outputs:
            if row["type"] != "directory":
                raise SanctionError(
                    f"generated {run_name} exact inventory entry is not a declared output: {relative}"
                )
            public_inventory[relative] = {
                "type": "directory",
                "physical": row["physical"],
            }
            continue
        if row["type"] != "file":
            raise SanctionError(
                f"generated {run_name} declared output is not a regular file: {relative}"
            )
        target_id = relative_outputs[relative]
        target = spec["_targets"][target_id]
        snapshot = _read_snapshot_physical(
            root.joinpath(*PurePosixPath(relative).parts),
            f"generated group {group_id} {run_name} output {relative}",
        )
        assert snapshot is not None
        data, mode, physical = snapshot
        if physical != row["physical"] or (
            row["mode_observable"] and mode != row["mode"]
        ):
            raise SanctionError(
                f"generated {run_name} output physical identity changed between enumeration and capture read: {relative}"
            )
        sensitive = target["_confidentiality_kind"] == "sensitive"
        identity = _scoped_identity(
            data,
            sensitive=sensitive,
            key=key,
            nonce=nonce,
            scope=f"generated:{group_id}:{run_name}:{relative}",
        )
        public_inventory[relative] = {
            "type": "file",
            "mode": mode,
            "mode_observable": row["mode_observable"],
            "physical": physical,
            "identity": identity,
        }
        raw[relative] = {
            "bytes": data,
            "mode": mode,
            "mode_observable": row["mode_observable"],
            "physical": physical,
        }

    after_identity, after = _enumerate_generated_tree(
        root, f"generated group {group_id} {run_name}"
    )
    if after_identity != root_identity or after != before:
        raise SanctionError(
            f"generated {run_name} capture changed during exact inventory observation"
        )
    return {
        "path": str(root),
        "directory_identity": root_identity,
        "inventory": public_inventory,
    }, raw


def _observe_classified_artifact(
    artifact: dict[str, Any],
    *,
    label: str,
    key: bytes | None,
    nonce: str,
    scope: str,
) -> dict[str, Any]:
    snapshot = _read_snapshot_physical(artifact["_path"], label)
    assert snapshot is not None
    data, mode, physical = snapshot
    sensitive = artifact["_confidentiality_kind"] == "sensitive"
    return {
        "path": str(artifact["_path"]),
        "content": json.loads(json.dumps(artifact["content"])),
        "mode": mode,
        "physical": physical,
        "identity": _scoped_identity(
            data,
            sensitive=sensitive,
            key=key,
            nonce=nonce,
            scope=scope,
        ),
    }


def _observe_generated(
    spec: dict[str, Any],
    material: dict[str, dict[str, Any]],
    key: bytes | None,
    nonce: str,
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for group_id, group in spec["_groups"].items():
        generator_source = _observe_classified_artifact(
            group["generator_source"],
            label=f"generated group {group_id} generator_source",
            key=key,
            nonce=nonce,
            scope=f"generated:{group_id}:generator-source",
        )
        inputs = [
            _observe_classified_artifact(
                artifact,
                label=f"generated group {group_id} input {index}",
                key=key,
                nonce=nonce,
                scope=f"generated:{group_id}:input:{index}",
            )
            for index, artifact in enumerate(group["_input_artifacts"])
        ]
        run_a, raw_a = _capture_generated_run(
            group_id=group_id,
            run_name="run_a",
            root=group["_run_a"],
            relative_outputs=group["_relative_outputs"],
            spec=spec,
            key=key,
            nonce=nonce,
        )
        captures = {"run_a": run_a}
        promised = group["determinism"]["promised"]
        raw_b: dict[str, dict[str, Any]] | None = None
        if promised:
            run_b, raw_b = _capture_generated_run(
                group_id=group_id,
                run_name="run_b",
                root=group["_run_b"],
                relative_outputs=group["_relative_outputs"],
                spec=spec,
                key=key,
                nonce=nonce,
            )
            captures["run_b"] = run_b
            run_a_physical = {
                (row["physical"]["device"], row["physical"]["inode"])
                for row in raw_a.values()
            }
            run_b_physical = {
                (row["physical"]["device"], row["physical"]["inode"])
                for row in raw_b.values()
            }
            if run_a_physical.intersection(run_b_physical):
                raise SanctionError(
                    f"generated group {group_id} run_a and run_b physical identity sets overlap; captures are not independent"
                )
            for relative in sorted(raw_a):
                if (
                    raw_a[relative]["bytes"] != raw_b[relative]["bytes"]
                    or (
                        raw_a[relative]["mode_observable"]
                        and raw_a[relative]["mode"] != raw_b[relative]["mode"]
                    )
                ):
                    raise SanctionError(
                        f"generated group {group_id} promised determinism but run inventories differ at {relative}"
                    )

        for relative, target_id in group["_relative_outputs"].items():
            target_material = material[target_id]
            captured = raw_a[relative]
            supplied_runs = [("run_a", raw_a)]
            if raw_b is not None:
                supplied_runs.append(("run_b", raw_b))
            for run_name, run_material in supplied_runs:
                if target_material["target_physical"] == run_material[relative]["physical"]:
                    raise SanctionError(
                        f"generated target {target_id} target_source physically aliases the {run_name} capture output {relative}"
                    )
            if (
                target_material["target_bytes"] != captured["bytes"]
                or (
                    captured["mode_observable"]
                    and target_material["target_mode"] != captured["mode"]
                )
            ):
                raise SanctionError(
                    f"generated target {target_id} does not match the declared run_a capture output {relative}"
                )

        row = {
            "generator": group["generator"],
            "generator_source": generator_source,
            "command_display": group["command_display"],
            "tool_versions": group["tool_versions"],
            "inputs": inputs,
            "outputs": list(group["outputs"]),
            "captures": captures,
            "determinism": "MATCH" if promised else "NOT_PROMISED",
        }
        if not promised:
            row["determinism_reason"] = group["_determinism_reason"]
        result[group_id] = row
    return result


def _observe_exact_mirrors(
    spec: dict[str, Any],
    material: dict[str, dict[str, Any]],
    key: bytes | None,
    nonce: str,
) -> dict[str, Any]:
    observed: dict[str, Any] = {}
    for group_id, members in spec["_mirror_groups"].items():
        first_id = members[0]
        first_target = spec["_targets"][first_id]
        first_material = material[first_id]
        for member_id in members[1:]:
            member_material = material[member_id]
            if member_material["base_mode"] != first_material["base_mode"]:
                raise SanctionError(
                    f"exact-mirror group {group_id} mirror base-mode mismatch between {first_id} and {member_id}"
                )
            if member_material["target_mode"] != first_material["target_mode"]:
                raise SanctionError(
                    f"exact-mirror group {group_id} mirror target-mode mismatch between {first_id} and {member_id}"
                )
            if member_material["base_bytes"] != first_material["base_bytes"]:
                raise SanctionError(
                    f"exact-mirror group {group_id} mirror base mismatch between {first_id} and {member_id}"
                )
            if member_material["target_bytes"] != first_material["target_bytes"]:
                raise SanctionError(
                    f"exact-mirror group {group_id} mirror target mismatch between {first_id} and {member_id}"
                )

        sensitive = first_target["_confidentiality_kind"] == "sensitive"

        def parity(data: bytes | None, role: str) -> dict[str, Any]:
            if data is None:
                return {"algorithm": "absent"}
            return _scoped_identity(
                data,
                sensitive=sensitive,
                key=key,
                nonce=nonce,
                scope=f"exact-mirror:{group_id}:{role}",
            )

        observed[group_id] = {
            "members": list(members),
            "path": first_target["path"],
            "old_path": first_target.get("old_path"),
            "operation": first_target["_operation"],
            "base_mode": first_material["base_mode"],
            "target_mode": first_material["target_mode"],
            "representation": first_target["_representation_kind"],
            "provenance": first_target["_provenance_kind"],
            "confidentiality": first_target["_confidentiality_kind"],
            "base_parity": parity(first_material["base_bytes"], "base"),
            "target_parity": parity(first_material["target_bytes"], "target"),
        }
    return observed


def _observe_targets(
    spec: dict[str, Any],
    material: dict[str, dict[str, Any]],
    out: Path,
    key: bytes | None,
    nonce: str,
) -> dict[str, Any]:
    observed: dict[str, Any] = {}
    for target_id in spec["decision"]["target_ids"]:
        target = spec["_targets"][target_id]
        target_material = material[target_id]
        base_bytes = target_material["base_bytes"]
        base_mode = target_material["base_mode"]
        target_bytes = target_material["target_bytes"]
        target_mode = target_material["target_mode"]
        sensitive = target["_confidentiality_kind"] == "sensitive"
        if sensitive:
            assert key is not None
            base_ident = {"algorithm": "absent"} if base_bytes is None else _hmac_identity(base_bytes, key, nonce, target_id, "base")
            target_ident = {"algorithm": "absent"} if target_bytes is None else _hmac_identity(target_bytes, key, nonce, target_id, "target")
        else:
            base_ident = {"algorithm": "absent"} if base_bytes is None else _identity(base_bytes)
            target_ident = {"algorithm": "absent"} if target_bytes is None else _identity(target_bytes)

        suffix = Path(target["path"]).suffix or ".bin"
        base_frozen = None if base_bytes is None else _freeze(out / "bases" / f"{_safe_component(target_id)}{suffix}", base_bytes, sensitive=sensitive)
        target_frozen = None if target_bytes is None else _freeze(out / "targets" / f"{_safe_component(target_id)}{suffix}", target_bytes, sensitive=sensitive)
        current = _current_state(spec, target, key, nonce)
        row: dict[str, Any] = {
            "id": target_id,
            "root": target["root"],
            "path": target["path"],
            "old_path": target.get("old_path"),
            "entry": target["_entry"],
            "operation": target["_operation"],
            "representation_kind": target["_representation_kind"],
            "provenance_kind": target["_provenance_kind"],
            "confidentiality_kind": target["_confidentiality_kind"],
            "commit": target["commit"],
            "relationship": target["relationship"],
            "base_attestation": target["base_attestation"],
            "base": base_ident,
            "target": target_ident,
            "base_mode": base_mode,
            "target_mode": target_mode,
            "base_frozen": base_frozen,
            "target_frozen": target_frozen,
            "base_source": str(target.get("_base_source", "")) or None,
            "target_source": str(target.get("_target_source", "")) or None,
            "declared_target_mode": target.get("target_mode"),
            "current": current,
            "content": {k: v for k, v in target["content"].items()},
        }
        row["freshness"] = _freshness_state(target, row)
        if row["freshness"] == "DRIFT":
            raise SanctionError(f"target {target_id} is not at its declared {target['_entry']} state")
        observed[target_id] = row
    return observed


def _review_patch_for_root(
    spec: dict[str, Any],
    target_obs: dict[str, Any],
    root_id: str,
    out: Path,
) -> dict[str, Any] | None:
    chunks: list[str] = []
    for target_id in spec["decision"]["target_ids"]:
        target = spec["_targets"][target_id]
        obs = target_obs[target_id]
        if (
            target["root"] != root_id
            or target["_representation_kind"] != "text"
            or target["_confidentiality_kind"] == "sensitive"
        ):
            continue
        encoding = target["content"]["representation"]["encoding"]
        base_bytes = b"" if obs["base_frozen"] is None else _read(Path(obs["base_frozen"]), f"target {target_id} frozen base")
        target_bytes = b"" if obs["target_frozen"] is None else _read(Path(obs["target_frozen"]), f"target {target_id} frozen target")
        base_text = _decode_text(base_bytes, encoding, f"target {target_id} base")
        target_text = _decode_text(target_bytes, encoding, f"target {target_id} target")
        old_name = target.get("old_path", target["path"])
        chunks.append(f"diff --sanction a/{old_name} b/{target['path']}\n")
        if obs["base_mode"] != obs["target_mode"]:
            chunks.append(f"old mode {obs['base_mode']}\nnew mode {obs['target_mode']}\n")
        if target["_operation"] == "rename":
            chunks.append(f"rename from {target['old_path']}\nrename to {target['path']}\n")
        if base_bytes != target_bytes or target["_operation"] in {"add", "delete"}:
            chunks.extend(
                difflib.unified_diff(
                    base_text.splitlines(keepends=True),
                    target_text.splitlines(keepends=True),
                    fromfile=f"a/{old_name}" if base_bytes else "/dev/null",
                    tofile=f"b/{target['path']}" if target_bytes else "/dev/null",
                    n=3,
                )
            )
        chunks.append("\n")
    if not chunks:
        return None
    path = out / "repos" / _safe_component(root_id) / "review.patch"
    _write_text(path, "".join(chunks))
    return _artifact(path)


def _pin_candidate_workspace(
    repo_out: Path,
    object_dir: Path,
    index_path: Path,
    root_id: str,
) -> tuple[list[int], str, str, tuple[int, ...]]:
    """Pin Git's writable namespace for every subprocess in candidate construction."""
    if os.name == "nt":
        handles = _win_open_directory_chain(
            object_dir, f"candidate workspace for {root_id}", create=False
        )
        for value in range(256):
            handles.append(
                _win_open_existing(
                    object_dir / f"{value:02x}",
                    f"candidate object fanout for {root_id}",
                    "dir",
                )
            )
        return handles, str(index_path), str(object_dir), ()

    fds = _posix_open_directory_chain(
        object_dir, f"candidate workspace for {root_id}", create=False
    )
    repo_fd, object_fd = fds[-2], fds[-1]
    for value in range(256):
        try:
            fanout_fd = os.open(f"{value:02x}", _posix_dir_flags(), dir_fd=object_fd)
        except OSError as exc:
            _posix_close_all(fds)
            raise SanctionError(
                f"cannot pin candidate object fanout for {root_id}: {value:02x}: {exc}"
            ) from exc
        fds.append(fanout_fd)
    namespace: Path | None = None
    for base in (Path("/proc/self/fd"), Path("/dev/fd")):
        candidate = base / str(repo_fd)
        try:
            via_namespace = os.stat(candidate)
            pinned = os.fstat(repo_fd)
        except OSError:
            continue
        if (via_namespace.st_dev, via_namespace.st_ino) == (pinned.st_dev, pinned.st_ino):
            namespace = base
            break
    if namespace is None:
        _posix_close_all(fds)
        raise SanctionError(
            "platform cannot expose a pinned directory handle to Git; candidate construction fails closed"
        )
    return (
        fds,
        str(namespace / str(repo_fd) / index_path.name),
        str(namespace / str(object_fd)),
        (repo_fd, object_fd),
    )


def _assert_candidate_fanouts(object_dir: Path, pins: list[int], root_id: str) -> None:
    pinned_fanouts = pins[-256:]
    if len(pinned_fanouts) != 256:
        raise SanctionError(f"candidate object fanout pin set is incomplete for {root_id}")
    for value, pinned in enumerate(pinned_fanouts):
        path = object_dir / f"{value:02x}"
        if os.name == "nt":
            expected_info = _BY_HANDLE_FILE_INFORMATION()
            if not _KERNEL32.GetFileInformationByHandle(pinned, ctypes.byref(expected_info)):
                raise _win_error(f"cannot inspect pinned object fanout for {root_id}", path)
            current = _win_open_existing(path, f"candidate object fanout for {root_id}", "dir")
            try:
                current_info = _BY_HANDLE_FILE_INFORMATION()
                if not _KERNEL32.GetFileInformationByHandle(current, ctypes.byref(current_info)):
                    raise _win_error(f"cannot inspect current object fanout for {root_id}", path)
                expected = (
                    int(expected_info.dwVolumeSerialNumber),
                    int(expected_info.nFileIndexHigh),
                    int(expected_info.nFileIndexLow),
                )
                actual = (
                    int(current_info.dwVolumeSerialNumber),
                    int(current_info.nFileIndexHigh),
                    int(current_info.nFileIndexLow),
                )
            finally:
                _KERNEL32.CloseHandle(current)
        else:
            expected_stat = os.fstat(pinned)
            try:
                current = os.open(f"{value:02x}", _posix_dir_flags(), dir_fd=pins[-257])
            except OSError as exc:
                raise SanctionError(f"candidate object fanout changed for {root_id}: {path}: {exc}") from exc
            try:
                current_stat = os.fstat(current)
                expected = (expected_stat.st_dev, expected_stat.st_ino)
                actual = (current_stat.st_dev, current_stat.st_ino)
            finally:
                os.close(current)
        if actual != expected:
            raise SanctionError(f"candidate object fanout identity changed for {root_id}: {path}")


def _candidate_for_root(
    spec: dict[str, Any],
    roots_obs: dict[str, Any],
    target_obs: dict[str, Any],
    root_id: str,
    out: Path,
) -> dict[str, Any] | None:
    root = spec["_roots"][root_id]
    commit_targets = [
        spec["_targets"][target_id]
        for target_id in spec["decision"]["target_ids"]
        if spec["_targets"][target_id]["root"] == root_id and spec["_targets"][target_id]["commit"]
    ]
    if root["kind"] != "git" or not commit_targets:
        return None
    for target in commit_targets:
        if target["path"] in {".gitattributes", ".gitmodules"} or target.get("old_path") in {".gitattributes", ".gitmodules"}:
            raise SanctionError("v1 fails closed when the sanction transaction changes Git transformation/submodule configuration")

    repo_out = out / "repos" / _safe_component(root_id)
    object_dir = repo_out / "objects"
    _create_physical_directory_exclusive(
        object_dir, f"candidate object directory for {root_id}"
    )
    for value in range(256):
        _create_physical_directory_exclusive(
            object_dir / f"{value:02x}", f"candidate object fanout for {root_id}"
        )
    index_path = repo_out / "candidate.index"
    if _physical_validate(index_path, f"candidate index for {root_id}", None, allow_missing=True):
        raise SanctionError(f"candidate index path already exists: {index_path}")
    real_objects = Path(roots_obs[root_id]["object_dir"])
    pins, git_index_path, git_object_dir, pass_fds = _pin_candidate_workspace(
        repo_out, object_dir, index_path, root_id
    )
    try:
        env = {
            "GIT_INDEX_FILE": git_index_path,
            "GIT_OBJECT_DIRECTORY": git_object_dir,
            "GIT_ALTERNATE_OBJECT_DIRECTORIES": str(real_objects.resolve()),
        }

        index_identity: bytes | None = None

        def current_index() -> bytes | None:
            snapshot = _read_snapshot(
                index_path, f"candidate index for {root_id}", missing_ok=True
            )
            return None if snapshot is None else snapshot[0]

        def git_run(
            *args: str,
            input_bytes: bytes | None = None,
            index_effect: str = "unchanged",
            object_write: bool = False,
        ) -> subprocess.CompletedProcess[bytes]:
            nonlocal index_identity
            before = current_index()
            if before != index_identity:
                raise SanctionError(f"candidate index identity changed before Git {' '.join(args)} in {root_id}")
            check_fanouts = object_write or os.name != "nt"
            if check_fanouts:
                _assert_candidate_fanouts(object_dir, pins, root_id)
            cp = _git(
                root["_path"],
                *args,
                input_bytes=input_bytes,
                extra_env=env,
                pass_fds=pass_fds,
            )
            after = current_index()
            if index_effect == "unchanged" and after != index_identity:
                raise SanctionError(f"Git {' '.join(args)} unexpectedly changed candidate index in {root_id}")
            if index_effect in {"create", "update"}:
                if after is None:
                    raise SanctionError(f"Git {' '.join(args)} did not produce a candidate index in {root_id}")
                index_identity = after
            if check_fanouts:
                _assert_candidate_fanouts(object_dir, pins, root_id)
            if object_write:
                _inventory(object_dir)
            return cp

        base = roots_obs[root_id]["head"]
        git_run("read-tree", base, index_effect="create")

        entries: list[dict[str, Any]] = []
        for target in commit_targets:
            target_id = target["id"]
            obs = target_obs[target_id]
            op = target["_operation"]
            if op in {"delete", "rename"}:
                remove_path = target.get("old_path", target["path"])
                git_run(
                    "update-index", "--force-remove", "--", remove_path, index_effect="update"
                )
            if op == "delete":
                entries.append(
                    {
                        "target": target_id,
                        "operation": op,
                        "path": target["path"],
                        "old_path": target.get("old_path"),
                        "mode": "absent",
                        "blob_oid": "absent",
                        "committed_identity": {"algorithm": "absent"},
                        "committed_artifact": None,
                    }
                )
                continue

            frozen = Path(obs["target_frozen"])
            raw = _read(frozen, f"target {target_id} frozen target")
            oid = git_run(
                "hash-object",
                "-w",
                f"--path={target['path']}",
                "--stdin",
                input_bytes=raw,
                object_write=True,
            ).stdout.decode().strip()
            committed = git_run("cat-file", "blob", oid).stdout
            committed_path = repo_out / "committed" / f"{_safe_component(target_id)}.blob"
            _write_bytes(committed_path, committed)
            mode = obs["target_mode"]
            git_run(
                "update-index",
                "--add",
                "--cacheinfo",
                mode,
                oid,
                target["path"],
                index_effect="update",
            )
            entries.append(
                {
                    "target": target_id,
                    "operation": op,
                    "path": target["path"],
                    "old_path": target.get("old_path"),
                    "mode": mode,
                    "blob_oid": oid,
                    "raw_identity": obs["target"],
                    "committed_identity": _identity(committed),
                    "committed_artifact": str(committed_path.resolve()),
                    "filter_changed_bytes": committed != raw,
                }
            )

        candidate_by_target = {entry["target"]: entry for entry in entries}
        expected_entries = {
            row["path"]: {"path": row["path"], "mode": row["mode"], "oid": row["oid"], "stage": "0"}
            for row in _tree_entries(root["_path"], base)
        }
        for target in commit_targets:
            entry = candidate_by_target[target["id"]]
            if target["_operation"] in {"delete", "rename"}:
                expected_entries.pop(target.get("old_path", target["path"]), None)
            if target["_operation"] != "delete":
                expected_entries[target["path"]] = {
                    "path": target["path"],
                    "mode": entry["mode"],
                    "oid": entry["blob_oid"],
                    "stage": "0",
                }
                committed_bytes = _read(
                    Path(entry["committed_artifact"]),
                    f"committed candidate {target['id']}",
                )
                recomputed_oid = git_run(
                    "hash-object", "--stdin", input_bytes=committed_bytes
                ).stdout.decode().strip()
                if recomputed_oid != entry["blob_oid"]:
                    raise SanctionError(
                        f"candidate blob OID does not match exact committed bytes for {target['id']}"
                    )

        def keyed(rows: list[dict[str, str]], label: str) -> dict[str, tuple[str, str, str]]:
            result: dict[str, tuple[str, str, str]] = {}
            for row in rows:
                if row["path"] in result:
                    raise SanctionError(f"duplicate {label} path in candidate for {root_id}: {row['path']}")
                result[row["path"]] = (row["mode"], row["oid"], row["stage"])
            return result

        expected_keyed = keyed(list(expected_entries.values()), "expected")
        actual_index_raw = git_run("ls-files", "--stage", "-z").stdout
        actual_index = keyed(
            _parse_index_entries(actual_index_raw, f"candidate index for {root_id}"), "index"
        )
        if actual_index != expected_keyed:
            raise SanctionError(f"candidate index entries differ from base plus declared targets in {root_id}")

        tree = git_run("write-tree", index_effect="update", object_write=True).stdout.decode().strip()
        tree_raw = git_run("ls-tree", "-r", "-z", "--full-tree", tree).stdout
        actual_tree = keyed(
            _parse_tree_entries(tree_raw, f"candidate tree for {root_id}"), "tree"
        )
        if actual_tree != expected_keyed:
            raise SanctionError(f"candidate tree entries differ from exact candidate index in {root_id}")
        patch_bytes = git_run(
            "diff", "--binary", "--full-index", "--find-renames", base, tree
        ).stdout
        patch_path = repo_out / "commit.patch"
        _write_bytes(patch_path, patch_bytes)
        changed_paths = sorted(
            _zpaths(
                git_run(
                    "diff", "--name-only", "-z", "--find-renames", base, tree
                ).stdout
            )
        )
        if not changed_paths:
            raise SanctionError(f"Git candidate for {root_id} has no effective changes")
        expected_index_flags = _parse_index_flags(
            git_run("ls-files", "-v", "-z").stdout,
            f"candidate index flags for {root_id}",
        )
        return {
            "root": root_id,
            "base_revision": base,
            "candidate_tree": tree,
            "entries": entries,
            "changed_paths": changed_paths,
            "index_flags": expected_index_flags,
            "patch": _artifact(patch_path),
            "temp_index": str(index_path.resolve()),
            "temp_object_dir": str(object_dir.resolve()),
            "scratch_root": str(repo_out.resolve()),
            "scratch_inventory": _inventory(repo_out),
        }
    finally:
        if os.name == "nt":
            _win_close_all(pins)
        else:
            _posix_close_all(pins)


def _packet_id_payload(lock: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in lock.items() if k not in {"packet_id", "packet_artifact"}}


def _id_short(identity: dict[str, Any]) -> str:
    algorithm = identity.get("algorithm", "unknown")
    if algorithm == "absent":
        return "ABSENT"
    value = str(identity.get("value", ""))
    size = identity.get("bytes", "withheld")
    return f"{algorithm}:{value} bytes={size}"


def _md_path(path: str) -> str:
    # Angle brackets preserve spaces in local Markdown link targets.
    return f"<{path}>"


def _md_visible(value: Any) -> str:
    """Return owner-authored text as an inert, visibly escaped literal."""
    rendered: list[str] = []
    for character in str(value):
        category = unicodedata.category(character)
        if category in {"Cc", "Cf", "Zl", "Zp"}:
            rendered.append(f"\\u{ord(character):04x}")
        else:
            rendered.append(character)
    # HTML escaping prevents raw tags; encoding the table delimiter keeps code
    # spans inert even inside GFM tables.
    return html.escape("".join(rendered), quote=True).replace("|", "&#124;")


def _md_code(value: Any) -> str:
    """Wrap a value in a padded code span whose fence exceeds every authored run.

    The single-space padding is unconditional: a leading, trailing, or
    only-backtick value would otherwise merge with the fence delimiters and
    escape the code span.
    """
    text = _md_visible(value)
    runs = [len(match.group(0)) for match in re.finditer(r"`+", text)]
    fence = "`" * (max(runs, default=0) + 1)
    return f"{fence} {text} {fence}"


def _render_packet(spec: dict[str, Any], lock: dict[str, Any]) -> str:
    contract = lock["manifest_contract"]
    decision = contract["decision"]
    denominator = contract["denominator_attestation"]
    evidence_classification = decision["evidence_classification"]

    def content_dimensions(content: dict[str, Any]) -> str:
        return "/".join(
            (
                content["representation"]["kind"],
                content["provenance"]["kind"],
                content["confidentiality"]["kind"],
            )
        )

    binding_note = (
        "HMAC-SHA-256 with the separately held key; possession of the key is not owner authentication"
        if evidence_classification == "sensitive"
        else "domain-separated SHA-256 for local consistency only; this is not owner authentication"
    )
    bounded_claim = (
        "This packet is mechanically complete for the owner-approved declared scope only; "
        "it does not discover the correct denominator or authoritative base."
    )

    def base_attestation_line(label: str, attestation: dict[str, Any]) -> str:
        selector = attestation["selected_by"]
        locator = _canonical(attestation["locator"]).decode("utf-8")
        verification = attestation["verification"]
        return (
            f"- {_md_code(label)} selected by {_md_code(selector['identity'])} "
            f"({_md_code(selector['role'])}); authority: {_md_code(attestation['authority'])}; "
            f"locator: {_md_code(locator)}; verification: "
            f"{_md_code(verification['method'])}; evidence: "
            f"{_md_code(verification['evidence_locator'])}.\n"
        )

    lines = [
        "# Complete sanction packet\n",
        "\n",
        f"**Packet ID:** `{lock['packet_id']}`  \n",
        f"**Claim:** {CLAIM}  \n",
        "**State:** READY FOR OWNER DECISION — NOT APPROVED  \n",
        f"**Built:** {lock['created_at']} on `{lock['machine']}` with helper `{lock['helper']['sha256']}`\n",
        "\n",
        "> This packet does not authenticate the owner, choose the denominator, judge semantic adequacy, or mutate any target. "
        "It detects observed inconsistency but cannot defeat a same-user attacker who rewrites every local artifact consistently. "
        "Approval/rejection must cite this exact packet ID.\n",
        f"> {bounded_claim}\n",
        "\n",
        "## Decision boundary\n",
        "\n",
        f"- Gate: {_md_code(decision['gate']['kind'])} — {_md_code(decision['gate']['locator'])}\n",
        f"- Decision evidence: `{evidence_classification}` â€” {binding_note}.\n",
        f"- Actions gated: {', '.join(_md_code(a) for a in decision['actions'])}\n",
        f"- Declared roots: {', '.join(_md_code(v) for v in decision['root_ids'])}\n",
        f"- Declared targets: {', '.join(_md_code(v) for v in decision['target_ids'])}\n",
        "\n",
        "## Declared-scope selection attestation\n",
        "\n",
        f"- Selected by: {_md_code(denominator['selected_by']['identity'])} ({_md_code(denominator['selected_by']['role'])})\n",
        f"- Selection basis: {_md_code(denominator['selection_basis'])}\n",
        f"- Root denominator: {', '.join(_md_code(v) for v in denominator['root_ids'])}\n",
        f"- Target denominator: {', '.join(_md_code(v) for v in denominator['target_ids'])}\n",
        f"- Omission check: {_md_code(denominator['omission_check']['method'])}\n",
        f"- Omission evidence: {_md_code(denominator['omission_check']['evidence_locator'])}\n",
    ]
    if denominator["residue"]:
        lines.append("- Residue denominator:\n")
        for row in denominator["residue"]:
            residue_locator = f"{row['root']}:{row['path']}"
            lines.append(
                f"  - {_md_code(residue_locator)} states "
                f"{_md_code(','.join(row['states']))}; disposition {_md_code(row['disposition'])}; "
                f"reason: {_md_code(row['reason'])}\n"
            )
    else:
        lines.append("- Residue denominator: none declared.\n")
    if denominator["exclusions"]:
        lines.append("- Exclusions:\n")
        for exclusion in denominator["exclusions"]:
            lines.append(
                f"  - {_md_code(exclusion['locator'])} — {_md_code(exclusion['reason'])}\n"
            )
    else:
        lines.append("- Exclusions: none declared.\n")

    lines.extend(
        [
            "\n",
            "## Repository and filesystem roots\n",
            "\n",
            "| Root | Ownership | Physical path | Base / state |\n",
            "|---|---|---|---|\n",
        ]
    )
    for root_id in decision["root_ids"]:
        root = contract["roots"][root_id]
        observed_root = lock["roots"][root_id]
        state = (
            f"HEAD {_md_code(observed_root['head'])} · branch {_md_code(observed_root['branch'])}"
            if root["kind"] == "git"
            else "direct filesystem"
        )
        lines.append(
            f"| {_md_code(root_id)} | {_md_code(root['kind'])} | {_md_code(root['path'])} | {state} |\n"
        )

    lines.extend(["\n", "### Root authoritative-base attestations\n", "\n"])
    for root_id in decision["root_ids"]:
        lines.append(
            base_attestation_line(
                root_id, contract["roots"][root_id]["base_attestation"]
            )
        )

    lines.extend(
        [
            "\n",
            "## Complete target denominator\n",
            "\n",
            "Every target is listed separately. No mirror/adaptation row is silently deduplicated.\n",
            "\n",
            "| Target | Root/path | Entry | Operation/mode | Content dimensions/relationship | Base | Proposed target | Presented state |\n",
            "|---|---|---|---|---|---|---|---|\n",
        ]
    )
    for target_id in decision["target_ids"]:
        target = contract["targets"][target_id]
        observed_target = lock["targets"][target_id]
        relation = target["relationship"]["kind"]
        if target["relationship"].get("group"):
            relation += f":{target['relationship']['group']}"
        path = target["path"]
        if target.get("old_path"):
            path = f"{target['old_path']} → {path}"
        root_path = f"{target['root']}:{path}"
        observed_modes = (
            f"{observed_target['base_mode']}→{observed_target['target_mode']}"
        )
        dimensions = (
            f"{target['representation_kind']}/{target['provenance_kind']}/"
            f"{target['confidentiality_kind']}"
        )
        lines.append(
            f"| {_md_code(target_id)} | {_md_code(root_path)} | {_md_code(target['entry'])} | "
            f"{_md_code(target['operation'])} {_md_code(observed_modes)} | "
            f"{_md_code(dimensions)} / {_md_code(relation)} | {_md_code(_id_short(observed_target['base']))} | "
            f"{_md_code(_id_short(observed_target['target']))} | {_md_code(observed_target['freshness'])} |\n"
        )

    lines.extend(["\n", "### Target authoritative-base attestations\n", "\n"])
    for target_id in decision["target_ids"]:
        lines.append(
            base_attestation_line(
                target_id, contract["targets"][target_id]["base_attestation"]
            )
        )

    lines.extend(["\n", "## Full review artifacts\n", "\n", "These files are mechanically generated and never ellipsized. Literal `...`/`…` from source content is preserved. Every link is identity-bound and must reopen unchanged at each phase.\n", "\n"])
    for root_id, artifact in lock["artifacts"]["review_patches"].items():
        lines.append(
            f"- {_md_code(root_id)} raw review patch: [open the complete patch]({_md_path(artifact['path'])}) — "
            f"SHA-256 `{artifact['sha256']}`, {artifact['bytes']} bytes, {artifact['lines']} lines, {artifact['hunks']} hunks.\n"
        )
    for root_id, candidate in lock["candidates"].items():
        artifact = candidate["patch"]
        lines.append(
            f"- {_md_code(root_id)} exact Git candidate patch (binary/full-index): [open the complete patch]({_md_path(artifact['path'])}) — "
            f"SHA-256 `{artifact['sha256']}`, {artifact['bytes']} bytes; candidate tree `{candidate['candidate_tree']}`.\n"
        )

    lines.extend(["\n", "## Binary, generated, and sensitive evidence\n", "\n"])
    special = False
    for target_id in decision["target_ids"]:
        target = contract["targets"][target_id]
        observed_target = lock["targets"][target_id]
        representation_kind = target["representation_kind"]
        provenance_kind = target["provenance_kind"]
        confidentiality_kind = target["confidentiality_kind"]
        if representation_kind == "binary":
            special = True
            representation = target["content"]["representation"]
            inspector = representation["inspector"]
            exact_access = (
                f"frozen exact artifact [open]({_md_path(observed_target['target_frozen'])})"
                if observed_target["target_frozen"]
                else f"owner exact access: {_md_code(representation['owner_access'])}"
            )
            lines.append(
                f"- {_md_code(target_id)} binary exact source {_md_code(target['target_source'])}; {exact_access}; "
                f"identity {_md_code(_id_short(observed_target['target']))}. "
                f"Inspector {_md_code(inspector['tool'])} scope: {_md_code(inspector['scope'])}; "
                f"limitations: {_md_code(inspector['limitations'])}; result: {_md_code(inspector['result_locator'])}. "
                "Inspector adequacy remains owner judgment.\n"
            )
        if provenance_kind == "generated":
            special = True
            group = lock["generated_groups"][target["content"]["provenance"]["group"]]
            if group["determinism"] == "MATCH":
                determinism = "two distinct supplied captures match across complete exact inventories"
            else:
                determinism = (
                    f"determinism NOT PROMISED ({_md_code(group['determinism_reason'])})"
                )
            lines.append(
                f"- {_md_code(target_id)} generated by {_md_code(group['generator'])} ({_md_code(group['command_display'])}); "
                f"{determinism}; exact target {_md_code(_id_short(observed_target['target']))}. "
                "The helper does not execute the generator and therefore claims only supplied-capture equality, not causal reproduction.\n"
            )
        if confidentiality_kind == "sensitive":
            special = True
            confidentiality = target["content"]["confidentiality"]
            lines.append(
                f"- {_md_code(target_id)} sensitive exact access: {_md_code(confidentiality['owner_access'])}; binding `HMAC-SHA-256` "
                f"with separately held key {_md_code(confidentiality['key_ref'])}; base {_md_code(_id_short(observed_target['base']))}; "
                f"target {_md_code(_id_short(observed_target['target']))}. "
                "Raw bytes, raw digest, and byte length are not persisted in this packet.\n"
            )
    if not special:
        lines.append("- No binary, generated, or sensitive targets in this packet.\n")
    for group_id, group in lock["generated_groups"].items():
        if group["determinism"] == "MATCH":
            det_note = "two distinct supplied captures match across complete exact inventories"
        else:
            det_note = (
                f"determinism not promised: {_md_code(group['determinism_reason'])}"
            )
        lines.append(
            f"- Generated group {_md_code(group_id)} tool versions: "
            f"{', '.join(_md_code(value) for value in group['tool_versions'])}; "
            f"outputs: {', '.join(_md_code(value) for value in group['outputs'])}; {det_note}. "
            "The helper does not execute the generator and makes no causal reproduction claim.\n"
        )
        generator_source = group["generator_source"]
        lines.append(
            f"  - Generator source {_md_code(generator_source['path'])}; classification "
            f"{_md_code(content_dimensions(generator_source['content']))}; mode "
            f"{_md_code(generator_source['mode'])}; identity {_md_code(_id_short(generator_source['identity']))}.\n"
        )
        for input_index, artifact in enumerate(group["inputs"]):
            lines.append(
                f"  - Generator input {_md_code(input_index)} path {_md_code(artifact['path'])}; classification "
                f"{_md_code(content_dimensions(artifact['content']))}; mode {_md_code(artifact['mode'])}; "
                f"identity {_md_code(_id_short(artifact['identity']))}.\n"
            )
        for run_name, capture in sorted(group["captures"].items()):
            directory_identity = json.dumps(
                capture["directory_identity"], sort_keys=True, separators=(",", ":")
            )
            lines.append(
                f"  - Capture {_md_code(run_name)} path {_md_code(capture['path'])}; physical directory identity "
                f"{_md_code(directory_identity)}; complete exact inventory:\n"
            )
            for relative, entry in sorted(capture["inventory"].items()):
                if entry["type"] == "directory":
                    physical = json.dumps(
                        entry["physical"], sort_keys=True, separators=(",", ":")
                    )
                    lines.append(
                        f"    - {_md_code(relative)} directory; physical identity {_md_code(physical)}.\n"
                    )
                else:
                    lines.append(
                        f"    - {_md_code(relative)} file; mode {_md_code(entry['mode'])}; mode observable "
                        f"{_md_code(str(entry['mode_observable']).lower())}; identity "
                        f"{_md_code(_id_short(entry['identity']))}.\n"
                    )

    for group_id, group in lock["exact_mirror_groups"].items():
        members = ", ".join(_md_code(member) for member in group["members"])
        old_path = (
            f"; old path {_md_code(group['old_path'])}"
            if group.get("old_path") is not None
            else ""
        )
        modes = f"{group['base_mode']}→{group['target_mode']}"
        classification = (
            f"{group['representation']}/{group['provenance']}/"
            f"{group['confidentiality']}"
        )
        lines.append(
            f"- Exact-mirror group {_md_code(group_id)} members: {members}; path {_md_code(group['path'])}{old_path}; "
            f"operation {_md_code(group['operation'])}; modes {_md_code(modes)}; "
            f"classification {_md_code(classification)}; "
            f"base parity {_md_code(_id_short(group['base_parity']))}; target parity "
            f"{_md_code(_id_short(group['target_parity']))}.\n"
        )

    lines.extend(["\n", "## Staged / unstaged / untracked residue and exclusions\n", "\n"])
    if not contract["residue"]:
        lines.append("No out-of-transaction Git residue was present at build time.\n")
    else:
        lines.extend(["| Root/path | State layers | Disposition | Reason |\n", "|---|---|---|---|\n"])
        for row in contract["residue"]:
            residue_locator = f"{row['root']}:{row['path']}"
            lines.append(
                f"| {_md_code(residue_locator)} | {_md_code(','.join(row['states']))} | "
                f"{_md_code(row['disposition'])} | {_md_code(row['reason'])} |\n"
            )

    lines.extend(["\n", "## Exact Git commit manifests\n", "\n"])
    if not lock["candidates"]:
        lines.append("No Git commit is part of the declared decision.\n")
    for root_id, candidate in lock["candidates"].items():
        lines.append(
            f"### {_md_code(root_id)}\n\nExpected parent {_md_code(candidate['base_revision'])}; "
            f"candidate tree {_md_code(candidate['candidate_tree'])}; exact changed path set: "
            f"{', '.join(_md_code(path) for path in candidate['changed_paths'])}.\n\n"
        )
        lines.append("| Target/path | Operation | Mode | Candidate blob | Raw vs committed bytes |\n|---|---|---|---|---|\n")
        for entry in candidate["entries"]:
            changed = entry.get("filter_changed_bytes", False)
            target_path = f"{entry['target']}:{entry['path']}"
            lines.append(
                f"| {_md_code(target_path)} | {_md_code(entry['operation'])} | {_md_code(entry['mode'])} | "
                f"{_md_code(entry['blob_oid'])} | {_md_code('DIFFER' if changed else 'MATCH')} |\n"
            )

    lines.extend(
        [
            "\n",
            "## Decision protocol\n",
            "\n",
            f"Approve or reject **packet `{lock['packet_id']}`** only after opening every applicable full artifact above. "
            "Any base, target, artifact, helper, repository HEAD/index/residue, mirror/adaptation, or evidence change invalidates the decision. "
            "Rejection permanently blocks apply/adopt/commit for this packet.\n",
        ]
    )
    return "".join(lines)


def _safe_build_output(spec: dict[str, Any], out: Path) -> Path:
    candidate = _absolute_create_path(out, "build --out")
    for root in spec["_roots"].values():
        if _within(candidate, root["_path"]):
            raise SanctionError(
                f"packet output must be outside every declared root: {candidate} is under {root['_path']}"
            )
    for group_id, group in spec["_groups"].items():
        for run_name in ("_run_a", "_run_b"):
            capture = group.get(run_name)
            if capture is not None and _within(candidate, capture):
                raise SanctionError(
                    f"build --out must be outside generated group {group_id} {run_name[1:]} capture: {candidate}"
                )
    return candidate


def build_packet(spec_path: Path, out: Path, key_path: str | None) -> dict[str, Any]:
    raw = _json_load(spec_path, "manifest")
    snapshot = json.loads(json.dumps(raw))
    spec = _validate_manifest(raw)
    key = _key(key_path, spec["_sensitive"])
    out = _safe_build_output(spec, out)
    nonce = secrets.token_hex(32)
    roots_obs = _observe_roots(spec)
    _validate_git_index_baseline(spec, roots_obs)
    _validate_residue(spec, roots_obs)
    material = _capture_target_material(spec)
    mirror_obs = _observe_exact_mirrors(spec, material, key, nonce)
    generated_obs = _observe_generated(spec, material, key, nonce)

    out = _create_physical_directory_exclusive(out, "packet output directory")
    spec_copy = out / "spec.json"
    _json_write(spec_copy, snapshot)
    target_obs = _observe_targets(spec, material, out, key, nonce)

    review_patches: dict[str, Any] = {}
    candidates: dict[str, Any] = {}
    for root_id in spec["decision"]["root_ids"]:
        review = _review_patch_for_root(spec, target_obs, root_id, out)
        if review is not None:
            review_patches[root_id] = review
        candidate = _candidate_for_root(spec, roots_obs, target_obs, root_id, out)
        if candidate is not None:
            candidates[root_id] = candidate

    helper_identity = {"path": str(_helper_path()), "sha256": _helper_sha()}
    manifest_identity = {
        "path": str(spec_copy.resolve()),
        "sha256": _sha(_read(spec_copy, "frozen manifest")),
    }
    lock: dict[str, Any] = {
        "schema": SCHEMA,
        "version": VERSION,
        "claim": CLAIM,
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "machine": platform.node() or "unknown",
        "helper": helper_identity,
        "nonce": nonce,
        "manifest": manifest_identity,
        "key_confirmation": (
            _packet_key_confirmation(
                key,
                nonce=nonce,
                helper_sha256=helper_identity["sha256"],
                manifest_sha256=manifest_identity["sha256"],
            )
            if spec["_sensitive"] and key is not None
            else None
        ),
        "manifest_contract": spec["_manifest_contract"],
        "decision": spec["_manifest_contract"]["decision"],
        "denominator_attestation": spec["_manifest_contract"][
            "denominator_attestation"
        ],
        "roots": roots_obs,
        "targets": target_obs,
        "residue": spec["_manifest_contract"]["residue"],
        "exact_mirror_groups": mirror_obs,
        "generated_groups": generated_obs,
        "candidates": candidates,
        "artifacts": {"review_patches": review_patches},
    }
    lock["packet_id"] = _sha(_canonical(_packet_id_payload(lock)))
    packet_path = out / "packet.md"
    _write_text(packet_path, _render_packet(spec, lock))
    lock["packet_artifact"] = _artifact(packet_path)
    lock_path = out / "packet.lock.json"
    _json_write(lock_path, lock)
    checked_lock, checked_spec = _load_lock(lock_path)
    _validate_packet_key(checked_lock, checked_spec, key)
    _verify_phase(
        lock_path,
        checked_lock,
        checked_spec,
        "pre-decision",
        key,
        commits=None,
        semantic_review=None,
        write_receipt=False,
    )
    print(f"READY FOR OWNER DECISION {lock['packet_id']} {lock_path}")
    return lock


def _verify_file_artifact(artifact: dict[str, Any], label: str) -> None:
    path = Path(_nonempty(artifact.get("path"), f"{label}.path"))
    data = _read(path, label)
    if _sha(data) != artifact.get("sha256") or len(data) != artifact.get("bytes"):
        raise SanctionError(f"{label} changed or was replaced: {path}")
    lines = data.count(b"\n") + (1 if data and not data.endswith(b"\n") else 0)
    hunks = sum(1 for line in data.splitlines() if line.startswith(b"@@ "))
    if lines != artifact.get("lines") or hunks != artifact.get("hunks"):
        raise SanctionError(f"{label} structure changed: {path}")


# Exact keysets for locked observation rows: _observe_roots / _observe_targets
# always emit precisely these fields, so a locked row is validated against the
# full set in both directions (missing AND unknown fields reject).
_ROOT_LOCK_PLAIN_FIELDS = {
    "id", "kind", "path", "base_revision", "base_attestation", "physical",
}
_ROOT_LOCK_GIT_FIELDS = _ROOT_LOCK_PLAIN_FIELDS | {
    "head", "branch", "git_dir", "object_dir", "status", "index",
}
_TARGET_LOCK_FIELDS = {
    "id", "root", "path", "old_path", "entry", "operation",
    "representation_kind", "provenance_kind", "confidentiality_kind",
    "commit", "relationship", "base_attestation", "base", "target",
    "base_mode", "target_mode", "base_frozen", "target_frozen",
    "base_source", "target_source", "declared_target_mode", "current",
    "content", "freshness",
}


def _load_lock(path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    lock = _expect_object(_json_load(path, "packet lock"), "packet lock")
    required = {
        "schema", "version", "claim", "created_at", "machine", "helper", "nonce",
        "manifest", "manifest_contract", "key_confirmation", "decision", "denominator_attestation", "roots", "targets", "residue",
        "exact_mirror_groups", "generated_groups",
        "candidates", "artifacts", "packet_id", "packet_artifact",
    }
    _keys(lock, required, required, "packet lock")
    if lock["schema"] != SCHEMA or lock["claim"] != CLAIM:
        raise SanctionError("packet lock schema/claim mismatch")
    helper = _expect_object(lock["helper"], "packet lock.helper")
    if helper.get("sha256") != _helper_sha():
        raise SanctionError("helper bytes changed since packet build; rebuild and re-present")
    expected_id = _sha(_canonical(_packet_id_payload(lock)))
    if not hmac.compare_digest(str(lock["packet_id"]), expected_id):
        raise SanctionError("packet lock content does not match packet_id")
    manifest = _expect_object(lock["manifest"], "packet lock.manifest")
    manifest_path = Path(_nonempty(manifest.get("path"), "packet lock.manifest.path"))
    manifest_bytes = _read(manifest_path, "frozen manifest")
    if _sha(manifest_bytes) != manifest.get("sha256"):
        raise SanctionError("frozen manifest changed after packet build")
    spec = _validate_manifest(json.loads(manifest_bytes.decode("utf-8")))
    expected_contract = spec["_manifest_contract"]
    locked_contract = _expect_object(
        lock["manifest_contract"], "packet lock.manifest_contract"
    )
    if locked_contract != expected_contract:
        raise SanctionError(
            "lock manifest contract differs from the validated frozen manifest"
        )
    if expected_contract["decision"] != lock["decision"]:
        raise SanctionError("lock decision denominator differs from frozen manifest")
    if expected_contract["denominator_attestation"] != lock["denominator_attestation"]:
        raise SanctionError(
            "lock denominator_attestation differs from the validated frozen manifest"
        )
    if expected_contract["residue"] != lock["residue"]:
        raise SanctionError(
            "lock residue differs from the validated frozen manifest"
        )
    locked_roots = _expect_object(lock["roots"], "packet lock.roots")
    if set(locked_roots) != set(expected_contract["roots"]):
        raise SanctionError("lock root keyset differs from the frozen manifest")
    for root_id in spec["decision"]["root_ids"]:
        locked_root = _expect_object(
            locked_roots.get(root_id), f"packet lock.roots.{root_id}"
        )
        root_row_fields = (
            _ROOT_LOCK_GIT_FIELDS
            if locked_root.get("kind") == "git"
            else _ROOT_LOCK_PLAIN_FIELDS
        )
        _keys(
            locked_root,
            root_row_fields,
            root_row_fields,
            f"packet lock.roots.{root_id} observation",
        )
        root_contract = expected_contract["roots"][root_id]
        if locked_root.get("base_attestation") != root_contract[
            "base_attestation"
        ]:
            raise SanctionError(
                f"lock root {root_id} base_attestation differs from the validated frozen manifest"
            )
        locked_projection = {
            field: locked_root.get(field) for field in root_contract
        }
        if locked_projection != root_contract:
            raise SanctionError(
                f"lock root {root_id} authored semantics differ from the validated frozen manifest"
            )
    locked_targets = _expect_object(lock["targets"], "packet lock.targets")
    if set(locked_targets) != set(expected_contract["targets"]):
        raise SanctionError("lock target keyset differs from the frozen manifest")
    for target_id in spec["decision"]["target_ids"]:
        locked_target = _expect_object(
            locked_targets.get(target_id), f"packet lock.targets.{target_id}"
        )
        _keys(
            locked_target,
            _TARGET_LOCK_FIELDS,
            _TARGET_LOCK_FIELDS,
            f"packet lock.targets.{target_id} observation",
        )
        target_contract = expected_contract["targets"][target_id]
        if locked_target.get("base_attestation") != target_contract[
            "base_attestation"
        ]:
            raise SanctionError(
                f"lock target {target_id} base_attestation differs from the validated frozen manifest"
            )
        locked_projection = {
            field: locked_target.get(field) for field in target_contract
        }
        if locked_projection != target_contract:
            raise SanctionError(
                f"lock target {target_id} authored semantics differ from the validated frozen manifest"
            )
    if spec["_sensitive"]:
        confirmation = _expect_object(lock["key_confirmation"], "packet key confirmation")
        confirmation_fields = {"algorithm", "value", "bytes"}
        _keys(
            confirmation,
            confirmation_fields,
            confirmation_fields,
            "packet key confirmation",
        )
        if (
            confirmation["algorithm"] != "hmac-sha256"
            or confirmation["bytes"] != "withheld"
        ):
            raise SanctionError("sensitive packet key confirmation schema mismatch")
        _nonempty(confirmation["value"], "packet key confirmation.value")
    elif lock["key_confirmation"] is not None:
        raise SanctionError("non-sensitive packet must not contain a key confirmation")

    _verify_file_artifact(lock["packet_artifact"], "rendered packet")
    packet_path = Path(_nonempty(lock["packet_artifact"].get("path"), "rendered packet.path"))
    expected_packet = _render_packet(spec, lock).encode("utf-8")
    if _read(packet_path, "rendered packet") != expected_packet:
        raise SanctionError("rendered packet does not match the packet-id-bound canonical rendering")
    for root_id, artifact in _expect_object(lock["artifacts"], "lock.artifacts").get("review_patches", {}).items():
        _verify_file_artifact(artifact, f"review patch {root_id}")
    for root_id, candidate in _expect_object(lock["candidates"], "lock.candidates").items():
        _verify_file_artifact(candidate["patch"], f"commit patch {root_id}")
        scratch_root = Path(_nonempty(candidate.get("scratch_root"), f"candidate {root_id}.scratch_root"))
        scratch_inventory = _expect_object(
            candidate.get("scratch_inventory"), f"candidate {root_id}.scratch_inventory"
        )
        if _inventory(scratch_root) != scratch_inventory:
            raise SanctionError(f"candidate scratch inventory changed for {root_id}")
        for entry in candidate["entries"]:
            artifact_path = entry.get("committed_artifact")
            if artifact_path:
                data = _read(Path(artifact_path), f"committed candidate {entry['target']}")
                if _identity(data) != entry.get("committed_identity"):
                    raise SanctionError(f"committed candidate artifact changed for {entry['target']}")
    for target_id, target in _expect_object(lock["targets"], "lock.targets").items():
        for role in ("base", "target"):
            frozen = target.get(f"{role}_frozen")
            if frozen:
                data = _read(Path(frozen), f"frozen {role} for {target_id}")
                if _identity(data) != target[role]:
                    raise SanctionError(f"frozen {role} artifact changed for {target_id}")
    return lock, spec


def _decision_path(lock_path: Path) -> Path:
    return _lexical_absolute(lock_path, "packet lock").parent / "decision.json"


def _decision_scope(spec: dict[str, Any]) -> dict[str, list[str]]:
    decision = spec["decision"]
    return {
        "actions": list(decision["actions"]),
        "root_ids": list(decision["root_ids"]),
        "target_ids": list(decision["target_ids"]),
    }


def _record_classification(spec: dict[str, Any]) -> str:
    return "sensitive" if spec["_sensitive"] else "non-sensitive"


def _load_decision(
    lock_path: Path,
    lock: dict[str, Any],
    spec: dict[str, Any],
    key: bytes | None,
    *,
    required: bool,
) -> dict[str, Any] | None:
    _validate_packet_key(lock, spec, key)
    path = _decision_path(lock_path)
    if not _physical_validate(path, "decision record", "file", allow_missing=True):
        if required:
            raise SanctionError("owner decision is missing; packet is not approved")
        return None
    decision = _expect_object(_json_load(path, "decision record"), "decision record")
    fields = {
        "schema", "packet_id", "helper_sha256", "nonce", "verdict", "locator",
        "scope", "evidence", "recorded_at", "warning", "record_binding",
    }
    _keys(decision, fields, fields, "decision record")

    scope = _expect_object(decision["scope"], "decision.scope")
    scope_fields = {"actions", "root_ids", "target_ids"}
    _keys(scope, scope_fields, scope_fields, "decision.scope")
    evidence = _expect_object(decision["evidence"], "decision.evidence")
    evidence_fields = {"path", "classification", "binding"}
    _keys(evidence, evidence_fields, evidence_fields, "decision.evidence")

    # Bind the complete stored record before interpreting its verdict or using
    # its evidence locator. A same-byte locator substitution is still a record
    # mutation and must fail here, not be normalized away by the evidence hash.
    record_payload = {k: v for k, v in decision.items() if k != "record_binding"}
    record_expected = _decision_binding(
        _canonical(record_payload),
        lock=lock,
        classification=_record_classification(spec),
        key=key,
        purpose="record",
    )
    _validate_decision_binding(
        decision["record_binding"], record_expected, "decision record binding"
    )

    if decision["schema"] != DECISION_SCHEMA or decision["packet_id"] != lock["packet_id"]:
        raise SanctionError("decision record is bound to a different packet")
    if decision["helper_sha256"] != lock["helper"]["sha256"] or decision["nonce"] != lock["nonce"]:
        raise SanctionError("decision helper/nonce binding mismatch")
    expected_locator = spec["decision"]["gate"]["locator"]
    if decision["locator"] != expected_locator:
        raise SanctionError("decision locator differs from the packet-bound gate locator")
    if scope != _decision_scope(spec):
        raise SanctionError("decision scope differs from the packet-bound actions/roots/targets")

    evidence_classification = spec["decision"]["evidence_classification"]
    if evidence["classification"] != evidence_classification:
        raise SanctionError("decision evidence classification differs from the packet-bound policy")
    expected_warning = _decision_warning(_record_classification(spec))
    if decision["warning"] != expected_warning:
        raise SanctionError("decision warning differs from the packet-bound threat statement")
    _nonempty(decision["recorded_at"], "decision.recorded_at")

    evidence_path = _absolute(evidence["path"], "decision.evidence.path")
    evidence_bytes = _read(evidence_path, "owner-decision evidence")
    evidence_expected = _decision_binding(
        evidence_bytes,
        lock=lock,
        classification=evidence_classification,
        key=key,
        purpose="evidence",
    )
    _validate_decision_binding(
        evidence["binding"], evidence_expected, "decision evidence binding"
    )

    verdict = _choice(decision["verdict"], {"approved", "rejected"}, "decision.verdict")
    if required and verdict != "approved":
        raise SanctionError("packet was rejected; apply/adopt/commit is permanently blocked")
    return decision


# --- Task 7: ordered, one-use lifecycle -----------------------------------
#
# The helper has no overwrite primitive: every write is create-exclusive
# (_write_bytes -> _posix_write_new O_EXCL / _win_write_new _CREATE_NEW).  A
# mutable "current state" file is therefore not implementable without punching a
# hole in that property, so the lifecycle state IS the append-only chain of
# verify-<phase>.json receipts.  Their existence set determines the permitted
# next phase, and the exclusive create is both the atomic advance and the
# one-use gate.


def _lifecycle_dir(lock_path: Path) -> Path:
    return _lexical_absolute(lock_path, "packet lock").parent


def _lifecycle_receipt_path(lock_path: Path, phase: str) -> Path:
    return _lifecycle_dir(lock_path) / f"verify-{phase}.json"


def _invalidation_path(lock_path: Path) -> Path:
    return _lifecycle_dir(lock_path) / "invalidated.json"


def _entry_composition(spec: dict[str, Any]) -> str:
    """Derive the packet's entry composition from its *decision* target set.

    Scoped to spec["decision"]["target_ids"] — the same set _current_matches and
    write_partial_receipt use — so a non-decision target cannot change the
    required transition sequence.  spec comes from the frozen spec.json whose
    sha256 is re-verified on every _load_lock, so this cannot drift under a
    valid lock.
    """
    entries = {
        spec["_targets"][target_id]["_entry"]
        for target_id in spec["decision"]["target_ids"]
    }
    if not entries:
        raise SanctionError("decision target set is empty; entry composition is undefined")
    if entries == {"pre-apply"}:
        return "all-pre-apply"
    if entries == {"already-applied"}:
        return "all-already-applied"
    return "mixed"


def _lifecycle_sequence(lock: dict[str, Any], spec: dict[str, Any]) -> tuple[str, ...]:
    live = _LIVE_SEQUENCE[_entry_composition(spec)]
    return live + (_COMMIT_SEQUENCE if lock["candidates"] else ())


def _lifecycle_binding(
    payload: dict[str, Any],
    *,
    lock: dict[str, Any],
    spec: dict[str, Any],
    key: bytes | None,
    purpose: str,
) -> dict[str, Any]:
    return _decision_binding(
        _canonical(payload),
        lock=lock,
        classification=_record_classification(spec),
        key=key,
        purpose=purpose,
    )


def _check_not_invalidated(
    lock_path: Path,
    lock: dict[str, Any],
    spec: dict[str, Any],
    key: bytes | None,
) -> None:
    path = _invalidation_path(lock_path)
    if not _physical_validate(path, "packet invalidation record", "file", allow_missing=True):
        return
    record = _expect_object(_json_load(path, "packet invalidation record"), "packet invalidation record")
    fields = {
        "schema", "packet_id", "helper_sha256", "nonce", "phase", "reason",
        "invalidated_at", "record_binding",
    }
    _keys(record, fields, fields, "packet invalidation record")
    payload = {k: v for k, v in record.items() if k != "record_binding"}
    _validate_decision_binding(
        record["record_binding"],
        _lifecycle_binding(payload, lock=lock, spec=spec, key=key, purpose="invalidation"),
        "packet invalidation record binding",
    )
    if record["schema"] != INVALIDATION_SCHEMA or record["packet_id"] != lock["packet_id"]:
        raise SanctionError("packet invalidation record is bound to a different packet")
    if record["helper_sha256"] != lock["helper"]["sha256"] or record["nonce"] != lock["nonce"]:
        raise SanctionError("packet invalidation helper/nonce binding mismatch")
    raise SanctionError(
        f"packet was invalidated by drift at {record['phase']} "
        f"({record['reason']}); rebuild and re-present rather than resuming"
    )


def _record_invalidation(
    lock_path: Path,
    lock: dict[str, Any],
    spec: dict[str, Any],
    key: bytes | None,
    phase: str,
    reason: str,
) -> None:
    """Persist a sticky drift invalidation.

    Best-effort by construction: if the record already exists the packet is
    already dead, and a write failure must never mask the drift error being
    raised through this call.
    """
    payload = {
        "schema": INVALIDATION_SCHEMA,
        "packet_id": lock["packet_id"],
        "helper_sha256": lock["helper"]["sha256"],
        "nonce": lock["nonce"],
        "phase": phase,
        "reason": reason,
        "invalidated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
    }
    record = dict(payload)
    record["record_binding"] = _lifecycle_binding(
        payload, lock=lock, spec=spec, key=key, purpose="invalidation"
    )
    try:
        _json_write(_invalidation_path(lock_path), record)
    except (SanctionError, OSError):
        return


def _load_lifecycle_receipt(
    path: Path,
    member: str,
    lock: dict[str, Any],
    spec: dict[str, Any],
    key: bytes | None,
    composition: str,
    sequence: tuple[str, ...],
    decision_record: dict[str, Any],
) -> dict[str, Any]:
    receipt = _expect_object(
        _json_load(path, f"lifecycle receipt {member}"), f"lifecycle receipt {member}"
    )
    required = {
        "schema", "packet_id", "helper_sha256", "nonce", "entry_composition",
        "sequence", "phase", "predecessor", "terminal",
        "decision_record_binding", "verified_at", "receipt_binding",
    }
    allowed = required | {"semantic_review", "commits"}
    _keys(receipt, required, allowed, f"lifecycle receipt {member}")

    # Bind the complete stored receipt before interpreting any field, mirroring
    # the _load_decision discipline: a same-byte substitution must fail here.
    payload = {k: v for k, v in receipt.items() if k != "receipt_binding"}
    _validate_decision_binding(
        receipt["receipt_binding"],
        _lifecycle_binding(payload, lock=lock, spec=spec, key=key, purpose="lifecycle"),
        f"lifecycle receipt {member} binding",
    )

    if receipt["schema"] != LIFECYCLE_SCHEMA or receipt["packet_id"] != lock["packet_id"]:
        raise SanctionError("lifecycle receipt is bound to a different packet")
    if receipt["helper_sha256"] != lock["helper"]["sha256"] or receipt["nonce"] != lock["nonce"]:
        raise SanctionError("lifecycle receipt helper/nonce binding mismatch")
    if receipt["phase"] != member:
        raise SanctionError(
            f"lifecycle receipt filename does not match its recorded phase: {receipt['phase']} != {member}"
        )
    if receipt["entry_composition"] != composition or tuple(receipt["sequence"]) != sequence:
        raise SanctionError(
            f"lifecycle receipt {member} was recorded under a different entry composition"
        )
    if receipt["decision_record_binding"] != decision_record["record_binding"]:
        raise SanctionError(f"lifecycle receipt {member} is bound to a different owner decision")
    return receipt


def _lifecycle_gate(
    lock_path: Path,
    lock: dict[str, Any],
    spec: dict[str, Any],
    key: bytes | None,
    decision_record: dict[str, Any] | None,
    phase: str,
) -> tuple[str | None, tuple[str, ...] | None, dict[str, Any] | None, bool]:
    """Return (composition, sequence, predecessor, has_chain) for a permitted phase.

    Raises unless `phase` is exactly the packet's only permitted next phase.
    Deliberately runs before any evidence capture so an ordering violation
    fails with an ordering message rather than a masking state message.

    `has_chain` reports whether any lifecycle state exists yet.  Drift only
    invalidates a packet that has state to resume: with an empty chain there is
    no "old state" to resume past, and writing an invalidation record anyway
    would contaminate the packet directory for every later independent probe.
    """
    if phase == PHASE_PRE_DECISION:
        return None, None, None, False
    assert decision_record is not None  # required=True for every chain member

    composition = _entry_composition(spec)
    sequence = _lifecycle_sequence(lock, spec)
    directory = _lifecycle_dir(lock_path)

    if phase not in sequence:
        raise SanctionError(
            f"phase {phase} is not part of this packet's transition sequence "
            f"({composition}, git_commit_candidates={sorted(lock['candidates'])}): "
            f"{list(sequence)}"
        )

    # A verify-*.json that is not a member of this packet's sequence is either
    # litter or a transplanted receipt; neither may be silently ignored.
    known = {f"verify-{member}.json" for member in ALL_PHASES}
    in_sequence = {f"verify-{member}.json" for member in sequence}
    for found in sorted(directory.glob("verify-*.json")):
        if found.name not in known:
            raise SanctionError(f"unrecognized lifecycle receipt in the packet directory: {found}")
        if found.name not in in_sequence and found.name != f"verify-{PHASE_PRE_DECISION}.json":
            raise SanctionError(
                f"lifecycle receipt {found.name} is not part of this packet's "
                f"transition sequence ({composition}): {list(sequence)}"
            )

    # Walk the contiguous chain frontier.
    chain: list[dict[str, Any]] = []
    for member in sequence:
        path = _lifecycle_receipt_path(lock_path, member)
        if not _physical_validate(path, f"lifecycle receipt {member}", "file", allow_missing=True):
            break
        chain.append(
            _load_lifecycle_receipt(
                path, member, lock, spec, key, composition, sequence, decision_record
            )
        )

    # No receipt may exist beyond the contiguous frontier: a gap plus a later
    # receipt is a branching history, not a resumable chain.
    for later in sequence[len(chain):]:
        if _physical_validate(
            _lifecycle_receipt_path(lock_path, later), f"lifecycle receipt {later}", "file", allow_missing=True
        ):
            raise SanctionError(
                f"branching lifecycle history: {later} receipt exists but "
                f"{sequence[len(chain)]} did not run"
            )

    # Predecessor chaining: decision record -> first phase -> ... -> frontier.
    expected_predecessor = decision_record["record_binding"]["value"]
    for index, receipt in enumerate(chain):
        if receipt["predecessor"]["binding_value"] != expected_predecessor:
            raise SanctionError(
                f"lifecycle receipt {sequence[index]} does not chain to its predecessor"
            )
        expected_predecessor = receipt["receipt_binding"]["value"]

    if len(chain) == len(sequence):
        raise SanctionError(
            f"lifecycle is already complete at {sequence[-1]}; rebuild and re-present"
        )
    permitted = sequence[len(chain)]
    if phase != permitted:
        if phase in sequence[: len(chain)]:
            raise SanctionError(f"phase {phase} was already consumed; replay is refused")
        raise SanctionError(
            f"out-of-order phase {phase}; the only permitted next phase is {permitted}"
        )

    if not chain:
        predecessor = {
            "kind": "decision",
            "phase": None,
            "binding_value": decision_record["record_binding"]["value"],
        }
    else:
        predecessor = {
            "kind": "phase",
            "phase": sequence[len(chain) - 1],
            "binding_value": chain[-1]["receipt_binding"]["value"],
        }
    return composition, sequence, predecessor, bool(chain)


def record_decision(lock_path: Path, verdict: str, evidence_file: Path, key_path: str | None) -> dict[str, Any]:
    lock, spec = _load_lock(lock_path)
    key = _key(key_path, spec["_sensitive"])
    _validate_packet_key(lock, spec, key)
    path = _decision_path(lock_path)
    if _physical_validate(path, "decision record", None, allow_missing=True):
        raise SanctionError(f"decision already exists and cannot be overwritten: {path}")
    _verify_phase(lock_path, lock, spec, "pre-decision", key, commits=None, semantic_review=None, write_receipt=False)
    evidence_file = _absolute(str(evidence_file), "--evidence-file")
    evidence = _read(evidence_file, "owner-decision evidence")
    evidence_classification = spec["decision"]["evidence_classification"]
    record_classification = _record_classification(spec)
    record = {
        "schema": DECISION_SCHEMA,
        "packet_id": lock["packet_id"],
        "helper_sha256": lock["helper"]["sha256"],
        "nonce": lock["nonce"],
        "verdict": _choice(verdict, {"approved", "rejected"}, "--verdict"),
        "locator": spec["decision"]["gate"]["locator"],
        "scope": _decision_scope(spec),
        "evidence": {
            "path": str(evidence_file),
            "classification": evidence_classification,
            "binding": _decision_binding(
                evidence,
                lock=lock,
                classification=evidence_classification,
                key=key,
                purpose="evidence",
            ),
        },
        "recorded_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "warning": _decision_warning(record_classification),
    }
    record["record_binding"] = _decision_binding(
        _canonical(record),
        lock=lock,
        classification=record_classification,
        key=key,
        purpose="record",
    )
    _json_write(path, record)
    _load_decision(lock_path, lock, spec, key, required=False)
    print(f"DECISION {record['verdict'].upper()} {lock['packet_id']} {path}")
    return record


def _verify_source_identities(
    lock: dict[str, Any],
    spec: dict[str, Any],
    key: bytes | None,
    material: dict[str, dict[str, Any]],
) -> None:
    nonce = lock["nonce"]
    for target_id in spec["decision"]["target_ids"]:
        target = spec["_targets"][target_id]
        locked = lock["targets"][target_id]
        target_material = material[target_id]
        base_bytes = target_material["base_bytes"]
        base_mode = target_material["base_mode"]
        target_bytes = target_material["target_bytes"]
        target_mode = target_material["target_mode"]
        sensitive = target["_confidentiality_kind"] == "sensitive"
        if sensitive:
            assert key is not None
            base_id = {"algorithm": "absent"} if base_bytes is None else _hmac_identity(base_bytes, key, nonce, target_id, "base")
            target_id_value = {"algorithm": "absent"} if target_bytes is None else _hmac_identity(target_bytes, key, nonce, target_id, "target")
        else:
            base_id = {"algorithm": "absent"} if base_bytes is None else _identity(base_bytes)
            target_id_value = {"algorithm": "absent"} if target_bytes is None else _identity(target_bytes)
        if base_id != locked["base"] or target_id_value != locked["target"]:
            raise _DriftError(f"base or proposed target source changed for {target_id}; rebuild and re-present")
        if base_mode != locked["base_mode"] or target_mode != locked["target_mode"]:
            raise _DriftError(f"mode changed for {target_id}; rebuild and re-present")


def _verify_generated_evidence(
    locked: dict[str, Any],
    current: dict[str, Any],
) -> None:
    if set(current) != set(locked):
        raise _DriftError("generated group denominator changed after packet build")
    for group_id in sorted(locked):
        before = locked[group_id]
        now = current[group_id]
        if now.get("generator_source") != before.get("generator_source"):
            raise SanctionError(
                f"generated group {group_id} generator source identity changed after packet build"
            )
        if now.get("inputs") != before.get("inputs"):
            raise SanctionError(
                f"generated group {group_id} input identity changed after packet build"
            )
        before_captures = before.get("captures", {})
        now_captures = now.get("captures", {})
        if set(now_captures) != set(before_captures):
            raise SanctionError(f"generated group {group_id} capture denominator changed")
        for run_name in sorted(before_captures):
            before_run = before_captures[run_name]
            now_run = now_captures[run_name]
            if now_run.get("directory_identity") != before_run.get("directory_identity"):
                raise SanctionError(
                    f"generated group {group_id} {run_name} capture identity was replaced"
                )
            if now_run.get("inventory") != before_run.get("inventory"):
                raise SanctionError(
                    f"generated group {group_id} {run_name} exact inventory changed"
                )
        if now != before:
            raise SanctionError(
                f"generated group {group_id} evidence changed after packet build"
            )


def _current_matches(lock: dict[str, Any], spec: dict[str, Any], key: bytes | None, *, desired: str) -> None:
    for target_id in spec["decision"]["target_ids"]:
        target = spec["_targets"][target_id]
        locked = lock["targets"][target_id]
        current = _current_state(spec, target, key, lock["nonce"])
        probe = dict(locked)
        probe["current"] = current
        if desired == "entry":
            # The locked observation is only trustworthy at the entry phases if
            # it still matches a fresh rederivation; a rebound packet id cannot
            # launder a forged current observation or freshness verdict.
            if locked["current"] != current:
                raise SanctionError(
                    f"{target_id} locked current observation differs from the rederived live state"
                )
            state = _freshness_state(target, probe)
            if locked["freshness"] != state:
                raise SanctionError(
                    f"{target_id} locked freshness {locked['freshness']} differs from rederived {state}"
                )
            expected = "BASE" if target["_entry"] == "pre-apply" else "TARGET"
        else:
            original = target["_entry"]
            target["_entry"] = "already-applied"
            try:
                state = _freshness_state(target, probe)
            finally:
                target["_entry"] = original
            expected = "TARGET"
        if state != expected:
            raise _DriftError(f"{target_id} current destination is {state}, expected {expected}")


def _verify_root_identity(lock: dict[str, Any], current: dict[str, Any], *, require_base_head: bool) -> None:
    for root_id, locked in lock["roots"].items():
        now = current[root_id]
        if now["path"] != locked["path"] or now["physical"] != locked["physical"]:
            raise _DriftError(f"physical root identity changed for {root_id}")
        if locked["kind"] == "git":
            if require_base_head and now["head"] != locked["head"]:
                raise _DriftError(f"Git HEAD changed for {root_id}; packet is stale")
            if now["branch"] != locked["branch"]:
                raise _DriftError(f"Git branch changed for {root_id}; packet is stale")
            if now["git_dir"] != locked["git_dir"] or now["object_dir"] != locked["object_dir"]:
                raise _DriftError(f"Git directory identity changed for {root_id}; packet is stale")


def _index_state_for_paths(
    snapshot: dict[str, Any], paths: set[str]
) -> dict[str, list[dict[str, str]]]:
    return {
        "entries": sorted(
            (row for row in snapshot["entries"] if row["path"] in paths),
            key=lambda row: (row["path"], row["stage"], row["mode"], row["oid"]),
        ),
        "flags": sorted(
            (row for row in snapshot["flags"] if row["path"] in paths),
            key=lambda row: (row["path"], row["tag"]),
        ),
    }


def _verify_live_only_index_invariant(
    lock: dict[str, Any],
    spec: dict[str, Any],
    current_roots: dict[str, Any],
    root_id: str,
) -> None:
    paths: set[str] = set()
    for target in spec["_targets"].values():
        if target["root"] != root_id or target["commit"]:
            continue
        paths.add(target["path"])
        if target["_operation"] == "rename":
            paths.add(target["old_path"])
    if not paths:
        return
    locked = _index_state_for_paths(lock["roots"][root_id]["index"], paths)
    current = _index_state_for_paths(current_roots[root_id]["index"], paths)
    if current != locked:
        raise SanctionError(
            f"commit:false Git target index invariant changed in {root_id}: {sorted(paths)}"
        )


def _candidate_real_patch(spec: dict[str, Any], root_id: str, candidate: dict[str, Any]) -> bytes:
    root = spec["_roots"][root_id]["_path"]
    return _git(root, "diff", "--cached", "--binary", "--full-index", "--find-renames", candidate["base_revision"]).stdout


def _candidate_identity(lock: dict[str, Any]) -> dict[str, Any]:
    """The exact candidate root/path/blob/mode set a semantic review attests to.

    Derived from the LOCK alone, so the same value is reconstructible by the
    reviewer before the review and by the verifier after it, with no working-tree
    read in between.  `candidate_tree` is Git's own exact summary of the
    path/blob/mode set; `changed_paths` and `entries` make that summary
    reader-visible, which is the point -- an attestation whose subject the
    reviewer cannot read is not an attestation.

    Deletes carry mode/blob_oid "absent" (never a manufactured 100644/zero-oid),
    matching Task 1's rule that absence is recorded, not invented.
    """
    identity: dict[str, Any] = {}
    for root_id, candidate in lock["candidates"].items():
        identity[root_id] = {
            "base_revision": candidate["base_revision"],
            "candidate_tree": candidate["candidate_tree"],
            "changed_paths": sorted(candidate["changed_paths"]),
            "entries": sorted(
                (
                    {
                        "target": entry["target"],
                        "mode": entry["mode"],
                        "blob_oid": entry["blob_oid"],
                    }
                    for entry in candidate["entries"]
                ),
                key=lambda row: (row["target"], row["mode"], row["blob_oid"]),
            ),
        }
    return identity


def _semantic_evidence(path: Path | None, lock: dict[str, Any]) -> dict[str, Any]:
    if path is None:
        raise SanctionError("pre-commit/post-commit requires --semantic-review-file (staged-byte semantic review evidence)")
    path = _absolute(str(path), "--semantic-review-file")
    data = _read(path, "semantic staged-byte review evidence")
    if not data.strip():
        raise SanctionError("semantic staged-byte review evidence is empty")

    # Non-empty is NOT evidence.  Before Task 8 any one-byte file satisfied this
    # gate, so a pre-commit could claim a semantic review that named no artifact
    # at all -- and a review of a DIFFERENT packet passed identically.
    try:
        parsed = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SanctionError(
            "semantic staged-byte review evidence must be a "
            f"{SEMANTIC_SCHEMA} JSON attestation, not free text: {exc}"
        ) from exc
    attestation = _expect_object(parsed, "semantic review attestation")

    required = set(SEMANTIC_ATTESTATION_FIELDS)
    _keys(attestation, required, required, "semantic review attestation")

    if attestation["schema"] != SEMANTIC_SCHEMA:
        raise SanctionError(
            f"semantic review attestation schema must be {SEMANTIC_SCHEMA}, "
            f"got {attestation['schema']!r}"
        )

    # Bind to THIS packet.  packet_id is a digest over the whole lock payload
    # (see _packet_id_payload), so any candidate change -- path set, blob
    # identity, mode set -- yields a different packet_id and strands an
    # attestation written against the older candidate.  That is the mechanism
    # behind "evidence created before a candidate change must fail": it is
    # rejected because it names a packet that no longer exists, not because a
    # clock was compared.
    for field in ("packet_id", "nonce"):
        if attestation[field] != lock[field]:
            raise SanctionError(
                f"semantic review attestation {field} names a different packet: "
                f"expected {lock[field]!r}, got {attestation[field]!r}"
            )
    if attestation["helper_sha256"] != lock["helper"]["sha256"]:
        raise SanctionError(
            "semantic review attestation was written against a different helper build: "
            f"expected {lock['helper']['sha256']!r}, got {attestation['helper_sha256']!r}"
        )

    # Recompute rather than trust.  Equality here is what makes the attestation
    # about the exact staged path/blob/mode set instead of about a story.
    expected_identity = _candidate_identity(lock)
    if attestation["candidate_identity"] != expected_identity:
        raise SanctionError(
            "semantic review attestation does not match the sanctioned candidate identity set "
            "(root/path/blob/mode); the review names different bytes than the packet stages"
        )

    # Reuse this file's OWN validators for these shapes rather than hand-rolling
    # weaker ones. `reviewer` is the same {identity, role} selector shape as
    # `denominator_attestation.selected_by`, and _validate_selector already
    # enforces _single_line (rejecting Cc/Cf/Zl/Zp) and returns the NORMALIZED
    # value. The first cut of this function used _nonempty and discarded its
    # stripped return, so raw bytes -- including a U+202E bidi override, which
    # survives _json_write's ensure_ascii=False -- reached the receipt this
    # helper then binds. Two identities differing only by surrounding whitespace
    # also bound to two different receipts for one reviewer.
    reviewer = _validate_selector(
        attestation["reviewer"], "semantic review attestation.reviewer"
    )
    scope_reviewed = _single_line(
        attestation["scope_reviewed"], "semantic review attestation.scope_reviewed"
    )
    # An audit field that accepts "never" is not an audit field. The value is
    # descriptive -- freshness is enforced by packet_id identity, not by a clock
    # comparison -- but it is copied into the receipt an owner reads, so it must
    # at least BE a timestamp. Parsed, not regex-matched, and re-emitted in
    # normalized ISO-8601 so two spellings of one instant cannot bind to two
    # different receipts.
    timestamp_raw = _single_line(
        attestation["timestamp"], "semantic review attestation.timestamp"
    )
    try:
        parsed_timestamp = dt.datetime.fromisoformat(
            timestamp_raw.replace("Z", "+00:00")
        )
    except ValueError as exc:
        raise SanctionError(
            "semantic review attestation.timestamp must be an ISO-8601 timestamp "
            f"(got {timestamp_raw!r}): {exc}"
        ) from exc
    if parsed_timestamp.tzinfo is None:
        raise SanctionError(
            "semantic review attestation.timestamp must carry an explicit UTC offset "
            f"(got {timestamp_raw!r}); a naive local time is not an audit record"
        )
    timestamp = parsed_timestamp.isoformat()

    # Same rule as denominator_attestation.exclusions: a list of {locator, reason}
    # objects, single-line, no duplicate locators. A bare isinstance(list) check
    # accepted [null, 5, {"a": 1}] and copied it verbatim into the bound receipt.
    # An empty list is the positive claim "nothing was excluded"; the absence of
    # the field is a different claim and is already rejected by the keyset above.
    exclusions: list[dict[str, str]] = []
    exclusion_locators: set[str] = set()
    for i, value in enumerate(
        _expect_list(attestation["exclusions"], "semantic review attestation.exclusions")
    ):
        item_where = f"semantic review attestation.exclusions[{i}]"
        exclusion = _expect_object(value, item_where)
        exclusion_fields = {"locator", "reason"}
        _keys(exclusion, exclusion_fields, exclusion_fields, item_where)
        locator = _single_line(exclusion["locator"], f"{item_where}.locator")
        if locator in exclusion_locators:
            raise SanctionError(
                f"duplicate semantic review attestation.exclusions locator: {locator}"
            )
        exclusion_locators.add(locator)
        exclusions.append(
            {
                "locator": locator,
                "reason": _single_line(exclusion["reason"], f"{item_where}.reason"),
            }
        )

    # Every value below is the NORMALIZED one the validators returned, never the
    # raw attestation field: the receipt is what the owner reads and what this
    # helper binds, so the bytes it carries must be the bytes that were checked.
    return {
        "path": str(path),
        "sha256": _sha(data),
        "schema": SEMANTIC_SCHEMA,
        "reviewer": reviewer,
        "scope_reviewed": scope_reviewed,
        "exclusions": exclusions,
        "timestamp": timestamp,
        # Reader-visible honesty: this is an attestation of subject, not proof of
        # authorship or of review quality.
        "attests": "reviewer/agent attestation that this exact candidate identity set was reviewed; not authentication of the reviewer or of the review's correctness",
    }


def _verify_phase(
    lock_path: Path,
    lock: dict[str, Any],
    spec: dict[str, Any],
    phase: str,
    key: bytes | None,
    *,
    commits: Path | None,
    semantic_review: Path | None,
    write_receipt: bool,
) -> None:
    phase = _choice(phase, set(ALL_PHASES), "--phase")
    requires_decision = phase != PHASE_PRE_DECISION
    decision_record = _load_decision(
        lock_path, lock, spec, key, required=requires_decision
    )

    # Task 7: a rejected packet is dead for verification, not just for
    # apply/adopt/commit.  _load_decision's verdict gate is keyed on
    # required=True, so the pre-decision diagnostic would otherwise keep
    # printing VERIFIED over a rejected decision.
    if (
        phase == PHASE_PRE_DECISION
        and decision_record is not None
        and decision_record["verdict"] != "approved"
    ):
        raise SanctionError("packet was rejected; further verification is refused")

    # Task 7: both gates run before any evidence capture so that an ordering or
    # invalidation violation reports itself, rather than being masked by a
    # world-state message from a phase that was never permitted to run.
    if phase != PHASE_PRE_DECISION:
        _check_not_invalidated(lock_path, lock, spec, key)
    composition, sequence, predecessor, has_chain = _lifecycle_gate(
        lock_path, lock, spec, key, decision_record, phase
    )

    try:
        _verify_phase_evidence(
            lock_path,
            lock,
            spec,
            phase,
            key,
            commits=commits,
            semantic_review=semantic_review,
            write_receipt=write_receipt,
            composition=composition,
            sequence=sequence,
            predecessor=predecessor,
            decision_record=decision_record,
        )
    except _DriftError as exc:
        if has_chain:
            _record_invalidation(lock_path, lock, spec, key, phase, str(exc))
        raise


def _verify_phase_evidence(
    lock_path: Path,
    lock: dict[str, Any],
    spec: dict[str, Any],
    phase: str,
    key: bytes | None,
    *,
    commits: Path | None,
    semantic_review: Path | None,
    write_receipt: bool,
    composition: str | None,
    sequence: tuple[str, ...] | None,
    predecessor: dict[str, Any] | None,
    decision_record: dict[str, Any] | None,
) -> None:
    semantic: Any = None
    commit_map: Any = None
    material = _capture_target_material(spec)
    _verify_source_identities(lock, spec, key, material)
    mirror_now = _observe_exact_mirrors(spec, material, key, lock["nonce"])
    if mirror_now != lock["exact_mirror_groups"]:
        raise _DriftError("exact-mirror evidence changed after packet build")
    generated_now = _observe_generated(spec, material, key, lock["nonce"])
    _verify_generated_evidence(lock["generated_groups"], generated_now)

    if phase == "post-commit":
        current_roots = _observe_roots_allow_advanced(spec)
        _verify_root_identity(lock, current_roots, require_base_head=False)
    else:
        current_roots = _observe_roots(spec)
        _verify_root_identity(lock, current_roots, require_base_head=True)

    # Task 7: a packet with no Git commit candidates never reaches pre-commit or
    # post-commit, so its terminal live/adoption phase is the last verification
    # it will ever receive.  The live-only Git invariants that the commit phases
    # enforce for a committing packet must therefore run here, or making the
    # commit phases invalid would silently delete that coverage rather than
    # relocate it.  Runs before the per-phase index comparison so the precise
    # detector reports the violation it was written to name.
    if sequence is not None and phase == sequence[-1] and not lock["candidates"]:
        for root_id, current in current_roots.items():
            if current["kind"] != "git":
                continue
            _verify_live_only_index_invariant(lock, spec, current_roots, root_id)
            if current["head"] != lock["roots"][root_id]["head"]:
                raise SanctionError(f"non-committing Git root {root_id} changed HEAD after sanction")
            if current["index"] != lock["roots"][root_id]["index"]:
                raise SanctionError(f"non-committing Git root {root_id} changed index after sanction")

    if phase == PHASE_PRE_DECISION or phase in _ENTRY_PHASES:
        # `desired="entry"` already expands per target to BASE for a pre-apply
        # entry and TARGET for an already-applied one, which is exactly the
        # "BASE for pending targets and TARGET for already-applied targets"
        # semantics the transition table specifies for mixed-freshness; the
        # all-pre-apply and all-already-applied rows are its degenerate cases.
        # Sequence membership is what keeps each name to its own composition.
        _current_matches(lock, spec, key, desired="entry")
        _validate_residue(spec, current_roots)
        for root_id, current in current_roots.items():
            if current["kind"] == "git" and current["index"] != lock["roots"][root_id]["index"]:
                raise _DriftError(f"Git index changed for {root_id}; packet is stale")
            if current["kind"] == "git" and current["status"] != lock["roots"][root_id]["status"]:
                raise _DriftError(f"Git status changed for {root_id}; packet is stale")
    elif phase == "post-apply":
        _current_matches(lock, spec, key, desired="target")
        _validate_residue(spec, current_roots, allow_all_targets=True)
        for root_id, current in current_roots.items():
            if current["kind"] == "git" and current["index"] != lock["roots"][root_id]["index"]:
                raise SanctionError(f"post-apply phase found staged/index mutation before its gate in {root_id}")
    elif phase == "pre-commit":
        _current_matches(lock, spec, key, desired="target")
        _validate_residue(spec, current_roots, allow_all_targets=True)
        semantic = _semantic_evidence(semantic_review, lock)
        for root_id, current in current_roots.items():
            if current["kind"] != "git":
                continue
            _verify_live_only_index_invariant(lock, spec, current_roots, root_id)
            if (
                root_id not in lock["candidates"]
                and current["index"] != lock["roots"][root_id]["index"]
            ):
                raise SanctionError(
                    f"non-committing Git root {root_id} changed index before commit"
                )
        for root_id, candidate in lock["candidates"].items():
            if current_roots[root_id]["index"]["flags"] != candidate["index_flags"]:
                raise SanctionError(
                    f"real index flags differ from the sanctioned candidate in {root_id}"
                )
            actual_patch = _candidate_real_patch(spec, root_id, candidate)
            expected_patch = _read(Path(candidate["patch"]["path"]), f"candidate patch {root_id}")
            if actual_patch != expected_patch:
                raise SanctionError(f"real staged bytes/path/modes differ from sanctioned candidate in {root_id}")
            staged = current_roots[root_id]["status"]["staged"]
            if staged != candidate["changed_paths"]:
                raise SanctionError(f"real staged path set differs in {root_id}: expected {candidate['changed_paths']}, got {staged}")
    else:
        semantic = _semantic_evidence(semantic_review, lock)
        if commits is None:
            raise SanctionError("post-commit requires --commits JSON mapping root id to commit SHA")
        commit_map = _expect_object(_json_load(commits, "commit map"), "commit map")
        if set(commit_map) != set(lock["candidates"]):
            raise SanctionError("commit map root set must exactly equal candidate Git roots")
        _current_matches(lock, spec, key, desired="target")
        for root_id, current in current_roots.items():
            if current["kind"] == "git":
                _verify_live_only_index_invariant(
                    lock, spec, current_roots, root_id
                )
        for root_id, candidate in lock["candidates"].items():
            root = spec["_roots"][root_id]["_path"]
            commit = _git(root, "rev-parse", str(commit_map[root_id])).stdout.decode().strip()
            if current_roots[root_id]["head"] != commit:
                raise SanctionError(f"current HEAD in {root_id} is not the sanctioned commit {commit}")
            parent_line = _git(root, "rev-list", "--parents", "-n", "1", commit).stdout.decode().strip().split()
            if len(parent_line) != 2 or parent_line[1] != candidate["base_revision"]:
                raise SanctionError(f"commit {commit} in {root_id} has wrong or non-single parent")
            tree = _git(root, "rev-parse", f"{commit}^{{tree}}").stdout.decode().strip()
            if tree != candidate["candidate_tree"]:
                raise SanctionError(f"commit tree differs from sanctioned candidate in {root_id}")
            actual_patch = _git(root, "diff", "--binary", "--full-index", "--find-renames", candidate["base_revision"], commit).stdout
            expected_patch = _read(Path(candidate["patch"]["path"]), f"candidate patch {root_id}")
            if actual_patch != expected_patch:
                raise SanctionError(f"committed patch differs from sanctioned candidate in {root_id}")
            if current_roots[root_id]["index"]["entries"] != _tree_entries(root, commit):
                raise SanctionError(f"current index in {root_id} does not exactly match the sanctioned commit")
            if current_roots[root_id]["index"]["flags"] != candidate["index_flags"]:
                raise SanctionError(
                    f"current index flags differ from the sanctioned candidate in {root_id}"
                )
            target_residue = set(candidate["changed_paths"]).intersection(
                set().union(*[set(paths) for paths in current_roots[root_id]["status"].values()])
            )
            if target_residue:
                raise SanctionError(f"sanctioned commit paths retain post-commit status in {root_id}: {sorted(target_residue)}")
        for root_id, current in current_roots.items():
            if current["kind"] != "git" or root_id in lock["candidates"]:
                continue
            if current["head"] != lock["roots"][root_id]["head"]:
                raise SanctionError(f"non-committing Git root {root_id} changed HEAD after sanction")
            if current["index"] != lock["roots"][root_id]["index"]:
                raise SanctionError(f"non-committing Git root {root_id} changed index after sanction")
        _validate_residue(spec, current_roots, allow_all_targets=True)

    if write_receipt:
        if phase == PHASE_PRE_DECISION:
            # Not a chain member: a repeatable pre-approval diagnostic.
            receipt = {
                "schema": SCHEMA,
                "packet_id": lock["packet_id"],
                "phase": phase,
                "verified_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            }
            if decision_record is not None:
                receipt["decision_record_binding"] = decision_record["record_binding"]
            _json_write(_lifecycle_receipt_path(lock_path, phase), receipt)
        else:
            assert sequence is not None and predecessor is not None
            assert decision_record is not None
            payload = {
                "schema": LIFECYCLE_SCHEMA,
                "packet_id": lock["packet_id"],
                "helper_sha256": lock["helper"]["sha256"],
                "nonce": lock["nonce"],
                "entry_composition": composition,
                "sequence": list(sequence),
                "phase": phase,
                "predecessor": predecessor,
                "terminal": phase == sequence[-1],
                "decision_record_binding": decision_record["record_binding"],
                "verified_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            }
            if phase in {"pre-commit", "post-commit"}:
                payload["semantic_review"] = semantic
            if phase == "post-commit":
                payload["commits"] = commit_map
            receipt = dict(payload)
            receipt["receipt_binding"] = _lifecycle_binding(
                payload, lock=lock, spec=spec, key=key, purpose="lifecycle"
            )
            # The create-exclusive write IS the atomic advance and the one-use
            # gate: the frontier moves only on a receipt that exists, and a
            # failure earlier in this function writes nothing, so a drifted or
            # refused phase can never advance the lifecycle.
            _json_write(_lifecycle_receipt_path(lock_path, phase), receipt)
    print(f"VERIFIED {phase} {lock['packet_id']}")
    if sequence is not None and phase == sequence[-1]:
        scope = "no Git commit candidates" if not lock["candidates"] else "committed"
        print(f"COMPLETE {phase} {lock['packet_id']} ({scope})")


def _observe_roots_allow_advanced(spec: dict[str, Any]) -> dict[str, Any]:
    observed: dict[str, Any] = {}
    for root_id, root in spec["_roots"].items():
        path = root["_path"]
        row: dict[str, Any] = {
            "id": root_id,
            "kind": root["kind"],
            "path": str(path),
            "base_revision": root.get("base_revision"),
            "base_attestation": root["base_attestation"],
            "physical": _physical_directory_identity(path, f"root {root_id}"),
        }
        if root["kind"] == "git":
            head = _git(path, "rev-parse", "HEAD").stdout.decode().strip()
            branch_cp = _git(path, "symbolic-ref", "--quiet", "--short", "HEAD", check=False)
            git_dir_text = _git(path, "rev-parse", "--absolute-git-dir").stdout.decode().strip()
            object_text = _git(path, "rev-parse", "--git-path", "objects").stdout.decode().strip()
            object_path = Path(object_text)
            if not object_path.is_absolute():
                object_path = path / object_path
            row.update(
                head=head,
                branch=branch_cp.stdout.decode().strip() if branch_cp.returncode == 0 else "DETACHED",
                git_dir=str(Path(git_dir_text).resolve()),
                object_dir=str(object_path.resolve()),
                status=_git_status(path),
                index=_index_snapshot(path),
            )
        observed[root_id] = row
    return observed


def verify_packet(lock_path: Path, phase: str, key_path: str | None, commits: Path | None, semantic_review: Path | None) -> None:
    lock, spec = _load_lock(lock_path)
    key = _key(key_path, spec["_sensitive"])
    _verify_phase(lock_path, lock, spec, phase, key, commits=commits, semantic_review=semantic_review, write_receipt=True)


def _receipt_target_state(lock: dict[str, Any], spec: dict[str, Any], target_id: str, key: bytes | None) -> str:
    target = spec["_targets"][target_id]
    locked = lock["targets"][target_id]
    current = _current_state(spec, target, key, lock["nonce"])
    op = target["_operation"]
    if op == "rename":
        at_target = _same_identity(current["identity"], locked["target"]) and current["old_identity"]["algorithm"] == "absent"
        at_base = _same_identity(current["old_identity"], locked["base"]) and current["identity"]["algorithm"] == "absent"
    elif op == "delete":
        at_target = current["identity"]["algorithm"] == "absent"
        at_base = _same_identity(current["identity"], locked["base"])
    else:
        at_target = _same_identity(current["identity"], locked["target"])
        at_base = _same_identity(current["identity"], locked["base"])
    # Mode can be the ONLY thing separating base from target (a mode-change, or any
    # target whose proposed bytes equal its base). Identity alone then cannot prove
    # the target was applied, so fold observable/relevant mode into the verdict:
    # where the mode is the sole discriminator and cannot be observed, the live
    # state is UNKNOWN, never a confident TARGET (fail toward the observable side).
    target_mode = locked.get("target_mode")
    base_mode = locked.get("base_mode")
    mode_discriminates = (
        op not in ("delete", "rename")
        and target_mode is not None
        and base_mode is not None
        and target_mode != base_mode
    )
    # A rename can ALSO carry an executable-mode change: correct bytes at the new
    # path with the wrong mode is not fully at target.  current["mode"] is the new
    # (target) path's mode for a rename, so this target-side downgrade is exact.
    # It fires only when the mode is observable (matching the modify at_target
    # guard below, which stays TARGET on an unobservable platform); the base side
    # (old path restored) is deliberately left to identity because current["mode"]
    # describes the new path, not the old.  Delete has no target mode and stays
    # excluded.
    if (
        op == "rename"
        and target_mode is not None
        and base_mode is not None
        and target_mode != base_mode
        and at_target
        and current["mode_observable"]
        and not _mode_matches(current["mode"], target_mode, observable=current["mode_observable"])
    ):
        return "UNKNOWN"
    if mode_discriminates:
        observable = current["mode_observable"]
        mode_at_target = _mode_matches(current["mode"], target_mode, observable=observable)
        mode_at_base = _mode_matches(current["mode"], base_mode, observable=observable)
        if at_target and at_base:
            if not observable:
                return "UNKNOWN"
            if mode_at_target and not mode_at_base:
                return "TARGET"
            if mode_at_base and not mode_at_target:
                return "BASE"
            return "UNKNOWN"
        if at_target and observable and not mode_at_target:
            return "UNKNOWN"
        # Symmetric downgrade: a live file at BASE bytes whose observed mode
        # diverges from the locked base mode is mode-drifted, not confidently
        # BASE (the same fail-toward-observable rule the target side applies).
        # (The both-true block above always returns, so at_base here already
        # implies not at_target -- mirroring the target-side guard's shape.)
        if at_base and observable and not mode_at_base:
            return "UNKNOWN"
    if at_target:
        return "TARGET"
    if at_base:
        return "BASE"
    if current["identity"]["algorithm"] == "absent":
        return "ABSENT"
    return "DRIFT"


def _candidate_entry(lock: dict[str, Any], target_id: str) -> dict[str, Any] | None:
    for candidate in lock["candidates"].values():
        for entry in candidate["entries"]:
            if entry["target"] == target_id:
                return entry
    return None


def _index_blob(root: Path, path: str) -> tuple[bytes | None, str]:
    raw = _git(root, "ls-files", "--stage", "--", path).stdout
    records = [record for record in raw.splitlines() if record]
    if not records:
        return None, "absent"
    if len(records) != 1:
        return b"", "unmerged"
    meta, sep, _ = records[0].partition(b"\t")
    bits = meta.decode("ascii", "strict").split()
    if not sep or len(bits) != 3 or bits[2] != "0":
        return b"", "unmerged"
    data = _git(root, "show", f":{path}").stdout
    return data, bits[0]


def _classify_git_layer(
    lock: dict[str, Any],
    spec: dict[str, Any],
    target_id: str,
    layer: str,
    key: bytes | None,
) -> tuple[str, str]:
    target = spec["_targets"][target_id]
    locked = lock["targets"][target_id]
    root = spec["_roots"][target["root"]]["_path"]
    entry = _candidate_entry(lock, target_id)

    def read_path(path: str) -> tuple[bytes | None, str]:
        if layer == "index":
            return _index_blob(root, path)
        return _git_blob_at(root, "HEAD", path)

    def observed_identity(data: bytes | None) -> dict[str, Any]:
        if data is None:
            return {"algorithm": "absent"}
        if target["_confidentiality_kind"] == "sensitive":
            if key is None:
                raise SanctionError(
                    f"sensitive Git layer classification for {target_id} requires --hmac-key-file"
                )
            return _hmac_identity(
                data, key, lock["nonce"], target_id, f"receipt-{layer}"
            )
        return _identity(data)

    new_bytes, new_mode = read_path(target["path"])
    old_bytes: bytes | None = None
    old_mode = "absent"
    if target["_operation"] == "rename":
        old_bytes, old_mode = read_path(target["old_path"])

    candidate_identity = (
        entry.get("committed_identity", {"algorithm": "absent"})
        if entry is not None
        else locked["target"]
    )
    candidate_mode = entry["mode"] if entry is not None else locked["target_mode"]
    new_identity = observed_identity(new_bytes)
    old_identity = observed_identity(old_bytes)
    op = target["_operation"]
    if op == "rename":
        target_match = (
            new_identity == candidate_identity
            and new_mode == candidate_mode
            and old_bytes is None
        )
        base_match = old_identity == locked["base"] and old_mode == locked["base_mode"] and new_bytes is None
    elif op == "delete":
        target_match = new_bytes is None
        base_match = new_identity == locked["base"] and new_mode == locked["base_mode"]
    elif op == "add":
        target_match = new_identity == candidate_identity and new_mode == candidate_mode
        base_match = new_bytes is None
    else:
        target_match = new_identity == candidate_identity and new_mode == candidate_mode
        base_match = new_identity == locked["base"] and new_mode == locked["base_mode"]
    identity_text = _id_short(new_identity)
    if op == "rename":
        identity_text += f"; old={_id_short(old_identity)}"
    if target_match:
        return ("STAGED-TARGET" if layer == "index" else "COMMITTED-TARGET"), identity_text
    if base_match:
        return "BASE", identity_text
    if new_mode == "unmerged":
        return "UNKNOWN", identity_text
    return "DRIFT", identity_text


def _safe_receipt_output(
    lock_path: Path,
    lock: dict[str, Any],
    spec: dict[str, Any],
    out: Path,
    key_path: str | None,
    label: str = "receipt --out",
) -> Path:
    """Resolve and validate a helper-written output path.

    Shared by `receipt` and `semantic-template`: the helper never writes inside
    the sanctioned scope, so an emitted path must clear FOUR containment classes
    (packet-evidence dir, any declared root, a generated-capture dir, protected
    helper/manifest/artifact/source files) and must not already exist.  A single
    `_within(root)` check is insufficient -- a skeleton dropped in the evidence
    or capture dir would corrupt the very denominators the packet gates.
    """
    candidate = _absolute_create_path(out, label)
    packet_dir = _lexical_absolute(lock_path, "packet lock").parent
    if _within(candidate, packet_dir):
        raise SanctionError(f"{label} must be outside the packet evidence directory: {candidate}")
    for root_id, root in spec["_roots"].items():
        if _within(candidate, root["_path"]):
            raise SanctionError(f"{label} must be outside declared root {root_id}: {candidate}")
    for group_id, group in spec["_groups"].items():
        for run_name in ("_run_a", "_run_b"):
            capture = group.get(run_name)
            if capture is not None and _within(candidate, capture):
                raise SanctionError(
                    f"{label} must be outside generated group {group_id} {run_name[1:]} capture: {candidate}"
                )

    protected_files = {
        Path(lock["helper"]["path"]).resolve(strict=False),
        Path(lock["manifest"]["path"]).resolve(strict=False),
        Path(lock["packet_artifact"]["path"]).resolve(strict=False),
    }
    if key_path is not None:
        protected_files.add(_absolute(key_path, "--hmac-key-file"))
    for target in spec["_targets"].values():
        for field in ("_base_source", "_target_source"):
            source = target.get(field)
            if source is not None:
                protected_files.add(Path(source).resolve(strict=True))
    for group in spec["_groups"].values():
        protected_files.add(group["_generator_source"].resolve(strict=True))
        for artifact in group["_input_artifacts"]:
            protected_files.add(artifact["_path"].resolve(strict=True))
    if candidate in protected_files:
        raise SanctionError(f"{label} collides with protected sanction evidence/source: {candidate}")
    if _physical_validate(candidate, label, None, allow_missing=True):
        raise SanctionError(f"{label} output already exists; CREATE_NEW refuses replacement: {candidate}")
    return candidate


def write_partial_receipt(lock_path: Path, out: Path, failure_point: str, key_path: str | None) -> int:
    lock, spec = _load_lock(lock_path)
    key = _key(key_path, spec["_sensitive"])
    decision_record = _load_decision(
        lock_path, lock, spec, key, required=False
    )
    out = _safe_receipt_output(lock_path, lock, spec, out, key_path)
    states = {target_id: _receipt_target_state(lock, spec, target_id, key) for target_id in spec["decision"]["target_ids"]}
    lines = ["# INCOMPLETE — NOT ADOPTED / NOT COMMITTED\n", "\n", f"**Packet:** `{lock['packet_id']}`  \n", f"**Failure point:** {_md_code(_nonempty(failure_point, '--failure-point'))}  \n"]
    if decision_record is None:
        lines.append("**Decision record:** not yet recorded.  \n")
    else:
        lines.append(
            f"**Decision record binding:** `{_id_short(decision_record['record_binding'])}`  \n"
        )
    lines.append("**PARTIAL LIVE / STAGED / COMMITTED STATE MAY BE PRESENT. No completion claim is permitted.**\n")
    lines.extend(["\n", "| Target | Live state / identity | Index state / identity | Commit state / identity | Compensation classification |\n", "|---|---|---|---|---|\n"])
    for target_id in spec["decision"]["target_ids"]:
        state = states[target_id]
        target = spec["_targets"][target_id]
        current = _current_state(spec, target, key, lock["nonce"])
        live_identity = _id_short(current["identity"])
        if target["_operation"] == "rename":
            live_identity += f"; old={_id_short(current['old_identity'])}"
        if spec["_roots"][target["root"]]["kind"] == "git":
            index_state, index_identity = _classify_git_layer(
                lock, spec, target_id, "index", key
            )
            commit_state, commit_identity = _classify_git_layer(
                lock, spec, target_id, "commit", key
            )
        else:
            index_state = index_identity = commit_state = commit_identity = "N/A"
        if commit_state == "COMMITTED-TARGET":
            compensation = "unsafe for automatic compensation: target is committed; preserve and adjudicate"
        elif index_state == "STAGED-TARGET":
            compensation = "unsafe for automatic compensation: target is staged; preserve and adjudicate"
        elif state == "TARGET" and target["_entry"] == "already-applied":
            # An already-applied target held its target bytes BEFORE this
            # transaction, so the transaction does not own it and its captured
            # base is not this transaction's to restore -- recommending a base
            # rollback here would undo pre-existing adopted work (plan step:
            # "compensation only when identity-bound transaction-ownership
            # evidence exists").
            compensation = "unsafe for automatic compensation: target was already-applied before this transaction (no transaction-ownership evidence); preserve and adjudicate"
        elif state == "TARGET":
            compensation = "candidate: transaction-owned target still exact; restore only from captured base after recheck"
        elif state == "BASE":
            compensation = "no live compensation needed"
        else:
            compensation = "unsafe for automatic compensation; preserve and adjudicate"
        lines.append(
            f"| {_md_code(target_id)} | {_md_code(state)} / {_md_code(live_identity)} | "
            f"{_md_code(index_state)} / {_md_code(index_identity)} | "
            f"{_md_code(commit_state)} / {_md_code(commit_identity)} | {compensation} |\n"
        )
    # Residue denominator: every DECLARED out-of-transaction Git path with its
    # layer, disposition, and current identity -- plus any UNDECLARED residue
    # observed now, which keeps the receipt incomplete (never silently omitted).
    #
    # Residue is tracked by LAYER MEMBERSHIP, by design: these paths are never
    # committed or mutated by the transaction, so the drift signal is a change in
    # which git layers a path occupies (declared vs current states), not its byte
    # identity.  The current identity is rendered for the reader but is NOT
    # compared against a build-time-locked per-layer identity -- the residue lock
    # rows carry no identity field (schema fixed to root/path/states/disposition/
    # reason), and binding one is out of scope because residue content is not
    # transaction-relevant.  Consequence (documented limit): a same-layer content
    # change to a residue path is shown via the current identity but is not
    # auto-flagged as drift; this surfaces only on the INCOMPLETE receipt, which
    # never sanctions a commit.
    target_paths: dict[str, set[str]] = {}
    for target in spec["_targets"].values():
        if spec["_roots"][target["root"]]["kind"] != "git":
            continue
        owned = target_paths.setdefault(target["root"], set())
        owned.add(target["path"])
        if target["_operation"] == "rename":
            owned.add(target["old_path"])
    # Declared coverage keys on (root, path, STATE) triples: a declared path
    # observed in a layer outside its declared states is undeclared residue for
    # that layer (a declared-unstaged path that becomes staged must surface,
    # never be silently deduplicated away by a path-only key).
    declared_layers: dict[tuple[str, str], set[str]] = {}
    for row in lock["residue"]:
        declared_layers.setdefault((row["root"], row["path"]), set()).update(row["states"])
    status_by_root = {
        root_id: _git_status(root["_path"])
        for root_id, root in spec["_roots"].items()
        if root["kind"] == "git"
    }
    lines.extend([
        "\n", "## Residue denominator\n", "\n",
        "| Residue path | Declared layers | Current layers | Disposition | Current identity |\n",
        "|---|---|---|---|---|\n",
    ])
    if not lock["residue"]:
        lines.append("| _(no out-of-transaction residue declared)_ | | | | |\n")
    for row in lock["residue"]:
        locator = f"{row['root']}:{row['path']}"
        residue_root = spec["_roots"][row["root"]]["_path"]
        snap = _read_snapshot(residue_root / row["path"], f"residue {locator}", missing_ok=True)
        residue_identity = _id_short(_identity(snap[0])) if snap is not None else "ABSENT"
        current_layers = sorted(
            state_name
            for state_name, paths in status_by_root.get(row["root"], {}).items()
            if row["path"] in paths
        )
        current_cell = _md_code(",".join(current_layers) if current_layers else "none")
        if set(current_layers) != set(row["states"]):
            current_cell += " **DRIFTED from declared**"
        lines.append(
            f"| {_md_code(locator)} | {_md_code(','.join(row['states']))} | {current_cell} | "
            f"{_md_code(row['disposition'])} | {_md_code(residue_identity)} |\n"
        )
    undeclared: list[tuple[str, str, str]] = []
    for root_id in status_by_root:
        for state_name, paths in status_by_root[root_id].items():
            for path in paths:
                if path in target_paths.get(root_id, set()):
                    continue
                if state_name in declared_layers.get((root_id, path), set()):
                    continue
                undeclared.append((root_id, path, state_name))
    if undeclared:
        lines.append(
            "\n**UNDECLARED residue observed at receipt time — the residue denominator is "
            "INCOMPLETE and this state is UNKNOWN; adjudicate before any completion claim:**\n\n"
        )
        for root_id, path, state_name in sorted(set(undeclared)):
            undeclared_locator = _md_code(f"{root_id}:{path}")
            declared_states = declared_layers.get((root_id, path))
            if declared_states:
                declared_cell = _md_code(",".join(sorted(declared_states)))
                lines.append(
                    f"- {undeclared_locator} ({state_name}) — DECLARED path observed in an "
                    f"UNDECLARED state (declared layers: {declared_cell})\n"
                )
            else:
                lines.append(
                    f"- {undeclared_locator} ({state_name}) — UNDECLARED, not in the locked residue denominator\n"
                )
    lines.append("\nThe helper did not mutate, compensate, stage, unstage, commit, or clean any path. A failed/half-copied target must never become a propagation source.\n")
    _write_text(out, "".join(lines))
    print(f"INCOMPLETE {lock['packet_id']} {out}")
    return EXIT_INCOMPLETE


def emit_semantic_template(lock_path: Path, out: Path) -> None:
    """Emit a pre-filled sanction-semantic-review/v1 attestation skeleton.

    The emitter fills every field a reviewer cannot reasonably hand-derive --
    the packet binding (packet_id, nonce, helper_sha256) and the exact
    candidate root/path/blob/mode identity recomputed from the lock -- and
    leaves the reviewer-JUDGMENT fields (reviewer.identity/role, scope_reviewed)
    empty.  Two non-judgment fields carry provisional defaults the reviewer is
    told to confirm: `exclusions` defaults to `[]` (the positive claim "nothing
    was excluded"; the field is required, so it cannot ship absent) and
    `timestamp` to the emission time.  An unfilled skeleton fails the pre-commit
    gate (its validators reject the empty reviewer/scope values), so emitting a
    template never substitutes for performing the review.

    Scope note: candidate_identity binds only the committed candidate surface
    (lock["candidates"] -- the Git tree/blob/mode set).  A semantic PASS attests
    review of the committed bytes, NOT of commit:false working-tree targets or
    generated-group outputs; the receipt/verify wording states this.

    The output path is validated by the shared _safe_receipt_output guard (the
    helper never writes inside the sanctioned scope) and is create-exclusive.
    """
    lock, spec = _load_lock(lock_path)
    if not lock["candidates"]:
        raise SanctionError(
            "semantic-template requires a packet with Git commit candidates; "
            "this packet declares none, so no staged-byte semantic review applies"
        )
    out = _safe_receipt_output(lock_path, lock, spec, out, None, label="semantic-template --out")
    template = {
        "schema": SEMANTIC_SCHEMA,
        "packet_id": lock["packet_id"],
        "nonce": lock["nonce"],
        "helper_sha256": lock["helper"]["sha256"],
        "reviewer": {"identity": "", "role": ""},
        "scope_reviewed": "",
        "exclusions": [],
        "timestamp": dt.datetime.now(dt.timezone.utc).isoformat(),
        "candidate_identity": _candidate_identity(lock),
    }
    if set(template) != set(SEMANTIC_ATTESTATION_FIELDS):
        raise SanctionError(
            "semantic-template skeleton drifted from the validator's required keyset"
        )
    _write_text(out, json.dumps(template, indent=2, ensure_ascii=False, sort_keys=True) + "\n")
    print(f"TEMPLATE {lock['packet_id']} {out}")
    print(
        "Review the staged bytes, then fill reviewer.identity, reviewer.role and "
        "scope_reviewed (plus exclusions, if any) and confirm the timestamp reflects "
        "the completed review; the unfilled skeleton is rejected by pre-commit."
    )


def _add_key_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--hmac-key-file", help="absolute path to separately held 32+ byte HMAC key")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    build = sub.add_parser("build", help="freeze a declared scope and render the packet")
    build.add_argument("manifest")
    build.add_argument("--out", required=True)
    _add_key_arg(build)

    decision = sub.add_parser("decision", help="record an owner decision attestation")
    decision.add_argument("lock")
    decision.add_argument("--verdict", required=True, choices=("approved", "rejected"))
    decision.add_argument("--evidence-file", required=True)
    _add_key_arg(decision)

    verify = sub.add_parser("verify", help="re-derive evidence at a lifecycle phase")
    verify.add_argument("lock")
    verify.add_argument("--phase", required=True, choices=ALL_PHASES)
    verify.add_argument("--commits")
    verify.add_argument("--semantic-review-file")
    _add_key_arg(verify)

    receipt = sub.add_parser("receipt", help="enumerate mixed state after a failed transaction leg")
    receipt.add_argument("lock")
    receipt.add_argument("--out", required=True)
    receipt.add_argument("--failure-point", required=True)
    _add_key_arg(receipt)

    template = sub.add_parser(
        "semantic-template",
        help="emit a pre-filled semantic review attestation skeleton for this packet",
    )
    template.add_argument("lock")
    template.add_argument("--out", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "build":
            build_packet(_absolute(args.manifest, "manifest"), Path(args.out), args.hmac_key_file)
            return 0
        if args.command == "decision":
            record_decision(_absolute(args.lock, "lock"), args.verdict, Path(args.evidence_file), args.hmac_key_file)
            return 0
        if args.command == "verify":
            commits = _absolute(args.commits, "--commits") if args.commits else None
            semantic = _absolute(args.semantic_review_file, "--semantic-review-file") if args.semantic_review_file else None
            verify_packet(_absolute(args.lock, "lock"), args.phase, args.hmac_key_file, commits, semantic)
            return 0
        if args.command == "receipt":
            return write_partial_receipt(_absolute(args.lock, "lock"), Path(args.out), args.failure_point, args.hmac_key_file)
        if args.command == "semantic-template":
            emit_semantic_template(
                _absolute(args.lock, "lock"),
                Path(args.out),
            )
            return 0
        raise SanctionError(f"unsupported command {args.command}")
    except SanctionError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return EXIT_INVALID


if __name__ == "__main__":
    raise SystemExit(main())
