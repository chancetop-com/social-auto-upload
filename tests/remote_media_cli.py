"""Predownload contract as observed by a caller and its local media origin."""
import os
from pathlib import Path
import shutil
import subprocess
import sysconfig
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import pytest


PROJECT = Path(__file__).resolve().parents[1]


def _launcher(tmp_path):
    shutil.copyfile(PROJECT / "conf.example.py", tmp_path / "conf.py")
    env = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join(map(str, (tmp_path, PROJECT))),
        "MLX_API_TOKEN": "",
        "ADSPOWER_API_KEY": "",
        "NO_PROXY": "127.0.0.1",
    }
    env.pop("SAU_DOWNLOAD_CONCURRENCY", None)
    executable = shutil.which("sau", path=sysconfig.get_path("scripts"))
    assert executable, "Install the project to run the sau CLI tests"

    def launch(*args, **environment):
        return subprocess.Popen(
            [executable, *args],
            cwd=tmp_path, env={**env, **environment}, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )

    return launch


@pytest.fixture
def sau_cli(tmp_path):
    return _launcher(tmp_path)


@pytest.fixture
def media_cli(tmp_path):
    launch = _launcher(tmp_path)
    return lambda *args, **env: launch("media", "predownload", *args, **env)


@pytest.fixture
def set_publish_clock(tmp_path):
    """Advance only the platform's monotonic budget across CLI processes."""
    clock = tmp_path / "monotonic"

    def set_time(seconds):
        pending = clock.with_suffix(".tmp")
        pending.write_text(str(seconds))
        pending.replace(clock)

    set_time(0)
    (tmp_path / "sitecustomize.py").write_text("""
from pathlib import Path
from types import SimpleNamespace
from uploader import publish_timeout
clock = Path(__file__).with_name("monotonic")
publish_timeout.time = SimpleNamespace(monotonic=lambda: float(clock.read_text()))
""")
    return set_time


@pytest.fixture
def origin():
    assets = {}
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append(self.path)
            asset = assets.get(self.path, (404, b""))
            if callable(asset):
                return asset(self)
            status, body = asset
            self.send_response(status)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield f"http://127.0.0.1:{server.server_port}", assets, requests
        finally:
            server.shutdown()
            thread.join()
