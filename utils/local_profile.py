"""Local browser Profile ownership, exclusive use and explicit reset.

The raw account leaf at browser-kind/platform/account is the user data directory.
Ownership, OS locks and reset markers live in a separate .guards tree, so reset
never deletes its own guard and internal filenames never reserve account aliases.
The brief layout lock protects only directory/ownership initialization; each
browser lifetime has its own nonblocking lock. Filesystem spelling equivalence is resolved by the filesystem,
then checked against the original alias in metadata, never by normalizing it.
"""
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from datetime import datetime, timezone
import json
import os
import shutil
import stat

import conf
from utils.errors import UsageError


BROWSER_PLATFORMS = frozenset({
    "tiktok", "rednote", "instagram", "xiaohongshu", "youtube", "facebook", "facebook-page",
    "douyin", "kuaishou", "tencent", "baijiahao", "weibo", "hupu", "alipay", "dayu", "zhihu", "xueqiu",
})


@dataclass(frozen=True)
class LocalProfile:
    path: Path
    exists: bool
    guard_path: Path


@contextmanager
def acquire_local_profile(platform: str, account: str, browser_kind: str, *, root=None, create=False):
    """Hold exclusive ownership for a session's complete browser lifetime.

    ``create`` is reserved for login. Missing Profiles otherwise yield
    ``exists=False`` so the caller can request login without opening a browser.
    Existence only proves initialized ownership, never platform authentication.
    """
    with _acquire_profile(platform, account, browser_kind, root=root, create=create) as profile:
        yield profile


@contextmanager
def _acquire_profile(platform, account, browser_kind, *, root=None, create=False, resetting=False):
    if platform not in BROWSER_PLATFORMS:
        raise UsageError(f"不支持本地浏览器 Profile 的平台: {platform}")
    if not isinstance(account, str) or not account.strip() or account in (".", "..") or any(c in account for c in ("/", "\\", "\x00")):
        raise UsageError("账号别名不能为空白、点目录或包含路径分隔符/NUL；原值不会被修改。")
    if os.name == "nt" and (PureWindowsPath(account).drive or PureWindowsPath(account).is_reserved()
                             or account.endswith((" ", ".")) or ":" in account):
        raise UsageError("当前文件系统不能无损保留此账号别名；请使用其他别名。")
    if browser_kind not in ("chrome", "chromium"):
        raise UsageError("browser-kind 必须为 chrome 或 chromium。")
    root = Path(root or Path(conf.BASE_DIR) / "browser_profiles")
    _check_directory_path(root)
    root = root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    # Account names occur only as directory leaves in both namespaces. No
    # internal file shares a directory with arbitrary account aliases.
    with _file_lock(root / ".layout.lock", blocking=True):
        guards = root / ".guards"
        guard_kind = guards / browser_kind
        guard_platform = guard_kind / platform
        for directory in (guards, guard_kind, guard_platform):
            _check_directory_path(directory)
            directory.mkdir(exist_ok=True)
        kind_dir = root / browser_kind
        owner = {"browser_kind": browser_kind}
        _owned_directory(kind_dir, owner, create=True, metadata=root / f".{browser_kind}.owner.json")
        platform_dir = kind_dir / platform
        owner = {**owner, "platform": platform}
        _owned_directory(platform_dir, owner, create=True,
                         metadata=guard_kind / f".{platform}.owner.json")
        guard = guard_platform / account
        owner = {**owner, "account": account}
        _owned_directory(guard, owner, create=True)
    path = platform_dir / account
    with _file_lock(guard / "profile.lock"):
        marker = guard / "resetting.json"
        metadata = guard / "profile.owner.json"
        _check_directory_path(path)
        if marker.exists() or marker.is_symlink():
            _check_owner(marker, owner)
            if not resetting:
                raise RuntimeError(f"Profile 重建未完成，必须重跑 reset-profile: {path}")
            # A retry may follow deletion of the data or its ownership record;
            # any surviving ownership record must still match this identity.
            if metadata.exists() or metadata.is_symlink():
                _check_owner(metadata, owner)
        else:
            _owned_directory(path, owner, create=create, metadata=metadata)
        _check_browser_ownership(path)
        yield LocalProfile(path, path.exists(), guard)


