"""The native login job stays outside the directory it replaces (including Windows DLLs)."""
from pathlib import Path

from .state import atomic_write


def write_host(root, *, windows):
    name = "release-host.ps1" if windows else "release-host.sh"
    host = root / name
    atomic_write(host, Path(__file__).with_name(name).read_text(encoding="utf-8"), executable=True)
    return host
