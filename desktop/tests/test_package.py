"""The release archive is a reproducible, target-specific artifact."""
import hashlib
import json
import stat
import zipfile
from pathlib import Path

import pytest

from desktop.build import pack


SHA = "d" * 40


def test_windows_package_is_pinned_to_revision_target_and_bytes(tmp_path):
    runtime = tmp_path / "private CPython"
    runtime.mkdir()
    (runtime / "python.exe").write_bytes(b"fixture PE")
    package = pack(tmp_path / "artifacts", runtime, SHA, "windows-x86_64", "0.1.0")
    assert package.name == f"sau-desktop-{SHA}-windows-x86_64.zip"
    first = package.read_bytes()
    assert package.with_suffix(".sha256").read_text().split()[0] == hashlib.sha256(first).hexdigest()
    with zipfile.ZipFile(package) as archive:
        assert archive.read("runtime/python.exe") == b"fixture PE"
        assert json.loads(archive.read("release.json")) == {
            "schema": 1, "revision": SHA, "target": "windows-x86_64", "version": "0.1.0"}
        assert all(stat.S_ISREG(i.external_attr >> 16) for i in archive.infolist())
    assert pack(package.parent, runtime, SHA, "windows-x86_64", "0.1.0").read_bytes() == first


def test_builder_rejects_an_unverified_runtime_before_using_it(tmp_path):
    import subprocess
    import sys
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    result = subprocess.run([sys.executable, Path(__file__).resolve().parents[1] / "build.py", "build",
                             "--runtime", runtime, "--runtime-sha256", "0" * 64, "--revision", SHA,
                             "--target", "windows-x86_64", "--out", tmp_path / "out"],
                            capture_output=True, text=True)
    assert result.returncode != 0
    assert "Runtime SHA-256 mismatch" in result.stderr
    assert not (tmp_path / "out").exists()


def test_native_package_records_only_shipped_entrypoints():
    import csv
    import io
    import os
    artifact = os.environ.get("SAU_TEST_DESKTOP_ARTIFACT")
    if not artifact:
        pytest.skip("set SAU_TEST_DESKTOP_ARTIFACT to a native package")
    with zipfile.ZipFile(artifact) as archive:
        names = set(archive.namelist())
        record, = (name for name in names
                   if name.endswith(".dist-info/RECORD") and "/social_auto_upload-" in name)
        site, metadata, _ = record.rsplit("/", 2)
        rows = csv.reader(io.StringIO(archive.read(record).decode()))
        files = {relative for relative, _, _ in rows}
        assert any(not path.startswith(metadata + "/") for path in files), "RECORD lists no CLI files"
        assert {f"{site}/{relative}" for relative in files} <= names