@contextmanager
def _file_lock(path: Path, *, blocking: bool = False):
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
    if path.is_symlink():
        raise RuntimeError(f"Profile 锁路径不能为符号链接: {path}")
    fd = os.open(path, flags, 0o600)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise RuntimeError(f"Profile 锁路径不是独立普通文件: {path}")
        if os.name == "nt":
            import msvcrt
            if info.st_size == 0:
                os.write(fd, b" ")
            os.lseek(fd, 0, os.SEEK_SET)
            operation = msvcrt.LK_LOCK if blocking else msvcrt.LK_NBLCK
            try:
                msvcrt.locking(fd, operation, 1)
            except OSError as exc:
                raise RuntimeError(f"Profile 已被项目进程占用或无法取得互斥: {path} ({exc})") from exc
        else:
            import fcntl
            operation = fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB)
            try:
                fcntl.flock(fd, operation)
            except OSError as exc:
                raise RuntimeError(f"Profile 已被项目进程占用或无法取得互斥: {path} ({exc})") from exc
        # This record is diagnostic only: neither its existence nor PID is
        # consulted when deciding whether this Profile is occupied.
        record = json.dumps({"pid": os.getpid(), "acquired_at": datetime.now(timezone.utc).isoformat()})
        os.lseek(fd, 0, os.SEEK_SET)
        os.write(fd, record.encode())
        os.ftruncate(fd, len(record))
        yield
    finally:
        os.close(fd)


def _check_browser_ownership(path: Path):
    # POSIX Chromium uses Singleton* links; Windows uses a delete-on-close
    # lockfile. A leftover browser artifact cannot establish that deletion is
    # safe. Do not unlink it, signal its PID, or ask a browser to take it over.
    for name in ("SingletonLock", "SingletonSocket", "SingletonCookie", "lockfile"):
        artifact = path / name
        try:
            artifact.lstat()
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise RuntimeError(f"无法安全确认外部浏览器占用: {artifact} ({exc})") from exc
        raise RuntimeError(
            f"检测到浏览器占用或残留 singleton 状态，无法安全确认 Profile 可用: {artifact}；"
            "请先关闭使用该 Profile 的外部浏览器并检查残留状态。不会自动清锁或接管。"
        )


def _check_directory_path(path: Path):
    try:
        info = path.lstat()
    except FileNotFoundError:
        return
    # On Windows, junctions are reparse points but need not be symbolic links.
    reparse = getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    if not stat.S_ISDIR(info.st_mode) or reparse:
        raise RuntimeError(f"Profile 路径必须是专用真实目录，不能为符号链接、junction 或文件: {path}")


def _owned_directory(path: Path, owner: dict, *, create: bool, metadata: Path | None = None):
    _check_directory_path(path)
    metadata = metadata if metadata is not None else path / ".sau-owner.json"
    if metadata.is_symlink():
        raise RuntimeError(f"Profile 归属元数据不能为符号链接: {metadata}")
    if path.exists() or metadata.exists():
        _check_owner(metadata, owner)
    if not path.exists() and create:
        path.mkdir()
        metadata.write_text(json.dumps(owner, ensure_ascii=False), encoding="utf-8")


def _check_owner(metadata: Path, owner: dict):
    if metadata.is_symlink():
        raise RuntimeError(f"Profile 归属元数据不能为符号链接: {metadata}")
    try:
        info = metadata.lstat()
        if not stat.S_ISREG(info.st_mode):
            raise RuntimeError(f"Profile 归属元数据必须是普通文件: {metadata}")
        actual = json.loads(metadata.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RuntimeError(f"Profile 归属元数据缺失或损坏: {metadata} ({exc})") from exc
    if actual != owner:
        raise RuntimeError(f"Profile 归属冲突: {metadata}")


def reset_local_profile(platform: str, account: str, browser_kind: str, *, root=None) -> Path:
    with _acquire_profile(platform, account, browser_kind, root=root, resetting=True) as profile:
        marker = profile.guard_path / "resetting.json"
        try:
            if profile.exists:
                if not marker.exists():
                    marker.write_text(json.dumps({"platform": platform, "account": account,
                                                  "browser_kind": browser_kind}, ensure_ascii=False),
                                      encoding="utf-8")
                shutil.rmtree(profile.path)
            (profile.guard_path / "profile.owner.json").unlink(missing_ok=True)
            marker.unlink(missing_ok=True)
        except OSError as exc:
            raise RuntimeError(f"Profile 重建未完成: {profile.path}；修复后重跑 reset-profile ({exc})") from exc
        return profile.path
