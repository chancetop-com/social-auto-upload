"""Windows filesystem primitives for the per-user managed Profile store."""

from ctypes import WinError
import msvcrt
from pathlib import Path

import ntsecuritycon
import pywintypes
import win32api
import win32con
import win32file
import win32security
import winerror


def _user_sid():
    token = win32security.OpenProcessToken(win32api.GetCurrentProcess(), win32con.TOKEN_QUERY)
    try:
        return win32security.GetTokenInformation(token, win32security.TokenUser)[0]
    finally:
        token.Close()


def private_mkdir(path: Path) -> None:
    """Create or validate one private directory without exposing it during creation."""
    try:
        owner = win32security.ConvertSidToStringSid(_user_sid())
        security = win32security.SECURITY_ATTRIBUTES()
        # P blocks parent grants. OICI propagates full access to files and directories.
        sddl = f"O:{owner}D:P(A;OICI;FA;;;{owner})(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)"
        security.SECURITY_DESCRIPTOR = win32security.ConvertStringSecurityDescriptorToSecurityDescriptor(
            sddl, win32security.SDDL_REVISION_1
        )
        win32file.CreateDirectory(str(path), security)
    except pywintypes.error as exc:
        if exc.winerror != winerror.ERROR_ALREADY_EXISTS:
            raise WinError(exc.winerror) from None
    if not _private_attributes(path) & win32con.FILE_ATTRIBUTE_DIRECTORY:
        raise NotADirectoryError("托管会话存储路径必须是目录。")


def _private_attributes(path: Path) -> int:
    try:
        # Inspect the reparse point itself and read the ACL from that same handle.
        handle = win32file.CreateFile(
            str(path), win32con.READ_CONTROL | ntsecuritycon.FILE_READ_ATTRIBUTES,
            win32con.FILE_SHARE_READ | win32con.FILE_SHARE_WRITE | win32con.FILE_SHARE_DELETE,
            None, win32con.OPEN_EXISTING,
            win32file.FILE_FLAG_OPEN_REPARSE_POINT | win32con.FILE_FLAG_BACKUP_SEMANTICS, None,
        )
        try:
            attrs = win32file.GetFileInformationByHandle(handle)[0]
            if attrs & win32con.FILE_ATTRIBUTE_REPARSE_POINT:
                raise PermissionError("托管会话路径不能使用重解析点。")
            descriptor = win32security.GetSecurityInfo(
                handle, win32security.SE_FILE_OBJECT,
                win32security.OWNER_SECURITY_INFORMATION | win32security.DACL_SECURITY_INFORMATION,
            )
        finally:
            handle.Close()
        user = _user_sid()
        acl = descriptor.GetSecurityDescriptorDacl()
        if descriptor.GetSecurityDescriptorOwner() != user or acl is None:
            raise PermissionError("托管会话路径必须由当前用户拥有并受到访问控制保护。")
        trustees = (
            user,
            win32security.CreateWellKnownSid(win32security.WinLocalSystemSid),
            win32security.CreateWellKnownSid(win32security.WinBuiltinAdministratorsSid),
        )
        for index in range(acl.GetAceCount()):
            ace = acl.GetAce(index)
            kind = ace[0][0]
            if kind == win32security.ACCESS_DENIED_ACE_TYPE:
                continue
            if kind != win32security.ACCESS_ALLOWED_ACE_TYPE or ace[2] not in trustees:
                raise PermissionError("托管会话路径的访问权限不安全。")
        return attrs
    except pywintypes.error as exc:
        raise WinError(exc.winerror) from None
    except NotImplementedError:
        raise PermissionError("无法确认托管会话路径的访问权限。") from None


def check_private(path: Path) -> None:
    """Verify current ownership and every effective or inheritable access grant."""
    _private_attributes(path)


def try_lock(fd: int) -> bool:
    """Reserve byte zero without waiting, until the caller closes its fd."""
    try:
        win32file.LockFile(msvcrt.get_osfhandle(fd), 0, 0, 1, 0)
    except pywintypes.error as exc:
        if exc.winerror == winerror.ERROR_LOCK_VIOLATION:
            return False
        raise WinError(exc.winerror) from None
    return True
