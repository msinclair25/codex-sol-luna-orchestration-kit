#!/usr/bin/env python3
"""Small cross-platform filesystem primitives for supported Sol/Luna flows.

POSIX mode bits are enforced on Unix. Native Windows uses ACLs rather than
meaningful ``0600``/``0700`` mode bits, so mode comparisons are intentionally
not used as an access-control test there. Link safety still rejects Windows
reparse points (including junctions), and file publication remains atomic and
collision-safe on both platforms.
"""
from __future__ import annotations

import os
import stat
import tempfile
from pathlib import Path
from typing import Optional


IS_WINDOWS = os.name == "nt"
PRIVATE_FILE_MODE = 0o600
PRIVATE_DIRECTORY_MODE = 0o700


def is_link_like(path: Path) -> bool:
    """Return true for symlinks and Windows reparse points/junctions."""

    try:
        if path.is_symlink():
            return True
        info = path.lstat()
    except FileNotFoundError:
        return False
    except OSError:
        return True
    attributes = getattr(info, "st_file_attributes", 0)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    return bool(reparse_flag and attributes & reparse_flag)


def is_link_safe_beneath(path: Path, root: Path) -> bool:
    """Return true when ``path`` is lexical child of ``root`` with no link-like component.

    The check deliberately does not call ``resolve()``: resolving first would hide
    the symlink or Windows junction that this boundary is intended to detect.
    Missing tail components are allowed so callers can validate a destination
    before creating its parent directories.
    """

    absolute_root = Path(os.path.abspath(root))
    absolute_path = Path(os.path.abspath(path))
    try:
        relative = absolute_path.relative_to(absolute_root)
    except ValueError:
        return False
    current = absolute_root
    if is_link_like(current):
        return False
    for part in relative.parts:
        current = current / part
        if is_link_like(current):
            return False
    return True


def allowed_system_link(path: Path) -> bool:
    """Allow only the known macOS/POSIX aliases traversed by temp paths."""

    return not IS_WINDOWS and path in {Path("/tmp"), Path("/var")}


def shared_temp_roots() -> set[Path]:
    """Return resolved shared temporary roots for broad-path rejection."""

    candidates = {Path(tempfile.gettempdir())}
    if not IS_WINDOWS:
        candidates.update({Path("/tmp"), Path("/private/tmp"), Path("/var/tmp")})
    roots: set[Path] = set()
    for candidate in candidates:
        try:
            roots.add(candidate.resolve())
        except (OSError, RuntimeError):
            continue
    return roots


def mode_matches(path: Path, expected: int) -> bool:
    """Check private POSIX bits, or defer to Windows ACL inheritance."""

    if IS_WINDOWS:
        return True
    try:
        return stat.S_IMODE(path.stat(follow_symlinks=False).st_mode) == expected
    except OSError:
        return False


def mode_from_stat(info: os.stat_result, expected: int) -> bool:
    """Like :func:`mode_matches` for an already captured stat result."""

    return IS_WINDOWS or stat.S_IMODE(info.st_mode) == expected


def set_mode(path: Path, mode: int) -> None:
    """Apply a POSIX mode where it is an enforceable access-control check."""

    if not IS_WINDOWS:
        os.chmod(path, mode)


def set_fd_mode(fd: int, mode: int) -> None:
    """Apply a POSIX descriptor mode without requiring Windows Python 3.13."""

    if not IS_WINDOWS:
        os.fchmod(fd, mode)


def sync_directory(path: Path) -> None:
    """Durably sync directory metadata where directory fsync is supported."""

    if IS_WINDOWS:
        return
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    directory_fd = os.open(str(path), flags)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def atomic_replace(
    path: Path,
    data: bytes,
    *,
    mode: Optional[int] = None,
    preserve_existing_mode: bool = False,
) -> None:
    """Atomically create or replace one regular file in its existing parent."""

    if is_link_like(path):
        raise OSError("link_destination")
    selected_mode = mode
    if preserve_existing_mode and path.exists() and not IS_WINDOWS:
        selected_mode = stat.S_IMODE(path.stat(follow_symlinks=False).st_mode)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            if selected_mode is not None:
                set_fd_mode(handle.fileno(), selected_mode)
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            temporary.unlink()
        except OSError:
            pass
        raise


def atomic_create(path: Path, data: bytes, *, mode: int = PRIVATE_FILE_MODE) -> None:
    """Atomically publish a new file without replacing an existing target."""

    if path.exists() or is_link_like(path):
        raise FileExistsError(str(path))
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    temporary = Path(temporary_name)
    published = False
    try:
        with os.fdopen(fd, "wb") as handle:
            set_fd_mode(handle.fileno(), mode)
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        if path.exists() or is_link_like(path):
            raise FileExistsError(str(path))
        if IS_WINDOWS:
            # Windows rename is atomic and fails rather than replacing dst.
            os.rename(temporary, path)
        else:
            # A same-filesystem hard link provides atomic no-replace publish.
            os.link(temporary, path, follow_symlinks=False)
            temporary.unlink()
        published = True
        sync_directory(path.parent)
    except Exception:
        if published:
            try:
                path.unlink()
            except OSError:
                pass
        try:
            temporary.unlink()
        except OSError:
            pass
        raise
