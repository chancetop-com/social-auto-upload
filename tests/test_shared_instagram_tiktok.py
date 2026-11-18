"""Installed publishing commands with independent connections to a loopback Chromium."""
import json
import sys
import threading
import time
from contextlib import ExitStack
from pathlib import Path

import pytest
from patchright.sync_api import Error, sync_playwright

from tests.shared_publish_sites import InstagramSite, TikTokSite
from tests.test_shared_adspower_process import Handler, OfflineProfile, installations


pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="POSIX console-script fixture")


def matching_page(profile, predicate, child):
    context = profile.browser.contexts[0]
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        context.pages[0].wait_for_timeout(50)
        for page in context.pages:
            try:
                if predicate(page):
                    return page
            except Error:
                if not page.is_closed():
                    raise
        if child.poll() is not None:
            pytest.fail(child.communicate()[0])
    pytest.fail(f"Missing editor among {[p.url for p in context.pages]}")


def test_tiktok_login_expiry_leaves_peer_draft_editable(tmp_path, installations):
    class LoginPage(Handler):
        def do_GET(self):
            self.respond(b'<form action="/login"><input name="username"></form>', "text/html")

    with ExitStack() as stack:
        playwright = stack.enter_context(sync_playwright())
        profile = OfflineProfile(tmp_path, stack, installations, playwright,
                                 sites={"www.tiktok.com": LoginPage})
        peer = profile.command(0, "instagram")
        profile.entered("instagram", peer)
        page = matching_page(profile, lambda p: "instagram.com" in p.url, peer)
        editor = page.locator("textarea")
        editor.fill("Instagram draft")
        original_url = page.url
        media = tmp_path / "photo.png"
        media.touch()
        child = profile.command(1, "tiktok", "--images", str(media), action="upload-note")
        output = child.communicate(timeout=12)[0]
        assert child.returncode == 10, output
        assert "publish_attempted=true" not in output
        assert page.url == original_url and editor.input_value() == "Instagram draft"
        editor.fill("Instagram draft continued")
        assert not profile.stops
        profile.finish("instagram", peer)
        assert profile.stops == ["shared"]


def test_instagram_note_result_only_contains_its_own_submission(tmp_path, installations):
    site = InstagramSite()
    with ExitStack() as stack:
        playwright = stack.enter_context(sync_playwright())
        profile = OfflineProfile(tmp_path, stack, installations, playwright,
                                 sites={"www.instagram.com": site.handler()})
        peer = profile.command(1, "tiktok")
        profile.entered("tiktok", peer)
        page = matching_page(profile, lambda p: "tiktok.com" in p.url, peer)
        editor = page.locator("textarea")
        editor.fill("TikTok draft")
        original_url = page.url

        photo = tmp_path / "carousel.png"
        photo.touch()
        result = tmp_path / "instagram.json"
        child = profile.command(0, "instagram", "--images", str(photo), "--title", "IG carousel",
                                "--result", str(result), action="upload-note", env={"HUMANIZE": "0"})
        output = child.communicate(timeout=15)[0]
        assert child.returncode == 0, output
        assert site.submissions == [{"caption": "IG carousel", "files": ["carousel.png"]}]
        record = json.loads(result.read_text())
        assert (record["status"], record["post_id"], record["title"]) == (
            "published", "offline-fixture", "IG carousel")
        assert page.url == original_url and editor.input_value() == "TikTok draft"
        editor.fill("peer continues")
        assert not profile.stops
        profile.finish("tiktok", peer)
        assert profile.stops == ["shared"]


