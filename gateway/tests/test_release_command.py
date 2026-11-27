"""Exercise the operator's executable against a restarted local Gateway."""
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time
import zipfile
from contextlib import contextmanager

import uvicorn

from sau_gateway.app import create_app

ROOT = Path(__file__).resolve().parents[2]
CLI = [sys.executable, ROOT / "desktop/release.py"]


def test_environment_is_checked_before_contacting_gateway():
    for args, reason in (([], "--env"), (["--env", "uat"], "disabled"), (["--env", "prod"], "disabled"),
                         (["--env", "qa"], "invalid choice")):
        attempt = subprocess.run([*CLI, "worker", *args], capture_output=True, text=True, env={"PATH": os.defpath})
        assert attempt.returncode and reason in attempt.stderr


@contextmanager
def serving():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        sock.listen()
        server = uvicorn.Server(uvicorn.Config(create_app(), access_log=False, log_level="error"))
        thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]})
        thread.start()
        try:
            deadline = time.monotonic() + 5
            while not server.started and time.monotonic() < deadline:
                time.sleep(.01)
            assert server.started
            yield "http://127.0.0.1:" + str(sock.getsockname()[1])
        finally:
            server.should_exit = True
            thread.join(5)


def run(env, *args):
    return subprocess.run([*CLI, *args], env=env, text=True, capture_output=True, timeout=20)


def test_selected_commit_exact_checksums_and_status_after_terminal_exit(tmp_path, gateway_env):
    revision = subprocess.check_output(["git", "-C", ROOT, "rev-parse", "HEAD"], text=True).strip()
    file = tmp_path / f"sau-desktop-{revision}-macos-arm64.zip"
    with zipfile.ZipFile(file, "w") as archive:
        archive.writestr("release.json", json.dumps(dict(schema=1, revision=revision, target="macos-arm64", version="0.1.0")))
        archive.writestr("runtime/bin/python3.11", "fixture")
        archive.writestr("runtime/lib/python3.11/site-packages/sau_worker/__init__.py", "fixture")
        archive.writestr("runtime/lib/python3.11/site-packages/sau_cli.py", "fixture")
    env = {"PATH": os.environ["PATH"], "GATEWAY_INTERNAL_TOKEN": "fixture-internal"}
    command = ["worker", "--env", "dev", "--ref", revision, "--artifacts", str(tmp_path)]
    with serving() as url:
        env["SAU_RELEASE_GATEWAY_URL"] = url
        file.with_suffix(".sha256").write_text("0" * 64 + "  " + file.name + "\n")
        bad = run(env, *command)
        assert bad.returncode and "SHA-256" in bad.stderr
        file.with_suffix(".sha256").write_text(hashlib.sha256(file.read_bytes()).hexdigest() + "  " + file.name + "\n")
        completed = run(env, *command)
        assert completed.returncode == 0, completed.stderr
        summary = json.loads(completed.stdout)
        assert summary["revision"] == revision
    with serving() as url:
        env["SAU_RELEASE_GATEWAY_URL"] = url
        again = run(env, "status", "--env", "dev", "--release-id", summary["releaseId"])
        assert again.returncode == 0, again.stderr
        assert json.loads(again.stdout)["packages"] == summary["packages"]
