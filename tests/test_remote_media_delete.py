"""Explicit deletion as observed by the scheduling app and its media origin."""
import json
import os
from pathlib import Path
import signal
import subprocess
from threading import Event
import time

import pytest

from tests.remote_media_cli import origin, sau_cli
from tests.test_remote_media_recovery import MOVIE, interrupted_movie, worker_of


def finish(child, expected=0):
    stdout, stderr = child.communicate(timeout=8)
    assert child.returncode == expected, (stdout, stderr)
    return stdout, stderr


def fetch(sau_cli, task, *urls):
    stdout, _ = finish(sau_cli("media", "predownload", "--wait", "--task-id", task, "--urls", *urls))
    return [Path(item["path"]) for item in json.loads(stdout)["items"]]


def test_delete_task_removes_its_directory_and_is_repeatable(sau_cli, origin):
    base, assets, _ = origin
    url = base + "/video.mp4"
    assets["/video.mp4"] = (200, b"video")
    old, = fetch(sau_cli, "post", url)
    independent, = fetch(sau_cli, "other", url)
    for _ in range(2):
        assert finish(sau_cli("media", "delete", "--task-id", "post")) == ("", "")
    assert not old.parent.exists()
    assert independent.read_bytes() == b"video"


def test_only_cli_owned_directories_can_admit_downloads(tmp_path, sau_cli, origin):
    base, assets, requests = origin
    assets["/video.mp4"] = (200, b"video")
    url = base + "/video.mp4"
    directory = tmp_path / "downloads" / "post"
    directory.mkdir(parents=True)
    personal = directory / "keep"
    personal.write_text("mine")
    timestamp = directory.stat().st_mtime_ns
    args = ("media", "predownload", "--task-id", "post", "--urls", url)
    for flags in ((), ("--wait",)):
        stdout, stderr = finish(sau_cli(*args, *flags), 1)
        assert json.loads(stdout)["reason"] == "queue_unavailable" and stderr
    assert requests == [] and list(directory.iterdir()) == [personal]
    assert personal.read_text() == "mine" and directory.stat().st_mtime_ns == timestamp
    directory.rename(tmp_path / "personal")
    downloaded, = fetch(sau_cli, "post", url)
    assert downloaded.read_bytes() == b"video"
    assert finish(sau_cli("media", "delete", "--task-id", "post")) == ("", "")
    assert not directory.exists()


def test_delete_signed_url_allows_refresh_and_retains_the_other_signature(sau_cli, origin):
    base, assets, requests = origin
    old, other = "/cover?signature=one", "/cover?signature=two"
    png = b"\x89PNG\r\n\x1a\n"
    assets.update({old: (200, png + b"v1"), other: (200, png + b"other")})
    deleted, retained = fetch(sau_cli, "post", base + old, base + other)
    assert deleted.suffix == ".png"
    assets[old] = (200, png + b"v2")
    for _ in range(2):
        assert finish(sau_cli("media", "delete", "--task-id", "post", "--url", base + old)) == ("", "")
    assert not deleted.exists() and retained.read_bytes() == png + b"other"
    refreshed, cached = fetch(sau_cli, "post", base + old, base + other)
    assert refreshed.read_bytes() == png + b"v2" and cached == retained
    assert requests == [old, other, old]


def test_delete_stops_writer_and_cancels_background_and_duplicate_waiter_interests(sau_cli, origin):
    base, assets, requests = origin
    sent, disconnected, ranges = interrupted_movie(assets)
    assets["/keep"] = (200, b"kept")
    movie, keep = base + "/movie", base + "/keep"
    args = ("media", "predownload", "--task-id", "post")
    child = sau_cli(*args, "--wait", "--urls", movie, keep, movie)
    try:
        assert sent.wait(5)
        receipt, _ = finish(sau_cli(*args, "--urls", movie))
        assert json.loads(receipt)["status"] == "accepted"
        assert finish(sau_cli("media", "delete", "--task-id", "post", "--url", movie)) == ("", "")
        assert disconnected.wait(2), "the writer kept reading the deleted URL"
        stdout, _ = finish(child, 1)
        result = json.loads(stdout)
        assert result["status"] == "failed"
        first, middle, last = result["items"]
        assert first == last == {"reason": "item_deleted"}
        assert Path(middle["path"]).read_bytes() == b"kept"
        assert requests == ["/movie", "/keep"]
        refreshed, = fetch(sau_cli, "post", movie)
        assert refreshed.read_bytes() == MOVIE
        assert ranges == [None, None], "the new download resumed a deleted checkpoint"
    finally:
        if child.poll() is None:
            child.kill()
            child.wait()