def test_lost_tiktok_photo_editor_leaves_instagram_video_and_lookalike_intact(tmp_path, installations):
    instagram = InstagramSite()
    tiktok = TikTokSite(ready=False)
    with ExitStack() as stack:
        playwright = stack.enter_context(sync_playwright())
        profile = OfflineProfile(tmp_path, stack, installations, playwright,
                                 sites={"www.instagram.com": instagram.handler(block_share=True),
                                        "www.tiktok.com": tiktok.handler()})
        video = tmp_path / "ig.mp4"
        photo = tmp_path / "tt.png"
        video.touch()
        photo.touch()
        result = tmp_path / "video.json"
        ig = profile.command(0, "instagram", "--file", str(video), "--title", "IG video",
                             "--no-publish", "--result", str(result), action="upload-video",
                             env={"HUMANIZE": "0"})
        ig_page = matching_page(profile, lambda p: p.locator("[contenteditable]").count() and
                               p.locator("[contenteditable]").inner_text() == "IG video", ig)
        ig_url = ig_page.url
        with ig_page.expect_popup() as popup:
            ig_page.evaluate("window.open('https://www.tiktok.com/tiktokstudio/upload?tab=photo')")
        lookalike = popup.value
        lookalike.locator("input[placeholder]").fill("Instagram preview")
        tt = profile.command(1, "tiktok", "--images", str(photo), "--title", "TT photo",
                             action="upload-note", env={"HUMANIZE": "0"})
        tt_page = matching_page(profile, lambda p: p != lookalike and p.url == lookalike.url and
                               p.locator("input[placeholder]").input_value() == "TT photo", tt)
        # Both probes have closed, and even closing a preview cannot free its platform.
        with tt_page.expect_popup() as tt_popup:
            tt_page.evaluate("window.open('about:blank')")
        tt_popup.value.close()
        for platform in ("instagram", "tiktok"):
            competing = profile.command(1, platform)
            output = competing.communicate(timeout=8)[0]
            assert competing.returncode == 1 and platform in output and "占用" in output, output

        tt_page.close()
        output = tt.communicate(timeout=7)[0]
        assert tt.returncode == 1 and "publish_attempted=true" not in output, output
        assert tiktok.submissions == []
        assert lookalike.locator("input[placeholder]").input_value() == "Instagram preview"
        assert ig_page.url == ig_url and ig_page.locator("[contenteditable]").inner_text() == "IG video"
        ig_page.locator("[contenteditable]").fill("IG video continued")
        assert not profile.stops
        ig_page.locator("[data-share-blocker]").evaluate("el => el.remove()")
        output = ig.communicate(timeout=8)[0]
        assert ig.returncode == 0, output
        assert json.loads(result.read_text())["status"] == "prepared"
        assert instagram.submissions == []
        assert profile.starts == profile.stops == ["shared"]


def wait_for_event(observed, child, timeout=15):
    deadline = time.monotonic() + timeout
    while not observed():
        if child.poll() is not None:
            pytest.fail(child.communicate()[0])
        if time.monotonic() >= deadline:
            pytest.fail("Offline command did not reach the expected state")
        time.sleep(.02)


def test_waiting_instagram_and_earlier_tiktok_publish_their_own_drafts(tmp_path, installations):
    epoch = 1893456000  # 2030-01-01 00:00:00 UTC
    clock = tmp_path / "clock"

    def advance(seconds):
        pending = clock.with_suffix(".tmp")
        pending.write_text(str(epoch + seconds))
        pending.replace(clock)

    def gate(platform):
        return {"HUMANIZE": "0", "SAU_TEST_CLOCK": str(clock),
                "SAU_TEST_GATE_ENTERED": str(tmp_path / platform),
                "PYTHONPATH": str(Path(__file__).parent / "fixtures/publish_clock")}

    advance(0)
    instagram = InstagramSite(now=lambda: int(clock.read_text()))
    tiktok = TikTokSite(now=lambda: int(clock.read_text()))
    with ExitStack() as stack:
        playwright = stack.enter_context(sync_playwright())
        profile = OfflineProfile(tmp_path, stack, installations, playwright,
                                 sites={"www.instagram.com": instagram.handler(),
                                        "www.tiktok.com": tiktok.handler()})
        photo = tmp_path / "IG.png"
        video = tmp_path / "TT.mp4"
        photo.touch()
        video.touch()
        ig = profile.command(0, "instagram", "--images", str(photo), "--title", "IG on time",
                             "--not-before", "2030-01-01T00:00:20Z", action="upload-note", env=gate("ig"))
        wait_for_event((tmp_path / "ig").exists, ig)
        draft = matching_page(profile, lambda p: "instagram.com" in p.url, ig)
        location = draft.url
        assert draft.locator("[contenteditable]").inner_text() == "IG on time"

        tt = profile.command(1, "tiktok", "--file", str(video), "--title", "TT first",
                             "--not-before", "2030-01-01T00:00:10Z", action="upload-video",
                             env=gate("tt"))
        wait_for_event((tmp_path / "tt").exists, tt)
        assert instagram.submissions == tiktok.submissions == []
        advance(10)
        output = tt.communicate(timeout=15)[0]
        assert tt.returncode == 0 and "submitted" in output and "8042" in output, output
        assert tiktok.submissions == [{"caption": "TT first", "files": ["TT.mp4"]}]
        assert tiktok.submitted_at == [epoch + 10]
        assert instagram.submissions == [] and profile.stops == []
        assert draft.url == location and draft.locator("[contenteditable]").inner_text() == "IG on time"
        draft.locator("[contenteditable]").fill("IG still editable")
        draft.locator("[contenteditable]").fill("IG on time")
        assert profile.browser.contexts[0].pages == [profile.browser.contexts[0].pages[0], draft]

        advance(20)
        output = ig.communicate(timeout=10)[0]
        assert ig.returncode == 0, output
        record, = (tmp_path / "cwd-0/.local/instagram-results").glob("*.json")
        assert json.loads(record.read_text())["post_url"] == "https://www.instagram.com/p/offline-fixture/"
        assert instagram.submissions == [{"caption": "IG on time", "files": ["IG.png"]}]
        assert instagram.submitted_at == [epoch + 20]
        assert profile.starts == profile.stops == ["shared"]


