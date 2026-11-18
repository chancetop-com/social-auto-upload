"""User-private state and kernel locks shared by compatible managed CLI processes."""
from __future__ import annotations

import errno
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
import tempfile
from typing import BinaryIO


def _private(path: Path, info: os.stat_result, *, directory: bool) -> None:
    right_type = stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)
    if not right_type or (not directory and info.st_nlink != 1):
        raise PermissionError("托管会话目录或文件类型不安全。")
    if os.name == "nt":
        from utils.windows_profile_security import check_private
        check_private(path)
    elif info.st_uid != os.geteuid() or info.st_mode & 0o077:
        raise PermissionError("托管会话目录和文件必须仅当前用户可访问。")
    elif sys.platform == "darwin":
        from utils.macos_profile_security import check_private
        check_private(path)


def _private_directory(path: Path) -> None:
    if os.name == "nt":
        from utils.windows_profile_security import private_mkdir
        private_mkdir(path)
    else:
        path.mkdir(mode=0o700, exist_ok=True)
    _private(path, path.lstat(), directory=True)


def _open_file(path: Path, flags: int) -> int:
    if os.name == "nt":
        # Windows has no O_NOFOLLOW. The verified parent excludes other users.
        try:
            info = path.lstat()
        except FileNotFoundError:
            pass
        else:
            _private(path, info, directory=False)
        flags |= os.O_BINARY
    else:
        flags |= os.O_NOFOLLOW | os.O_NONBLOCK
    fd = os.open(path, flags, 0o600)
    try:
        _private(path, os.fstat(fd), directory=False)
    except BaseException:
        os.close(fd)
        raise
    return fd


class ProfileStore:
    """Only lock files are permanent. Replacing one could split its kernel lock."""

    def __init__(self, provider: str, profile_id: str):
        home = Path.home()
        if not home.is_absolute():
            raise PermissionError("无法确认当前用户的主目录。")
        if os.name != "nt":
            info = home.stat()
            if info.st_uid != os.geteuid() or info.st_mode & 0o022:
                raise PermissionError("主目录无法保护托管会话文件。")
            if sys.platform == "darwin":
                from utils.macos_profile_security import check_private
                check_private(home, home=True)
        root = home / ".sau-managed-profiles"
        _private_directory(root)
        identity = json.dumps([provider, profile_id], ensure_ascii=True).encode("ascii")
        self._directory = root / hashlib.sha256(identity).hexdigest()
        _private_directory(self._directory)
        self._record = self._directory / "session.json"

    def try_lock(self, name: str) -> BinaryIO | None:
        if not re.fullmatch(r"[a-z][a-z0-9-]*", name):
            raise ValueError("无效的托管会话锁名。")
        fd = _open_file(self._directory / (name + ".lock"), os.O_RDWR | os.O_CREAT)
        handle = os.fdopen(fd, "r+b", buffering=0)
        try:
            if os.name == "nt":
                from utils.windows_profile_security import try_lock
                acquired = try_lock(fd)
            else:
                import fcntl
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except OSError as exc:
                    if exc.errno not in (errno.EAGAIN, errno.EACCES):
                        raise
                    acquired = False
                else:
                    acquired = True
            if acquired:
                return handle
        except BaseException:
            handle.close()
            raise
        handle.close()
        return None

    def read_record(self) -> dict | None:
        try:
            fd = _open_file(self._record, os.O_RDONLY)
        except FileNotFoundError:
            return None
        with os.fdopen(fd, "rb") as stream:
            data = stream.read(65537)
        if len(data) <= 65536:
            try:
                record = json.loads(data)
            except (UnicodeError, ValueError):
                pass
            else:
                if isinstance(record, dict):
                    return record
        raise ValueError("无法读取托管会话记录。")

    def write_record(self, record: dict) -> None:
        encoded = json.dumps(record, allow_nan=False).encode("ascii")
        if len(encoded) > 65536:
            raise ValueError("托管会话记录过大。")
        fd, name = tempfile.mkstemp(dir=self._directory)
        temporary = Path(name)
        try:
            with os.fdopen(fd, "wb") as stream:
                _private(temporary, os.fstat(stream.fileno()), directory=False)
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self._record)
        finally:
            temporary.unlink(missing_ok=True)

    def clear_record(self) -> None:
        self._record.unlink(missing_ok=True)
