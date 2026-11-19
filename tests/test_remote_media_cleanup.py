"""Retention as observed through the installed CLI and its download root."""
import json
import os
from pathlib import Path
import signal
import subprocess
from threading import Event
import time

import pytest

from tests.remote_media_cli import origin, sau_cli
from tests.test_remote_media_recovery import worker_of


WEEK = 7 * 24 * 60 * 60
NOW = int(time.time())


def run(child):
    stdout, stderr = child.communicate(timeout=12)
    assert child.returncode == 0, (stdout, stderr)
    return stdout


def download(cli, task_id, url):
    response = run(cli("media", "predownload", "--wait", "--task-id", task_id, "--urls", url))
    return Path(json.loads(response)["items"][0]["path"])


def age(directory, seconds=WEEK):
    timestamp = NOW - seconds
    os.utime(directory, (timestamp, timestamp))


@pytest.mark.skipif(os.name == "nt", reason="Observes POSIX process termination")
def test_cleanup_releases_a_dead_waiter_after_its_worker_finished(tmp_path, sau_cli, origin):
    base, assets, requests = origin
    started, release = Event(), Event()

    def deliver(handler):
        started.set()
        release.wait(10)
        handler.send_response(200)
        handler.send_header("Content-Length", "4")
        handler.end_headers()
        handler.wfile.write(b"clip")

    assets["/clip"] = deliver
    waiter = sau_cli("media", "predownload", "--wait", "--task-id", "finished", "--urls", base + "/clip")
    directory = tmp_path / "downloads" / "finished"
    try:
        assert started.wait(6)
        waiter.send_signal(signal.SIGSTOP)
        worker = worker_of(waiter)
        release.set()
        deadline = time.monotonic() + 8
        while True:
            status = subprocess.run(["ps", "-o", "stat=", "-p", str(worker)], capture_output=True, text=True)
            if status.returncode or status.stdout.strip().startswith("Z"):
                break
            assert time.monotonic() < deadline
            time.sleep(.05)
        assert any(path.read_bytes() == b"clip" for path in directory.iterdir() if path.is_file())
        age(directory, 2 * WEEK)
        run(sau_cli("media", "cleanup"))
        assert directory.exists(), "a live waiter can still collect its completed file"
    finally:
        release.set()
        waiter.kill()
        waiter.wait()
    age(directory, WEEK - 60)
    run(sau_cli("media", "cleanup"))
    assert directory.stat().st_mtime == NOW - WEEK + 60
    age(directory, WEEK)
    run(sau_cli("media", "cleanup"))
    assert not directory.exists() and requests == ["/clip"]


def test_cleanup_uses_task_directory_age_and_protects_other_files(tmp_path, sau_cli, origin):
    base, assets, requests = origin
    assets["/clip.mp4"] = (200, b"clip")
    url = base + "/clip.mp4"
    expired = download(sau_cli, "expired", url)
    recent = download(sau_cli, "recent", url)
    root = expired.parent.parent
    unrelated = root / "my-files"
    unrelated.mkdir()
    (unrelated / "keep").write_text("mine")
    linked = download(sau_cli, "outside-link", url).parent
    outside = linked.rename(tmp_path / "outside")
    (outside / "keep").write_text("outside")
    linked.symlink_to(outside, target_is_directory=True)
    (expired.parent / "outside-link").symlink_to(outside, target_is_directory=True)
    age(expired.parent)
    age(recent.parent, WEEK - 1)
    age(unrelated)
    age(outside)
    (tmp_path / "sitecustomize.py").write_text(
        f"import time\ntime.time_ns = lambda: {NOW * 10**9}\n"
    )
    for _ in range(2):
        run(sau_cli("media", "cleanup"))
        assert not expired.parent.exists()
        assert recent.read_bytes() == b"clip"
        assert recent.parent.stat().st_mtime == NOW - WEEK + 1
        assert (root / "outside-link" / "keep").read_text() == "outside"
        assert (unrelated / "keep").read_text() == "mine"
    assert download(sau_cli, "expired", url).read_bytes() == b"clip"
    assert requests == ["/clip.mp4"] * 4


