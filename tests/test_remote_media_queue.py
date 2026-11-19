"""Background predownload as observed by separate callers and a local HTTP origin."""
import json
from pathlib import Path
import subprocess
from threading import Condition, Event

import pytest

from tests.remote_media_cli import media_cli, origin


def test_accepted_process_exits_and_a_waiter_shares_its_transfer(media_cli, origin):
    base, assets, requests = origin
    started = Event()
    release = Event()

    def slow(handler):
        handler.send_response(200)
        handler.send_header("Content-Length", "5")
        handler.end_headers()
        started.set()
        if release.wait(15):
            handler.wfile.write(b"video")

    assets["/video"] = slow
    args = ("--task-id", "draft", "--urls", base + "/video")
    try:
        submitted = media_cli(*args)
        stdout, stderr = submitted.communicate(timeout=8)
        assert submitted.returncode == 0, stderr
        assert json.loads(stdout) == {"task_id": "draft", "status": "accepted"}
        assert started.wait(5)
        waiting = media_cli("--wait", *args)
        # The server is withholding the body while the second caller starts.
        with pytest.raises(subprocess.TimeoutExpired):
            waiting.communicate(timeout=1)
    finally:
        release.set()
    stdout, stderr = waiting.communicate(timeout=8)
    assert waiting.returncode == 0, stderr
    item, = json.loads(stdout)["items"]
    assert Path(item["path"]).read_bytes() == b"video"
    assert requests == ["/video"]

@pytest.mark.parametrize(("configured", "limit"), [(None, 1), ("2", 2)])
def test_one_worker_shares_its_startup_limit_across_ids(media_cli, origin, configured, limit):
    base, assets, requests = origin
    changed = Condition()
    release = Event()
    count = 0
    peak = 0

    def held(handler):
        nonlocal count, peak
        with changed:
            count += 1
            peak = max(peak, count)
            changed.notify_all()
        try:
            handler.send_response(200)
            handler.send_header("Content-Length", "1")
            handler.end_headers()
            if release.wait(15):
                handler.wfile.write(b"x")
        finally:
            with changed:
                count -= 1

    assets.update({"/a": held, "/b": held, "/c": held})
    env = {"SAU_DOWNLOAD_CONCURRENCY": configured} if configured else {}
    try:
        for path in ("a", "b", "c"):
            # Later submitters have their own config. The live worker keeps
            # its original limit until all three distinct requests are done.
            caller = media_cli("--task-id", path, "--urls", base + "/" + path, **env)
            stdout, stderr = caller.communicate(timeout=8)
            assert caller.returncode == 0 and json.loads(stdout)["status"] == "accepted", stderr
            env = {"SAU_DOWNLOAD_CONCURRENCY": "3"}
        with changed:
            assert changed.wait_for(lambda: peak >= limit, timeout=3)
            assert not changed.wait_for(lambda: peak > limit, timeout=0.3)
    finally:
        release.set()
    for path in ("a", "b", "c"):
        caller = media_cli("--wait", "--task-id", path, "--urls", base + "/" + path)
        stdout, stderr = caller.communicate(timeout=8)
        assert caller.returncode == 0, stderr
        item, = json.loads(stdout)["items"]
        assert Path(item["path"]).read_bytes() == b"x"
    assert sorted(requests) == ["/a", "/b", "/c"]

    # After draining the same root, the next launch reads a new limit.
    release.clear()
    peak = 0
    assets.update({"/d": held, "/e": held, "/f": held})
    try:
        next_batch = media_cli("--wait", "--task-id", "next", "--urls",
                               *(base + "/" + path for path in "def"), SAU_DOWNLOAD_CONCURRENCY="3")
        with changed:
            assert changed.wait_for(lambda: peak == 3, timeout=5)
    finally:
        release.set()
    stdout, stderr = next_batch.communicate(timeout=8)
    assert next_batch.returncode == 0, stderr
    assert json.loads(stdout)["status"] == "ready"


@pytest.mark.parametrize("configured", ["0", "-2", "two", "1.5", ""])
def test_invalid_concurrency_is_a_usage_error_before_queue_creation(media_cli, tmp_path, configured):
    caller = media_cli("--task-id", "post", "--urls", "http://127.0.0.1:1/video",
                       SAU_DOWNLOAD_CONCURRENCY=configured)
    stdout, stderr = caller.communicate(timeout=8)
    assert caller.returncode == 2
    assert not stdout and "SAU_DOWNLOAD_CONCURRENCY" in stderr
    assert not (tmp_path / "downloads").exists()


@pytest.mark.parametrize("failure", ["storage", "startup"])
def test_unavailable_queue_reports_a_single_failure_receipt(media_cli, tmp_path, failure):
    if failure == "storage":
        (tmp_path / "downloads").write_text("occupied")
    else:
        # The scheduler can load its config; a newly launched Python process
        # in the same environment cannot. This exercises a real startup failure.
        with (tmp_path / "conf.py").open("a") as config:
            config.write("\n(BASE_DIR / 'opened-once').touch(exist_ok=False)\n")
    caller = media_cli("--task-id", "post", "--urls", "http://127.0.0.1:1/video")
    stdout, stderr = caller.communicate(timeout=8)
    assert caller.returncode == 1, stderr
    assert json.loads(stdout) == {"task_id": "post", "status": "failed",
                                  "reason": "queue_unavailable", "items": []}


def test_task_id_cannot_occupy_queue_storage(media_cli, tmp_path):
    caller = media_cli("--task-id", ".SAU-Queue", "--urls", "http://127.0.0.1:1/video")
    stdout, stderr = caller.communicate(timeout=8)
    assert caller.returncode == 2
    assert not stdout and stderr.strip()
    assert not (tmp_path / "downloads").exists()


def test_case_alias_cannot_reuse_the_original_tasks_download(media_cli, origin, tmp_path):
    probe = tmp_path / "case-probe"
    probe.touch()
    if not probe.with_name("CASE-PROBE").exists():
        pytest.skip("Filesystem distinguishes case in pathnames")
    base, assets, requests = origin
    assets["/video"] = (200, b"original")
    args = ("--wait", "--urls", base + "/video", "--task-id")
    first = media_cli(*args, "post-A")
    stdout, stderr = first.communicate(timeout=8)
    assert first.returncode == 0, stderr
    original = Path(json.loads(stdout)["items"][0]["path"])
    second = media_cli(*args, "post-a")
    stdout, stderr = second.communicate(timeout=8)
    assert second.returncode != 0
    assert "path" not in stdout
    assert original.read_bytes() == b"original" and requests == ["/video"]
