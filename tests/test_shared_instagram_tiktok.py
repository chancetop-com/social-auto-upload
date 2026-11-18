"""Installed publishing commands with independent connections to a loopback Chromium."""
import sys
import time
from contextlib import ExitStack

import pytest
from patchright.sync_api import sync_playwright

from tests.test_shared_adspower_process import Handler, OfflineProfile, installations


pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="POSIX console-script fixture")


def matching_page(profile, predicate, child):
    context = profile.browser.contexts[0]
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        context.pages[0].wait_for_timeout(50)
        for page in context.pages:
            if predicate(page):
                return page
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
