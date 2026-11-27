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
    # An exported offline installer must verify the native target without its
    # approved-discovery companion or a target supplied by the environment.
    installer = tmp_path / "bootstrap.sh"
    installer.write_bytes((DESKTOP / "bootstrap.sh").read_bytes())
    try_install = subprocess.run(["/bin/sh", installer, SHA, digest, tmp_path, root],
                                 capture_output=True, text=True, env={"HOME": str(tmp_path), "target": "windows-x86_64"})
    assert try_install.returncode != 0
    assert "unsafe package member" in try_install.stderr.lower()
    assert not (root / "program").exists()
    assert not (tmp_path / "escaped").exists()


@pytest.mark.parametrize("unsafe", [False, True])
def test_windows_installer_extracts_only_verified_regular_files(tmp_path, unsafe):
    import shutil
    from desktop.build import pack
    pwsh = os.environ.get("SAU_TEST_PWSH") or shutil.which("pwsh") or shutil.which("powershell")
    if not pwsh:
        pytest.skip("PowerShell is required for the Windows bootstrap fixture")
    runtime = tmp_path / "private runtime"
    runtime.mkdir()
    (runtime / "python.exe").write_bytes(b"Windows interpreter fixture")
    package = pack(tmp_path / "out", runtime, SHA, "windows-x86_64", "0.1.0")
    if unsafe:
        with zipfile.ZipFile(package, "a") as archive:
            archive.writestr("runtime/../outside", b"x")
    stage = tmp_path / "selected path with spaces"
    stage.mkdir()
    runner = tmp_path / "extract.ps1"
    runner.write_text("$ErrorActionPreference='Stop'\n. $args[0]\nExpand-DesktopPackage $args[1] $args[2]\n")
    result = subprocess.run([pwsh, "-NoProfile", "-NonInteractive", "-File", runner,
                             DESKTOP / "expand-package.ps1", package, stage],
                            env={**os.environ, "HOME": str(tmp_path), "POWERSHELL_TELEMETRY_OPTOUT": "1"},
                            capture_output=True, text=True)
    if unsafe:
        assert result.returncode != 0 and "Unsafe package member" in result.stderr
        assert list(stage.iterdir()) == []
    else:
        assert result.returncode == 0, result.stderr
        assert (stage / "runtime/python.exe").read_bytes() == b"Windows interpreter fixture"


@pytest.mark.parametrize("custom", [False, True])
def test_windows_bootstrap_checks_digest_and_cleans_its_selected_root(tmp_path, custom):
    import shutil
    from desktop.build import pack
    pwsh = os.environ.get("SAU_TEST_PWSH") or shutil.which("pwsh") or shutil.which("powershell")
    if not pwsh:
        pytest.skip("PowerShell is required for the Windows bootstrap fixture")
    runtime = tmp_path / "prepared"
    runtime.mkdir()
    (runtime / "python.exe").write_bytes(b"Windows binary fixture")
    package = pack(tmp_path / "artifacts", runtime, SHA, "windows-x86_64", "0.1.0")
    root = tmp_path / ("User's chosen root" if custom else "Local App Data/social-auto-upload")
    env = {**os.environ, "HOME": str(tmp_path), "LOCALAPPDATA": str(tmp_path / "Local App Data"),
           "PROCESSOR_ARCHITECTURE": "AMD64", "PROCESSOR_ARCHITEW6432": "", "POWERSHELL_TELEMETRY_OPTOUT": "1"}
    args = [pwsh, "-NoProfile", "-NonInteractive", "-File", DESKTOP / "bootstrap.ps1",
            "-Revision", SHA, "-ArtifactDir", package.parent, "-Sha256", "a" * 64]
    if custom:
        args.extend(["-InstallRoot", root])
    result = subprocess.run(args, env=env, capture_output=True, text=True)
    assert result.returncode != 0 and "Package SHA-256 mismatch" in result.stderr
    assert root.is_dir() and list(root.iterdir()) == []
