"""Task media lifetime observed through publishing and predownload commands."""
from contextlib import ExitStack
import json
import os
import signal

import pytest
from patchright.sync_api import sync_playwright

from tests.remote_media_cli import origin, sau_cli
from tests.shared_publish_sites import TikTokSite
from tests.test_remote_media_delete import fetch, finish
from tests.test_remote_media_platforms import receiver
from tests.test_remote_media_recovery import interrupted_movie
from tests.test_shared_adspower_process import OfflineProfile, installations
from tests.test_shared_instagram_tiktok import matching_page, wait_for_event


def test_confirmed_post_releases_unused_transfers_and_admits_a_fresh_task(
        tmp_path, origin, sau_cli, receiver):
    base, assets, requests = origin
    assets.update({"/first.jpg": (200, b"first"), "/second.jpg": (200, b"second")})
    first, second = base + "/first.jpg", base + "/second.jpg"
    cached, _ = fetch(sau_cli, "post", first, second)
    other, = fetch(sau_cli, "other", first)
    local = tmp_path / "local.jpg"
    local.write_bytes(b"caller")
    sent, disconnected, _ = interrupted_movie(assets)
    predownload = ("media", "predownload", "--task-id", "post")
    unused = (base + "/movie", base + "/queued")
    waiter = sau_cli(*predownload, "--wait", "--urls", *unused)
    try:
        assert sent.wait(8)
        accepted, _ = finish(sau_cli(*predownload, "--urls", *unused))
        assert json.loads(accepted)["status"] == "accepted"
        finish(sau_cli("facebook", "upload-note", "--task-id", "post", "--account", "offline",
                       "--title", "Post", "--images", first, second, str(local)))
        assert [bytes.fromhex(item["bytes"]) for item in json.loads(receiver.read_text())] == [
            b"first", b"second", b"caller",
        ]
        assert not cached.parent.exists()
        assert disconnected.wait(2)
        stdout, _ = finish(waiter, 1)
        assert json.loads(stdout) == {"task_id": "post", "status": "task_cleared", "items": []}
        assert other.read_bytes() == b"first" and local.read_bytes() == b"caller"
        assets["/first.jpg"] = (200, b"fresh")
        fresh, = fetch(sau_cli, "post", first)
        assert fresh.read_bytes() == b"fresh"
        assert requests == ["/first.jpg", "/second.jpg", "/first.jpg", "/movie", "/first.jpg"]
    finally:
        if waiter.poll() is None:
            waiter.kill()
            waiter.wait()
            finish(sau_cli("media", "delete", "--task-id", "post"))


@pytest.mark.skipif(os.name == "nt" or getattr(os, "geteuid", lambda: 0)() == 0,
                    reason="Uses POSIX directory permissions")
def test_cleanup_error_preserves_confirmed_platform_result(sau_cli, origin, receiver):
    base, assets, _ = origin
    assets["/chosen.jpg"] = (200, b"post")
    cached, = fetch(sau_cli, "post", base + "/chosen.jpg")
    root = cached.parent.parent
    previous = root.stat().st_mode
    root.chmod(0o500)
    try:
        stdout, stderr = finish(sau_cli("facebook", "upload-note", "--task-id", "post",
                                        "--images", str(cached), "--title", "Post", "--account", "local"))
        assert "Facebook image post submitted" in stdout
        assert "published" in stderr.lower() and "release media task post" in stderr
    finally:
        root.chmod(previous)
    finish(sau_cli("media", "delete", "--task-id", "post"))


@pytest.mark.skipif(os.name == "nt", reason="POSIX isolated Chromium fixture")
@pytest.mark.parametrize(("outcome", "code", "submissions"), [
    ("no-publish", 0, 0), ("failed", 1, 0), ("interrupt", 130, 0),
    ("unknown", 9, 1), ("login", 10, 1),
])
def test_unconfirmed_platform_outcome_keeps_task_media(
        tmp_path, sau_cli, origin, installations, outcome, code, submissions):
    base, assets, requests = origin
    assets["/photo.png"] = (200, b"chosen photo")
    cached, = fetch(sau_cli, "post", base + "/photo.png")
    site = TikTokSite(ready=outcome not in {"failed", "interrupt"}, outcome=outcome)
    with ExitStack() as stack:
        profile = OfflineProfile(tmp_path, stack, installations, stack.enter_context(sync_playwright()),
                                 sites={"www.tiktok.com": site.handler()})
        flags = ["--no-publish"] if outcome == "no-publish" else []
        child = profile.command(0, "tiktok", "--images", str(cached), "--task-id", "post", "--title", "Photo",
                                *flags, action="upload-note", env={"HUMANIZE": "0", "PYTHONPATH": str(tmp_path)})
        if outcome in {"failed", "interrupt", "unknown"}:
            page = matching_page(profile, lambda p: p.locator("#images").count() and
                                 p.locator("#images").evaluate("input => input.files.length === 1"), child)
            if outcome == "interrupt":
                child.send_signal(signal.SIGINT)
            else:
                if outcome == "unknown":
                    wait_for_event(lambda: site.submissions, child)
                page.close()
        stdout, _ = child.communicate(timeout=20)
        assert child.returncode == code, stdout
        if outcome == "login":
            assert "publish_attempted=true" in stdout.splitlines()
    assert len(site.submissions) == submissions
    assert cached.read_bytes() == b"chosen photo" and requests == ["/photo.png"]


@pytest.mark.parametrize(("platform", "status", "flags"), [
    ("facebook-page", "processing", []),
    ("facebook-page", "scheduled", ["--schedule", "2030-01-01T00:00:00Z"]),
    ("xiaohongshu", "scheduled", ["--schedule", "2030-01-01T00:00:00Z"]),
    ("rednote", "scheduled", ["--schedule", "2030-01-01T00:00:00Z"]),
    ("instagram", "not_submitted", ["--no-publish"]),
])
def test_successful_command_keeps_task_until_platform_confirms_publication(
        sau_cli, origin, receiver, platform, status, flags):
    base, assets, _ = origin
    assets["/video.mp4"] = (200, b"chosen video")
    cached, = fetch(sau_cli, "post", base + "/video.mp4")
    stdout, _ = finish(sau_cli(platform, "upload-video", "--file", str(cached),
                               "--task-id", "post", "--account", "local", "--title", "Video",
                               *flags, SAU_TEST_POST_STATUS=status))
    if platform in {"facebook-page", "instagram"}:
        assert json.loads(stdout)["status"] == status
    assert cached.read_bytes() == b"chosen video"
