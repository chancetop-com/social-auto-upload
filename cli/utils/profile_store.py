"""User-private state and kernel locks shared by compatible managed CLI processes."""
from __future__ import annotations

import errno
from functools import cache
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile
from typing import BinaryIO
from uuid import UUID


@cache
def system_boot_id() -> str | None:
    """Return the OS boot UUID when available, shared by independent CLIs."""
    try:
        if sys.platform == "darwin":
            raw = subprocess.check_output(
                ["/usr/sbin/sysctl", "-n", "kern.bootsessionuuid"],
                stderr=subprocess.DEVNULL, text=True, timeout=1,
            )
            boot = UUID(raw.strip())
        elif sys.platform == "win32":
            import ctypes

            # SYSTEM_BOOT_ENVIRONMENT_INFORMATION starts with the boot GUID.
            info = ctypes.create_string_buffer(32)
            returned = ctypes.c_ulong()
            query = ctypes.windll.ntdll.NtQuerySystemInformation
            if query(90, info, ctypes.sizeof(info), ctypes.byref(returned)) != 0 or returned.value < 16:
                return None
            boot = UUID(bytes_le=info.raw[:16])
        elif sys.platform.startswith("linux"):
            boot = UUID(Path("/proc/sys/kernel/random/boot_id").read_text().strip())
        else:
            return None
    except (OSError, ValueError, AttributeError, subprocess.SubprocessError):
        return None
    return boot.hex if boot.int else None


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


def _valid_record(record: object) -> bool:
    if not isinstance(record, dict):
        return False
    def digest(key):
        value = record.get(key)
        return (
            isinstance(value, str)
            and re.fullmatch(r"[a-f0-9]{64}", value) is not None
        )

    def timestamp(key):
        value = record.get(key)
        return (
            not isinstance(value, bool)
            and isinstance(value, (int, float))
            and math.isfinite(value)
            and value >= 0
        )

    if not digest("resource"):
        return False
    phase = record.get("phase")
    if "boot_id" in record and (
        not isinstance(record["boot_id"], str) or not re.fullmatch(r"[a-f0-9]{32}", record["boot_id"])
    ):
        return False
    if phase == "starting":
        return record.keys() == {"phase", "resource"}
    if phase == "stopped":
        return record.keys() <= {"phase", "resource", "cooldown_since", "boot_id"} and timestamp("cooldown_since")
    if "launched_at_ns" in record and (type(record["launched_at_ns"]) is not int or record["launched_at_ns"] <= 0):
        return False
    if "stop_requested_at" in record:
        if phase not in ("stopping", "stop_acknowledged") or not timestamp("stop_requested_at"):
            return False
    if "stop_acknowledged_at" in record:
        if phase != "stop_acknowledged" or not timestamp("stop_acknowledged_at"):
            return False
    return (phase in ("active", "stopping", "stop_acknowledged")
            and digest("endpoint") and "headless" in record
            and (record["headless"] is None or type(record["headless"]) is bool))


def _user_profile_directory() -> Path:
    if os.name == "nt":
        from utils.windows_profile_security import user_profile_directory
        return user_profile_directory()
    import pwd
    return Path(pwd.getpwuid(os.geteuid()).pw_dir)


class ProfileStore:
    """Only lock files are permanent. Replacing one could split its kernel lock."""

    def __init__(self, provider: str, profile_id: str):
        home = _user_profile_directory()
        if not home.is_absolute():
            raise PermissionError("无法确认当前用户的主目录。")
        if os.name == "nt":
            from utils.windows_profile_security import check_private
            check_private(home)
        else:
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
                if _valid_record(record):
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