@pytest.mark.parametrize(("outcome", "code"), [("lost", 9), ("login", 10)])
def test_tiktok_outcome_after_one_dispatch_preserves_waiting_peer(tmp_path, installations, outcome, code):
    instagram = InstagramSite()
    tiktok = TikTokSite(outcome=outcome)
    with ExitStack() as stack:
        playwright = stack.enter_context(sync_playwright())
        profile = OfflineProfile(tmp_path, stack, installations, playwright,
                                 sites={"www.instagram.com": instagram.handler(block_share=True),
                                        "www.tiktok.com": tiktok.handler()})
        photo = tmp_path / "draft.png"
        photo.touch()
        result = tmp_path / "peer.json"
        ig = profile.command(0, "instagram", "--images", str(photo), "--title", "Editable peer",
                             "--no-publish", "--result", str(result), action="upload-note", env={"HUMANIZE": "0"})
        ig_page = matching_page(profile, lambda p: p.locator("[contenteditable]").count() and
                               p.locator("[contenteditable]").inner_text() == "Editable peer", ig)
        location = ig_page.url
        tt = profile.command(1, "tiktok", "--images", str(photo), "--title", "TT submitted",
                             action="upload-note", env={"HUMANIZE": "0"})
        if outcome == "lost":
            wait_for_event(lambda: bool(tiktok.submissions), tt)
            page = matching_page(profile, lambda p: "tiktokstudio/upload?tab=photo" in p.url, tt)
            page.close()
        output = tt.communicate(timeout=10)[0]
        assert tt.returncode == code, output
        assert ("publish_attempted=true" in output.splitlines()) == (code == 10)
        assert tiktok.submissions == [{"caption": "TT submitted", "files": ["draft.png"]}]
        assert not profile.stops and not instagram.submissions
        assert ig_page.url == location and ig_page.locator("[contenteditable]").inner_text() == "Editable peer"
        ig_page.locator("[contenteditable]").fill("Still editing")
        ig_page.locator("[data-share-blocker]").evaluate("el => el.remove()")
        output = ig.communicate(timeout=8)[0]
        assert ig.returncode == 0, output
        assert json.loads(result.read_text())["status"] == "prepared"
        assert profile.starts == profile.stops == ["shared"]


def test_instagram_login_after_dispatch_retains_result_and_attempt_signal(tmp_path, installations):
    release = threading.Event()

    class UnconfirmedInstagram(InstagramSite):
        def configure(self, submission):
            release.wait(15)
            return {"status": "fail"}

    instagram = UnconfirmedInstagram()
    with ExitStack() as stack:
        playwright = stack.enter_context(sync_playwright())
        profile = OfflineProfile(tmp_path, stack, installations, playwright,
                                 sites={"www.instagram.com": instagram.handler()})
        peer = profile.command(1, "tiktok")
        profile.entered("tiktok", peer)
        peer_page = matching_page(profile, lambda p: "tiktok.com" in p.url, peer)
        editor = peer_page.locator("textarea")
        editor.fill("Peer draft")
        location = peer_page.url
        video = tmp_path / "ig.mp4"
        result = tmp_path / "ig.json"
        video.touch()
        ig = profile.command(0, "instagram", "--file", str(video), "--title", "IG sent",
                             "--result", str(result), action="upload-video", env={"HUMANIZE": "0"})
        stack.callback(release.set)
        wait_for_event(lambda: bool(instagram.submissions), ig)
        ig_page = matching_page(profile, lambda p: "instagram.com" in p.url, ig)
        ig_page.evaluate("history.replaceState(null, '', '/accounts/login/')")
        release.set()
        output = ig.communicate(timeout=10)[0]
        assert ig.returncode == 10 and "publish_attempted=true" in output.splitlines(), output
        assert instagram.submissions == [{"caption": "IG sent", "files": ["ig.mp4"]}]
        assert json.loads(result.read_text())["status"] == "submission_unknown"
        assert not profile.stops and peer_page.url == location and editor.input_value() == "Peer draft"
        editor.fill("Still editable")
        profile.finish("tiktok", peer)
        assert profile.stops == ["shared"]
