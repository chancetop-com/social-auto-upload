"""Material delivery observed through the installed CLI and offline publishing UI."""
from contextlib import ExitStack
import json
import os
import subprocess
import sys
from threading import Event

import pytest
from pathlib import Path

from patchright.sync_api import sync_playwright

from tests.remote_media_cli import PROJECT, origin, sau_cli
from tests.shared_publish_sites import TikTokSite
from tests.test_shared_instagram_tiktok import matching_page
from tests.test_shared_adspower_process import OfflineProfile, installations


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX isolated Chromium fixture")
@pytest.mark.parametrize(("managed", "explicit_id"), [(True, True), (False, False)])
def test_photo_order_and_full_budget_after_eighteen_minutes_of_acquisition(
        tmp_path, installations, origin, sau_cli, managed, explicit_id):
    base, assets, requests = origin
    clock = tmp_path / "monotonic"
    clock.write_text("0")

    def cover_response(handler):
        clock.write_text("1080")
        handler.send_response(200)
        handler.send_header("Content-Length", "12")
        handler.end_headers()
        handler.wfile.write(b"remote cover")

    assets["/cover.jpg?key=signed"] = cover_response
    cover = base + "/cover.jpg?key=signed"
    local = tmp_path / "local.png"
    local.write_text("local photo")
    # Only the publish budget reads virtual monotonic time. The scheduler,
    # browser deadlines, HTTP clients and event loop keep their real clocks.
    (tmp_path / "sitecustomize.py").write_text("""
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
import os
from uploader import publish_timeout
clock = Path(os.environ["TEST_PUBLISH_CLOCK"])
publish_timeout.time = SimpleNamespace(monotonic=lambda: float(clock.read_text()))
if "TEST_LOCAL_CDP" in os.environ:
    from sau_commands import tiktok
    from utils.browser_session import BrowserSession
    @asynccontextmanager
    async def session(playwright, **options):
        browser = await playwright.chromium.connect_over_cdp(os.environ["TEST_LOCAL_CDP"])
        yield BrowserSession(browser, browser.contexts[0], "local")
    tiktok.local_browser_session = session
""")
    site = TikTokSite(ready=False, capture_files=True)
    with ExitStack() as stack:
        playwright = stack.enter_context(sync_playwright())
        profile = OfflineProfile(tmp_path, stack, installations, playwright,
                                 sites={"www.tiktok.com": site.handler()})
        args = ["--images", cover, str(local), cover, "--title", "Photo order"]
        if explicit_id:
            args += ["--task-id", "post"]
        env = {"HUMANIZE": "0", "TEST_PUBLISH_CLOCK": str(clock), "PYTHONPATH": str(tmp_path)}
        if managed:
            child = profile.command(0, "tiktok", *args, action="upload-note", env=env)
        else:
            env.update(TEST_LOCAL_CDP=profile.endpoint,
                       PYTHONPATH=os.pathsep.join(map(str, (tmp_path, PROJECT))))
            child = sau_cli("tiktok", "upload-note", "--account", "offline", *args, **env)
            stack.callback(profile.reap, child)
        page = matching_page(profile, lambda p: p.locator("#images").count() and
                             p.locator("#images").evaluate("input => input.files.length === 3"), child)
        clock.write_text("1979")  # Use 899 of the platform's 900 seconds.
        page.locator("#post").evaluate("button => button.disabled = false")
        stdout, stderr = child.communicate(timeout=25)
        assert child.returncode == 0, (stdout, stderr)
    submission, = site.submissions
    assert submission["contents"] == ["remote cover", "local photo", "remote cover"]
    assert requests == ["/cover.jpg?key=signed"]
    assert local.read_text() == "local photo"


def test_video_and_cover_are_independent_sources_and_only_remote_invocations_use_storage(
        tmp_path, origin, sau_cli):
    # The installed CLI hands its local paths to a platform boundary which reads
    # the bytes while the command owns them, including the optional video cover.
    (tmp_path / "sitecustomize.py").write_text("""
import json
from pathlib import Path
from sau_commands import tiktok

async def record(request, target):
    paths = [request.video_file, request.thumbnail_file]
    print(json.dumps({"contents": [path.read_text() for path in paths],
                      "paths": [str(path) for path in paths]}))

tiktok._upload_video = record
""")
    base, assets, requests = origin
    video, cover = tmp_path / "local.mp4", tmp_path / "local.jpg"
    video.write_text("local video")
    cover.write_text("local cover")
    assets.update({"/v.mp4": (200, b"remote video"), "/c.jpg": (200, b"remote cover")})
    root = tmp_path / "downloads"
    previous = set()
    for v, c, expected in [
        (str(video), str(cover), ["local video", "local cover"]),
        (str(video), base + "/c.jpg", ["local video", "remote cover"]),
        (base + "/v.mp4", str(cover), ["remote video", "local cover"]),
        (base + "/v.mp4", base + "/c.jpg", ["remote video", "remote cover"]),
    ]:
        child = sau_cli("tiktok", "upload-video", "--account", "local", "--title", "Video",
                        "--file", v, "--thumbnail", c)
        stdout, stderr = child.communicate(timeout=15)
        assert child.returncode == 0, stderr
        handoff = json.loads(stdout.splitlines()[0])
        assert handoff["contents"] == expected
        if v == str(video) and c == str(cover):
            assert not root.exists()
            continue
        downloaded = {Path(path).parent for path in handoff["paths"] if Path(path).parent != tmp_path}
        assert len(downloaded) == 1
        directory, = downloaded
        assert directory.parent == root and not directory.exists()
        assert directory not in previous
        previous.add(directory)
    assert video.read_text() == "local video" and cover.read_text() == "local cover"