def test_publish_blocks_all_deletes_from_acquisition_until_platform_release(tmp_path, sau_cli, origin):
    base, assets, requests = origin
    started, release = Event(), Event()

    def video(handler):
        started.set()
        release.wait(15)
        handler.send_response(200)
        handler.send_header("Content-Length", "5")
        handler.end_headers()
        handler.wfile.write(b"movie")

    assets.update({"/video.mp4": video, "/other": (200, b"keep")})
    cached, = fetch(sau_cli, "post", base + "/other")
    (tmp_path / "sitecustomize.py").write_text("""
import asyncio
from pathlib import Path
from sau_commands import tiktok
async def platform(request, target):
    assert request.video_file.read_bytes() == b"movie"
    Path("entered").touch()
    while not Path("return").exists():
        await asyncio.sleep(.05)
tiktok._upload_video = platform
""")
    publish = sau_cli("tiktok", "upload-video", "--account", "local", "--task-id", "post",
                      "--file", base + "/video.mp4", "--title", "Held", "--no-publish")
    try:
        assert started.wait(5)
        for stage in ("acquisition", "platform"):
            if stage == "platform":
                release.set()
                deadline = time.monotonic() + 5
                while not (tmp_path / "entered").exists():
                    assert time.monotonic() < deadline
                    time.sleep(.05)
            for scope in ((), ("--url", base + "/other")):
                stdout, stderr = finish(sau_cli("media", "delete", "--task-id", "post", *scope), 1)
                assert not stdout and len(stderr.splitlines()) == 1 and "publish" in stderr.lower()
                assert cached.read_bytes() == b"keep"
        assert requests == ["/other", "/video.mp4"]
    finally:
        release.set()
        (tmp_path / "return").touch()
        finish(publish)
    assert finish(sau_cli("media", "delete", "--task-id", "post")) == ("", "")


@pytest.mark.parametrize("args", [(), ("--task-id",), ("--task-id", "../outside"), ("--task-id", ".SAU-Queue")])
def test_missing_or_unsafe_id_has_a_one_line_diagnostic(sau_cli, args):
    stdout, stderr = finish(sau_cli("media", "delete", *args), 1)
    assert not stdout and len(stderr.splitlines()) == 1 and "ID" in stderr


@pytest.mark.skipif(os.name == "nt", reason="Pauses the detached POSIX worker")
def test_item_delete_rechecks_directory_after_draining_a_writer(tmp_path, sau_cli, origin):
    base, assets, _ = origin
    assets["/movie"] = (200, b"external file")
    url = base + "/movie"
    outside = tmp_path / "external"
    specimen, = fetch(sau_cli, "copy", url)
    specimen.parent.rename(outside)
    external = outside / specimen.name
    sent, _, _ = interrupted_movie(assets)
    waiter = sau_cli("media", "predownload", "--wait", "--task-id", "post", "--urls", url)
    assert sent.wait(5)
    worker = worker_of(waiter)
    os.kill(worker, signal.SIGSTOP)
    directory = tmp_path / "downloads" / "post"
    try:
        deletion = sau_cli("media", "delete", "--task-id", "post", "--url", url)
        stdout, _ = finish(waiter, 1)
        assert json.loads(stdout)["items"] == [{"reason": "item_deleted"}]
        assert deletion.poll() is None, "delete returned before the writer stopped"
        directory.rename(tmp_path / "previous")
        directory.symlink_to(outside, target_is_directory=True)
    finally:
        os.kill(worker, signal.SIGCONT)
    stdout, stderr = finish(deletion, 1)
    assert not stdout and len(stderr.splitlines()) == 1
    assert external.read_bytes() == b"external file"


