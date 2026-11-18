"""Simulate the native POSIX account database in disposable CLI installations."""
import os
import pwd


lookup = pwd.getpwuid


def getpwuid(uid):
    entry = lookup(uid)
    if uid == os.geteuid():
        return pwd.struct_passwd((*entry[:5], os.environ["OFFLINE_OS_PROFILE"], *entry[6:]))
    return entry


pwd.getpwuid = getpwuid