@pytest.mark.parametrize("managed", [False, True])
def test_first_required_failure_exits_while_earlier_photo_is_held(tmp_path, origin, sau_cli, managed):
    base, assets, requests = origin
    release = Event()
    started = Event()

    def slow(handler):
        started.set()
        release.wait(15)
        handler.send_error(503)

    assets["/held.jpg"] = slow
    assets["/keep.jpg"] = (200, b"earlier download")
    prepared = sau_cli("media", "predownload", "--wait", "--task-id", "failed",
                       "--urls", base + "/keep.jpg")
    stdout, stderr = prepared.communicate(timeout=10)
    assert prepared.returncode == 0, stderr
    cached = Path(json.loads(stdout)["items"][0]["path"])
    flags, env = ["--account", "local"], {}
    if managed:
        # An attempted connection would be visible at the same controlled origin.
        flags, env = ["--profile-id", "fixture"], dict(ADSPOWER_API_KEY="offline", ADSPOWER_API_BASE=base)
    missing = base + "/missing.jpg"
    child = sau_cli("tiktok", "upload-note", *flags, "--task-id", "failed", "--images",
                    base + "/held.jpg", missing, SAU_DOWNLOAD_CONCURRENCY="2", **env)
    try:
        assert started.wait(5)
        stdout, stderr = child.communicate(timeout=4)
    finally:
        release.set()
        if child.poll() is None:
            child.communicate(timeout=10)
    assert child.returncode == 1
    assert missing in stderr and "HTTP 404" in stderr
    assert "publish_attempted=false" in stderr.splitlines()
    assert cached.read_bytes() == b"earlier download"
    assert sorted(requests) == ["/held.jpg", "/keep.jpg", "/missing.jpg"]


def test_publish_promotes_waiting_urls_and_shares_the_active_transfer(tmp_path, origin, sau_cli):
    base, assets, requests = origin
    started, release = Event(), Event()

    def active(handler):
        started.set()
        release.wait(15)
        handler.send_response(200)
        handler.send_header("Content-Length", "5")
        handler.end_headers()
        handler.wfile.write(b"cover")

    assets.update({"/active.jpg": active, "/ordinary.jpg": (200, b"low"),
                   "/needed.mp4": (200, b"video")})
    (tmp_path / "sitecustomize.py").write_text("""
from sau_commands import tiktok
async def publish(request, target):
    assert request.video_file.read_bytes() == b"video"
    assert request.thumbnail_file.read_bytes() == b"cover"
tiktok._upload_video = publish
""")
    urls = [base + path for path in ("/active.jpg", "/ordinary.jpg", "/needed.mp4")]
    early = sau_cli("media", "predownload", "--task-id", "priority", "--urls", *urls)
    stdout, stderr = early.communicate(timeout=8)
    assert early.returncode == 0 and json.loads(stdout)["status"] == "accepted", stderr
    child = sau_cli("tiktok", "upload-video", "--task-id", "priority", "--account", "local",
                    "--file", urls[2], "--thumbnail", urls[0], "--title", "Urgent")
    try:
        assert started.wait(5)
        with pytest.raises(subprocess.TimeoutExpired):
            child.communicate(timeout=1.5)
        assert requests == ["/active.jpg"]
    finally:
        release.set()
    stdout, stderr = child.communicate(timeout=10)
    assert child.returncode == 0, stderr
    pending = sau_cli("media", "predownload", "--wait", "--task-id", "priority", "--urls", urls[1])
    pending.communicate(timeout=8)
    assert requests == ["/active.jpg", "/needed.mp4", "/ordinary.jpg"]


def test_extensionless_direct_image_is_a_reusable_local_upload(tmp_path, origin, sau_cli):
    base, assets, requests = origin
    body = b"\x89PNG\r\n\x1a\nphoto"

    def image(handler):
        handler.send_response(200)
        handler.send_header("Content-Length", str(len(body)))
        handler.send_header("Content-Type", "image/png")
        handler.end_headers()
        handler.wfile.write(body)

    assets["/asset?key=1"] = image
    url = base + "/asset?key=1"
    fetched = sau_cli("media", "predownload", "--wait", "--task-id", "extensionless", "--urls", url)
    stdout, stderr = fetched.communicate(timeout=10)
    assert fetched.returncode == 0, stderr
    path = json.loads(stdout)["items"][0]["path"]
    (tmp_path / "sitecustomize.py").write_text("""
from sau_commands import tiktok
async def publish(request, target):
    first, second = request.image_files
    assert first == second and first.suffix == ".png"
tiktok._upload_note = publish
""")
    child = sau_cli("tiktok", "upload-note", "--account", "local", "--task-id", "extensionless",
                    "--images", path, url)
    stdout, stderr = child.communicate(timeout=10)
    assert child.returncode == 0, stderr
    assert requests == ["/asset?key=1"]


def test_predownload_is_independent_of_browser_credentials(origin, sau_cli):
    base, assets, requests = origin
    assets["/offline-cover"] = (200, b"cover")
    child = sau_cli("media", "predownload", "--wait", "--task-id", "independent",
                    "--urls", base + "/offline-cover", MLX_API_TOKEN="offline", ADSPOWER_API_KEY="offline")
    stdout, stderr = child.communicate(timeout=10)
    assert child.returncode == 0, stderr
    assert json.loads(stdout)["status"] == "ready" and requests == ["/offline-cover"]