@pytest.mark.skipif(os.name == "nt", reason="Pauses the detached POSIX worker")
def test_whole_task_notifies_waiter_before_drain_and_admits_new_requests_afterwards(sau_cli, origin):
    base, assets, requests = origin
    sent, _, _ = interrupted_movie(assets)
    assets["/fresh"] = (200, b"new generation")
    old_urls = (base + "/movie", base + "/never")
    args = ("media", "predownload", "--task-id", "post")
    unrelated, = fetch(sau_cli, "other", base + "/fresh")
    waiter = sau_cli(*args, "--wait", "--urls", *old_urls)
    assert sent.wait(5)
    worker = worker_of(waiter)
    stdout, _ = finish(sau_cli(*args, "--urls", *old_urls))
    assert json.loads(stdout)["status"] == "accepted"
    os.kill(worker, signal.SIGSTOP)
    try:
        deletion = sau_cli("media", "delete", "--task-id", "post")
        stdout, _ = finish(waiter, 1)
        assert json.loads(stdout) == {"task_id": "post", "status": "task_cleared", "items": []}
        assert deletion.poll() is None
        assert finish(sau_cli("media", "delete", "--task-id", "other")) == ("", "")
        assert not unrelated.parent.exists()
        fresh = sau_cli(*args, "--wait", "--urls", base + "/fresh")
        with pytest.raises(subprocess.TimeoutExpired):
            fresh.communicate(timeout=.6)
    finally:
        os.kill(worker, signal.SIGCONT)
    assert finish(deletion) == ("", "")
    stdout, _ = finish(fresh)
    item, = json.loads(stdout)["items"]
    assert Path(item["path"]).read_bytes() == b"new generation"
    assert requests == ["/fresh", "/movie", "/fresh"]


def test_delete_queued_url_keeps_same_task_transfer_running(sau_cli, origin):
    base, assets, requests = origin
    started, release = Event(), Event()

    def held(handler):
        started.set()
        release.wait(10)
        handler.send_response(200)
        handler.send_header("Content-Length", "4")
        handler.end_headers()
        handler.wfile.write(b"kept")

    assets["/active"] = held
    queued = base + "/queued"
    args = ("media", "predownload", "--task-id", "post")
    waiter = sau_cli(*args, "--wait", "--urls", base + "/active", queued, queued)
    try:
        assert started.wait(5)
        assert json.loads(finish(sau_cli(*args, "--urls", queued))[0])["status"] == "accepted"
        assert finish(sau_cli("media", "delete", "--task-id", "post", "--url", queued)) == ("", "")
        assert waiter.poll() is None
    finally:
        release.set()
    stdout, _ = finish(waiter, 1)
    active, first, second = json.loads(stdout)["items"]
    assert Path(active["path"]).read_bytes() == b"kept"
    assert first == second == {"reason": "item_deleted"}
    assert requests == ["/active"]


@pytest.mark.skipif(os.name == "nt" or getattr(os, "geteuid", lambda: 0)() == 0,
                    reason="Uses POSIX directory permissions")
def test_failed_task_delete_can_be_retried_after_permissions_are_restored(sau_cli, origin):
    base, assets, _ = origin
    assets["/video"] = (200, b"ok")
    downloaded, = fetch(sau_cli, "post", base + "/video")
    # The task contents can be removed, but rmdir of the task itself fails.
    root = downloaded.parent.parent
    mode = root.stat().st_mode
    root.chmod(0o500)
    try:
        stdout, stderr = finish(sau_cli("media", "delete", "--task-id", "post"), 1)
        assert not stdout and len(stderr.splitlines()) == 1
    finally:
        root.chmod(mode)
    assert finish(sau_cli("media", "delete", "--task-id", "post")) == ("", "")
    assert not downloaded.parent.exists()


def test_delete_never_follows_links_or_removes_an_unmanaged_directory(tmp_path, sau_cli, origin):
    base, assets, _ = origin
    url = base + "/video.mp4"
    assets["/video.mp4"] = (200, b"download")
    downloaded, = fetch(sau_cli, "post", url)
    external = tmp_path / "mine"
    external.mkdir()
    valuable = external / "keep"
    valuable.write_text("personal")
    root = downloaded.parent.parent
    unmanaged = root / "personal"
    unmanaged.mkdir()
    (unmanaged / downloaded.name).write_text("mine")
    (root / "alias").symlink_to(external, target_is_directory=True)
    for task in ("alias", "personal"):
        for scope in ((), ("--url", url)):
            stdout, stderr = finish(sau_cli("media", "delete", "--task-id", task, *scope), 1)
            assert not stdout and len(stderr.splitlines()) == 1
    downloaded.unlink()
    downloaded.symlink_to(valuable)
    assert finish(sau_cli("media", "delete", "--task-id", "post", "--url", url)) == ("", "")
    assert not downloaded.is_symlink()
    (downloaded.parent / "linked").symlink_to(external, target_is_directory=True)
    assert finish(sau_cli("media", "delete", "--task-id", "post")) == ("", "")
    assert valuable.read_text() == "personal"
    assert (unmanaged / downloaded.name).read_text() == "mine"
