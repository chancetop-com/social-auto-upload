"""Run XHS and Rednote CLI commands in separate installations on an offline Profile."""
import json
import sys
import time
import threading
from contextlib import ExitStack
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from patchright.sync_api import sync_playwright

from tests.test_shared_adspower_process import Handler, OfflineProfile, installations

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="POSIX console-script fixture")

PLATFORMS = ("xiaohongshu", "rednote")


FIXTURES = Path(__file__).with_name("fixtures")
EPOCH = 1893456000  # 2030-01-01 00:00:00 UTC


def advance(profile, seconds):
    clock = profile.root / "clock"
    pending = clock.with_suffix(".tmp")
    pending.write_text(str(EPOCH + seconds))
    pending.replace(clock)


def command(profile, installation, platform, action="check", *, when=None, profile_id="shared"):
    flags = []
    env = {"HUMANIZE": "0"}
    if action != "check":
        video = action == "upload-video"
        media = profile.root / (f"{platform}.mp4" if video else f"{platform}.png")
        media.write_bytes(b"offline media")
        flags += ["--title", f"{platform} draft", "--desc" if video else "--note", f"{platform} body",
                  "--file" if video else "--images", str(media)]
    if when is not None:
        flags += ["--not-before", f"2030-01-01T00:00:{when:02d}Z"]
        env.update(PYTHONPATH=str(FIXTURES / "publish_clock"), SAU_TEST_CLOCK=str(profile.root / "clock"),
                   SAU_TEST_GATE_ENTERED=str(profile.root / f"waiting-{platform}"))
    return profile.command(installation, platform, *flags, action=action, env=env, profile_id=profile_id)


def wait_for(check, child):
    deadline = time.monotonic() + 20
    while not check():
        if child.poll() is not None:
            pytest.fail(child.communicate()[0])
        if time.monotonic() >= deadline:
            pytest.fail("CLI did not reach its offline synchronization point")
        time.sleep(.025)


def finish(child, expected):
    output = child.communicate(timeout=35)[0]
    assert child.returncode == expected, output
    return output


class CreatorSite:
    def __init__(self):
        self.documents = []
        self.clicks = []
        self.outcome = "success"
        self.arrived = threading.Event()
        self.release = threading.Event()
        self.release.set()

    def handler(self):
        site = self

        class Creator(Handler):
            def do_GET(self):
                if self.path == "/ready.js":
                    site.arrived.set()
                    site.release.wait(45)
                    self.respond(b"", "application/javascript")
                elif self.path.startswith("/publish/publish?"):
                    site.documents.append(parse_qs(urlsplit(self.path).query)["target"][0])
                    body = (FIXTURES / "xhs_creator.html").read_bytes()
                    self.respond(body, "text/html")
                else:
                    self.respond(b"", "text/plain")

            def do_POST(self):
                assert self.path == "/submit"
                site.clicks.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
                self.respond(b'{"next":"/publish/success"}', "application/json")

        return Creator


@pytest.fixture
def creators(tmp_path, installations):
    sites = {platform: CreatorSite() for platform in PLATFORMS}
    with ExitStack() as stack:
        playwright = stack.enter_context(sync_playwright())
        profile = OfflineProfile(
            tmp_path, stack, installations, playwright,
            sites={f"creator.{name}.com": site.handler() for name, site in sites.items()},
        )
        advance(profile, 0)
        yield profile, sites
        for site in sites.values():
            site.release.set()


def test_rednote_default_check_allows_explicit_headed_peer(creators):
    profile, sites = creators
    sites["rednote"].release.clear()
    first = profile.command(0, "rednote")
    assert sites["rednote"].arrived.wait(15)
    peer = profile.command(1, "xiaohongshu", "--headed")
    output = peer.communicate(timeout=15)[0]
    assert (peer.returncode, "valid" in output.splitlines()) == (0, True), output
    assert profile.stops == []
    sites["rednote"].release.set()
    output = first.communicate(timeout=15)[0]
    assert (first.returncode, "valid" in output.splitlines()) == (0, True), output
    assert profile.starts == profile.stops == ["shared"]


def test_waiting_xhs_note_allows_rednote_video_at_its_own_time(creators):
    profile, sites = creators
    xhs = command(profile, 0, "xiaohongshu", "upload-note", when=20)
    wait_for((profile.root / "waiting-xiaohongshu").exists, xhs)
    rednote = command(profile, 1, "rednote", "upload-video", when=10)
    wait_for((profile.root / "waiting-rednote").exists, rednote)
    assert sites["xiaohongshu"].clicks == sites["rednote"].clicks == []
    advance(profile, 10)
    assert "Rednote video upload submitted" in finish(rednote, 0)
    assert sites["rednote"].clicks == [
        {"target": "video", "file": "rednote.mp4", "title": "rednote draft", "body": "rednote body"}
    ]
    assert sites["xiaohongshu"].clicks == [] and xhs.poll() is None and not profile.stops
    advance(profile, 20)
    assert "Xiaohongshu note upload submitted" in finish(xhs, 0)
    assert sites["xiaohongshu"].clicks == [
        {"target": "image", "file": "xiaohongshu.png", "title": "xiaohongshu draft", "body": "xiaohongshu body"}
    ]
    assert profile.starts == profile.stops == ["shared"]
