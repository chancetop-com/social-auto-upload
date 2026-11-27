"""Check the extended ACLs that macOS enforces in addition to POSIX modes."""
import ctypes
import errno
import os
from pathlib import Path

_libc = ctypes.CDLL(None, use_errno=True)
_libc.acl_get_file.argtypes = (ctypes.c_char_p, ctypes.c_int)
_libc.acl_get_file.restype = ctypes.c_void_p
_libc.acl_to_text.argtypes = (ctypes.c_void_p, ctypes.c_void_p)
_libc.acl_to_text.restype = ctypes.c_void_p
_libc.acl_free.argtypes = (ctypes.c_void_p,)
_ACL_TYPE_EXTENDED = 0x100  # Darwin <sys/acl.h>
_HOME_READ_RIGHTS = {b"read", b"list", b"search", b"execute", b"readattr",
                     b"readextattr", b"readsecurity", b"synchronize"}


def check_private(path: Path, *, home: bool = False) -> None:
    acl = _libc.acl_get_file(os.fsencode(path), _ACL_TYPE_EXTENDED)
    if not acl:
        error = ctypes.get_errno()
        if error == errno.ENOENT:  # A verified existing path has no extended ACL.
            return
        raise OSError(error, os.strerror(error))
    try:
        text = _libc.acl_to_text(acl, None)
        if not text:
            error = ctypes.get_errno()
            raise OSError(error, os.strerror(error))
        try:
            entries = ctypes.string_at(text).splitlines()
        finally:
            _libc.acl_free(text)
    finally:
        _libc.acl_free(acl)

    if not entries or entries[0] != b"!#acl 1":
        raise PermissionError("无法确认托管会话目录的访问权限。")
    for entry in entries[1:]:
        # Darwin text entries end in numeric ID, action/inheritance flags and rights.
        fields = entry.rsplit(b":", 3)
        if len(fields) != 4:
            raise PermissionError("无法确认托管会话目录的访问权限。")
        principal, numeric_id, flags, rights = fields
        action = flags.split(b",", 1)[0]
        if action == b"deny":
            continue
        if action == b"allow":
            if principal.startswith(b"user:") and numeric_id == str(os.geteuid()).encode():
                continue
            if home and set(rights.split(b",")) <= _HOME_READ_RIGHTS:
                continue
        raise PermissionError("托管会话路径的访问控制列表允许其他用户访问。")
