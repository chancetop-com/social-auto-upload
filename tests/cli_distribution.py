"""Install independent copies of the CLI wheel for process-level tests."""
import os
from pathlib import Path
import sys
import subprocess
import venv

import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def install_cli(tmp_path_factory):
    wheels = tmp_path_factory.mktemp("wheels")
    subprocess.run(["uv", "build", "--wheel", "--out-dir", wheels, ROOT], check=True)
    wheel, = wheels.glob("*.whl")

    def install(prefix):
        venv.EnvBuilder(with_pip=False).create(prefix)
        scripts = prefix / ("Scripts" if os.name == "nt" else "bin")
        python = scripts / ("python.exe" if os.name == "nt" else "python")
        subprocess.run(["uv", "pip", "install", "--python", python, "--no-deps", wheel], check=True)
        # Share third-party packages without enabling the source checkout's editable .pth.
        packages = Path(subprocess.check_output(
            [python, "-I", "-c", "import sysconfig; print(sysconfig.get_path('purelib'))"], text=True,
        ).strip())
        dependencies = [path for path in sys.path if Path(path).name in {"site-packages", "dist-packages"}]
        (packages / "test_dependencies.pth").write_text("\n".join(dependencies) + "\n")
        return scripts / ("sau.exe" if os.name == "nt" else "sau"), packages

    return install
