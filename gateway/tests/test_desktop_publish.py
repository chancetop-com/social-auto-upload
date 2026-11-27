"""Run the worker entry point against a live Gateway and a controlled private CLI."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time
import venv

import httpx
import uvicorn

from sau_gateway.app import create_app
from test_publish_api import INTERNAL, postiz, video


@contextmanager
def live_gateway():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        server = uvicorn.Server(uvicorn.Config(create_app(), log_level="error"))
        thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
        thread.start()
        try:
            deadline = time.monotonic() + 5
            while not server.started:
                assert thread.is_alive() and time.monotonic() < deadline
                time.sleep(.01)
            yield "http://127.0.0.1:" + str(listener.getsockname()[1])
        finally:
            server.should_exit = True
            thread.join(timeout=5)
            assert not thread.is_alive()


def test_worker_run_invokes_paired_process_once_and_records_edited_occurrence(postiz, gateway_env, tmp_path):
    root = tmp_path / "private fixture CLI"
    venv.EnvBuilder(with_pip=False).create(root)
    python = root / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    packages = Path(subprocess.check_output([python, "-I", "-c",
                    "import sysconfig; print(sysconfig.get_path('purelib'))"], text=True).strip())
    calls = tmp_path / "calls.jsonl"
    (packages / "sau_cli.py").write_text(
        "import json, sys\n"
        "if sys.argv[1:] == ['--version']:\n"
        "    print('sau 0.1.0')\n"
        "else:\n"
        f"    with open({str(calls)!r}, 'a', encoding='utf-8') as out:\n"
        "        print(json.dumps(sys.argv[1:]), file=out)\n"
        "    print('TikTok video upload submitted: controlled.mp4')\n",
        encoding="utf-8")
    task = video("temporal-repeating-414")
    postiz[1]["task"] = {**task, "caption": "edited before start", "earliestPublishAt": "2026-11-28T01:00:00Z"}
    with live_gateway() as url, httpx.Client(base_url=url, headers=INTERNAL, trust_env=False) as api:
        assert api.post("/internal/occurrences", json=task).json()["state"] == "pending"
        env = {key: os.environ[key] for key in ("PATH", "SystemRoot") if key in os.environ}
        env.update({"HOME": str(tmp_path), "SAU_CLI_PYTHON": str(python), "SAU_DESKTOP_TOKEN": "fixture-desktop",
                    "SAU_DEV_CHROME_ALIASES": "operator-selected,operator-approved", "SAU_GATEWAY_URL": url})
        worker = subprocess.Popen([sys.executable, "-m", "sau_worker", "run"], env=env,
                                  cwd=Path(__file__).resolve().parents[2] / "cli-service")
        try:
            deadline = time.monotonic() + 8
            while True:
                record = api.get("/internal/occurrences/" + task["workflowId"]).json()
                if record["receipt"]:
                    break
                assert worker.poll() is None and time.monotonic() < deadline, record["state"]
                time.sleep(.02)
            assert record["state"] == "succeeded" and record["sessionId"]
            assert record["receipt"] == {"cliInvoked": True, "outcome": "published", "exitCode": 0}
            assert api.post("/internal/occurrences", json=task).json() == record
            argv, = [json.loads(line) for line in calls.read_text().splitlines()]
            assert argv[:2] == ["tiktok", "upload-video"]
            assert "--title=edited before start" in argv and "--account=operator-approved" in argv
            assert "--not-before=2026-11-28T01:00:00Z" in argv
            assert len(postiz[0]) == 1
        finally:
            worker.terminate()
            worker.wait(timeout=5)