def test_cleanup_keeps_transferring_queued_and_publishing_tasks(tmp_path, sau_cli, origin):
    base, assets, requests = origin
    started, release = Event(), Event()

    def stalled(handler):
        started.set()
        release.wait(15)
        handler.send_error(404)

    assets.update({"/stalled": stalled, "/queued": (200, b"queued"), "/prepared": (200, b"old file")})
    posting = download(sau_cli, "posting", base + "/prepared").parent
    age(posting, 2 * WEEK)
    run(sau_cli("media", "predownload", "--task-id", "transfer", "--urls", base + "/stalled"))
    assert started.wait(5)
    run(sau_cli("media", "predownload", "--task-id", "queued", "--urls", base + "/queued"))
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"clip")
    (tmp_path / "sitecustomize.py").write_text("""
import asyncio
import os
from pathlib import Path
if os.environ.get("HOLD_UPLOAD"):
    from sau_commands import tiktok
    async def upload(request, target):
        Path("entered").touch()
        while not Path("release").exists():
            await asyncio.sleep(.02)
    tiktok._upload_video = upload
""")
    publish = sau_cli("tiktok", "upload-video", "--no-publish", "--task-id", "posting",
                      "--account", "local", "--title", "Clip", "--file", str(video), HOLD_UPLOAD="1")
    try:
        deadline = time.monotonic() + 8
        while not (tmp_path / "entered").exists():
            assert time.monotonic() < deadline and publish.poll() is None
            time.sleep(.02)
        assert posting.stat().st_mtime >= NOW
        for name in ("transfer", "queued", "posting"):
            age(tmp_path / "downloads" / name, 2 * WEEK)
        run(sau_cli("media", "cleanup"))
        assert requests == ["/prepared", "/stalled"]
        for name in ("transfer", "queued", "posting"):
            assert (tmp_path / "downloads" / name).is_dir(), name
        run(sau_cli("media", "delete", "--task-id", "queued", "--url", base + "/queued"))
        assert (tmp_path / "downloads" / "queued").stat().st_mtime >= NOW
    finally:
        (tmp_path / "release").touch()
        release.set()
        run(publish)
    assert posting.stat().st_mtime >= NOW
    assert download(sau_cli, "queued", base + "/queued").read_bytes() == b"queued"


def test_background_predownload_refreshes_retained_directory_on_admission_and_failure(
        tmp_path, sau_cli, origin):
    base, assets, _ = origin
    assets["/clip"] = (200, b"clip")
    directory = download(sau_cli, "scheduled", base + "/clip").parent
    started, release = Event(), Event()

    def fail(handler):
        started.set()
        release.wait(15)
        handler.send_error(403)

    assets["/denied"] = fail
    age(directory, 2 * WEEK)
    try:
        run(sau_cli("media", "predownload", "--task-id", "scheduled", "--urls", base + "/denied"))
        assert started.wait(5)
        assert directory.stat().st_mtime >= NOW
        age(directory, 2 * WEEK)
    finally:
        release.set()
    deadline = time.monotonic() + 6
    while directory.stat().st_mtime < NOW:
        assert time.monotonic() < deadline, "unattended failure left the directory aged"
        time.sleep(.02)


def test_cached_reuse_after_scan_protects_idle_task(tmp_path, sau_cli, origin):
    base, assets, requests = origin
    assets["/clip"] = (200, b"cached clip")
    url = base + "/clip"
    clip = download(sau_cli, "reused", url)
    age(clip.parent, 2 * WEEK)
    # Pause the CLI after the filesystem returns the pre-scan metadata.
    # The next CLI can now finish using the cache before cleanup proceeds.
    (tmp_path / "sitecustomize.py").write_text("""
import os
from pathlib import Path
import time
if target := os.environ.get("PAUSE_STAT"):
    def pause_once(inspect):
        def wrapped(path, *args, **kwargs):
            result = inspect(path, *args, **kwargs)
            if str(path) == target and not Path("scanned").exists():
                Path("scanned").touch()
                deadline = time.monotonic() + 10
                while not Path("resume").exists() and time.monotonic() < deadline:
                    time.sleep(.02)
            return result
        return wrapped
    os.stat = pause_once(os.stat)
    os.lstat = pause_once(os.lstat)
""")
    scan = sau_cli("media", "cleanup", PAUSE_STAT=str(clip.parent))
    try:
        deadline = time.monotonic() + 8
        while not (tmp_path / "scanned").exists():
            assert time.monotonic() < deadline and scan.poll() is None
            time.sleep(.02)
        assert download(sau_cli, "reused", url) == clip
    finally:
        (tmp_path / "resume").touch()
        run(scan)
    assert clip.read_bytes() == b"cached clip"
    assert requests == ["/clip"]


@pytest.mark.parametrize("fault", ["unreadable", "missing-schema"])
def test_cleanup_skips_when_queue_state_is_unreadable(tmp_path, sau_cli, origin, fault):
    base, assets, _ = origin
    assets["/clip"] = (200, b"clip")
    clip = download(sau_cli, "unknown", base + "/clip")
    age(clip.parent, 2 * WEEK)
    (tmp_path / "sitecustomize.py").write_text("""
import os
if fault := os.environ.get("UNREADABLE_STORAGE"):
    import sqlite3
    connect = sqlite3.connect
    def unavailable(*args, **kwargs):
        if fault == "missing-schema":
            return connect(":memory:")
        raise sqlite3.OperationalError("unreadable storage")
    sqlite3.connect = unavailable
""")
    run(sau_cli("media", "cleanup", UNREADABLE_STORAGE=fault))
    assert clip.read_bytes() == b"clip"
    assert clip.parent.stat().st_mtime == NOW - 2 * WEEK
    run(sau_cli("media", "cleanup"))
    assert not clip.parent.exists()
