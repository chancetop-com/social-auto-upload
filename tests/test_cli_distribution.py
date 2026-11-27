"""Smoke-test the installed wheel, with no source checkout on its import path."""
import json
from importlib.metadata import distributions
import os
from pathlib import Path
import subprocess

from tests.remote_media_cli import origin


def test_installed_entry_starts_outside_checkout(install_cli, tmp_path):
    sau, packages = install_cli(tmp_path / "worker install")
    env = {**os.environ, "PYTHONPATH": "", "SAU_HOME": "", "HOME": str(tmp_path), "USERPROFILE": str(tmp_path)}
    cli, = (dist for dist in distributions(path=[str(packages)])
            if dist.metadata["Name"] == "social-auto-upload")
    version = subprocess.run([sau, "--version"], cwd=tmp_path, env=env,
                             capture_output=True, text=True, check=True, timeout=30)
    assert version.stdout.strip() == f"sau {cli.version}"
    result = subprocess.run([sau, "article", "themes"], cwd=tmp_path, env=env,
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert "modern" in result.stdout


def test_relocated_runtime_uses_operator_config_for_media(install_cli, tmp_path, origin):
    staging = tmp_path / "staging"
    sau, _ = install_cli(staging)
    release = staging.rename(tmp_path / "release with spaces")
    python = release / sau.parent.relative_to(staging) / ("python.exe" if os.name == "nt" else "python")

    config = tmp_path / "config"
    config.mkdir()
    media_store = tmp_path / "operator data"
    media_store.mkdir()
    (config / "conf.py").write_text(
        f"from pathlib import Path\nBASE_DIR = Path({str(media_store)!r})\n",
        encoding="utf-8",
    )
    base, assets, requests = origin
    assets["/video.mp4"] = (200, b"test video")
    result = subprocess.run(
        [python, "-I", "-m", "sau_cli", "media", "predownload", "--wait",
         "--task-id", "scheduled", "--urls", base + "/video.mp4"],
        cwd=tmp_path, env={**os.environ, "SAU_HOME": str(config), "NO_PROXY": "127.0.0.1"},
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    receipt = json.loads(result.stdout)
    assert receipt["status"] == "ready" and receipt["task_id"] == "scheduled"
    path = Path(receipt["items"][0]["path"])
    assert path.parent == media_store / "downloads" / "scheduled"
    assert path.read_bytes() == b"test video"
    assert requests == ["/video.mp4"]
