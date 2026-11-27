import hashlib
import os
from pathlib import Path
import platform
import stat
import subprocess
import zipfile

import pytest

from desktop.tests.test_package import SHA


DESKTOP = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(platform.system() != "Darwin", reason="macOS native bootstrap")
@pytest.mark.parametrize("name,mode", [
    ("../escaped", stat.S_IFREG), ("runtime/link", stat.S_IFLNK),
    ("runtime/../escaped", stat.S_IFREG), ("runtime/bad\\escape", stat.S_IFREG),
])
def test_pinned_but_unsafe_package_does_not_change_live_install(tmp_path, name, mode):
    target = "macos-" + platform.machine()
    archive = tmp_path / f"sau-desktop-{SHA}-{target}.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        info = zipfile.ZipInfo(name)
        info.external_attr = (mode | 0o755) << 16
        bundle.writestr(info, "outside")
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    root = tmp_path / "Selected Install"
    try_install = subprocess.run(["/bin/sh", DESKTOP / "bootstrap.sh", SHA, digest, tmp_path, root],
                                 capture_output=True, text=True, env={"HOME": str(tmp_path)})
    assert try_install.returncode != 0
    assert "unsafe package member" in try_install.stderr.lower()
    assert not (root / "program").exists()
    assert not (tmp_path / "escaped").exists()
