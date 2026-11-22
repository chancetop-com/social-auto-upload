# -*- coding: utf-8 -*-
"""BitBrowser draft coverage for TikTok and Instagram (ticket 11).

Each case runs the installed ``sau`` entry against a simulated BitBrowser
Local API and a desktop-opened window whose single Chromium context is served
by the controlled platform pages.  The command must join that context, work on
its own new page, leave the requested draft readable and stop before the final
submit.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from contextlib import ExitStack
from urllib.parse import urlsplit

import pytest
from patchright.sync_api import Error, sync_playwright

from sau_commands.output import NO_PUBLISH_SUCCESS
from tests.shared_publish_sites import InstagramSite, TikTokSite
from tests.test_shared_adspower_process import (
    Handler,
    OfflineProfile,
    installations,
    serve,
)

pytestmark = pytest.mark.skipif(
    sys.platform == "win32", reason="POSIX console-script fixture"
)

WINDOW_ID = "ticket11-bitbrowser-window"
KEY = "offline-bitbrowser-key"
TIKTOK_DRY_RUN_READY = "TikTok 发布就绪，--no-publish 停在发布按钮前（未点击发布）"
INSTAGRAM_DRY_RUN_READY = "Instagram 发布就绪，--no-publish 停在 Share 前（未点击发布）"


class BitBrowserProfile(OfflineProfile):
    """OfflineProfile whose Local API speaks the BitBrowser envelope.

    The window is already open in the desktop client: ``observe`` reports the
    live Chromium process and its debug port, and no ``/browser/open`` call is
    expected.  ``close`` only marks the simulated window stopped so the test
    browser can still inspect the preserved desktop tab.
    """

    def __init__(self, root, stack, entries, playwright, *, sites=None):
        super().__init__(root, stack, entries, playwright, sites=sites)
        self.window_id = WINDOW_ID
        self.window_active = True
        self.requests = []
        self.opens = []
        self.closes = []
        self.alive_queries = []
        self.port_queries = []
        self.health_calls = []
        self.api_keys = []
        self.debug_port = urlsplit(self.endpoint).port
        profile = self

        class Provider(Handler):
            def do_POST(self):
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length) or b"{}")
                profile.api_keys.append(self.headers.get("x-api-key"))
                profile.requests.append((self.path, body))
                if self.path == "/health":
                    profile.health_calls.append(body)
                    data = {}
                elif self.path == "/browser/open":
                    profile.opens.append(body.get("id"))
                    assert body.get("id") == profile.window_id, body
                    profile.window_active = True
                    data = {"ws": profile.endpoint}
                elif self.path == "/browser/close":
                    profile.closes.append(body.get("id"))
                    assert body.get("id") == profile.window_id, body
                    profile.window_active = False
                    data = {}
                elif self.path == "/browser/pids/alive":
                    profile.alive_queries.append(body)
                    assert body.get("ids") == [profile.window_id], body
                    data = [profile.window_id] if profile.window_active else []
                elif self.path == "/browser/ports":
                    profile.port_queries.append(body)
                    data = (
                        {profile.window_id: profile.debug_port}
                        if profile.window_active
                        else {}
                    )
                else:
                    self.send_error(404)
                    return
                self.respond(
                    json.dumps({"success": True, "data": data}).encode(),
                    "application/json",
                )

        self.bit_port = stack.enter_context(serve(Provider))

    def mark_desktop_tab(self, marker):
        page = self.browser.contexts[0].pages[0]
        page.set_content(f"<textarea>{marker}</textarea>")
        return page

    def command(self, platform, *flags, action, env=None):
        """Run one installed CLI process with only BitBrowser credentials."""
        work = self.root / f"cwd-{platform}-{action}"
        work.mkdir(exist_ok=True)
        command_env = {
            **os.environ,
            "HOME": str(self.home),
            "ADSPOWER_API_KEY": "",
            "ADSPOWER_API_BASE": "",
            "MLX_API_TOKEN": "",
            "BITBROWSER_API_KEY": KEY,
            "BITBROWSER_API_BASE": f"http://127.0.0.1:{self.bit_port}/",
            "OFFLINE_OS_PROFILE": str(self.home),
            "PYTHONPATH": "",
            "PYTHONNOUSERSITE": "1",
            "NO_PROXY": "localhost,127.0.0.1",
            **(env or {}),
        }
        child = subprocess.Popen(
            [
                self.entries[0],
                platform,
                action,
                "--profile-id",
                self.window_id,
                *flags,
            ],
            env=command_env,
            cwd=work,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.stack.callback(self.reap, child)
        return child


def matching_page(profile, predicate, child):
    context = profile.browser.contexts[0]
    deadline = time.monotonic() + 25
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
            stdout, stderr = child.communicate()
            pytest.fail(f"{stdout}\n{stderr}")
    pytest.fail(f"Missing editor among {[page.url for page in context.pages]}")


def wait_for_page_state(page, predicate, child, description, timeout=15):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if predicate():
                return
        except Error:
            if page.is_closed():
                break
            raise
        if child.poll() is not None:
            stdout, stderr = child.communicate()
            pytest.fail(f"{description}\n{stdout}\n{stderr}")
        page.wait_for_timeout(50)
    pytest.fail(f"{description}: {page.url}")


def write_media(root, name, data=b"offline-media"):
    path = root / name
    path.write_bytes(data)
    return path


@pytest.fixture
def playwright_session():
    with sync_playwright() as playwright:
        yield playwright


def assert_own_page_in_single_context(profile, page, desktop):
    assert len(profile.browser.contexts) == 1
    assert page is not desktop
    assert profile.browser.contexts[0].pages[0] is desktop
    assert len(profile.browser.contexts[0].pages) == 2
    assert desktop.locator("textarea").input_value() == "desktop draft untouched"


def assert_bitbrowser_window_requests(profile, *, opens=()):
    assert profile.opens == list(opens)
    assert profile.closes == [WINDOW_ID]
    assert profile.health_calls
    assert profile.alive_queries
    assert profile.port_queries
    assert {path for path, _ in profile.requests} == {
        "/health",
        "/browser/pids/alive",
        "/browser/ports",
        "/browser/close",
    }
    assert set(profile.api_keys) == {KEY}


def assert_cli_success(stdout, stderr, *, summary):
    assert stderr == ""
    assert KEY not in stdout + stderr
    assert "mode=bitbrowser" in stdout
    assert f"profile:{WINDOW_ID}" in stdout
    assert summary in stdout


def printed_instagram_result(stdout):
    start = stdout.index('{\n  "platform":')
    return json.loads(stdout[start:])


def test_tiktok_video_draft_joins_the_window_and_stops_before_publish(
    tmp_path, installations, playwright_session
):
    tiktok = TikTokSite(ready=False)
    video = write_media(tmp_path, "ticket11-tiktok-video.mp4")
    caption = "BB11 TikTok video draft 8134"
    with ExitStack() as stack:
        profile = BitBrowserProfile(
            tmp_path,
            stack,
            installations,
            playwright_session,
            sites={"www.tiktok.com": tiktok.handler()},
        )
        desktop = profile.mark_desktop_tab("desktop draft untouched")

        child = profile.command(
            "tiktok",
            "--file",
            str(video),
            "--title",
            caption,
            "--no-publish",
            action="upload-video",
            env={"HUMANIZE": "0"},
        )
        page = matching_page(
            profile,
            lambda candidate: candidate.locator("[contenteditable]").count()
            and candidate.locator("[contenteditable]").inner_text() == caption,
            child,
        )

        assert_own_page_in_single_context(profile, page, desktop)
        assert "tiktokstudio/upload" in page.url
        assert page.evaluate(
            "Array.from(document.querySelector('#video').files, file => file.name)"
        ) == [video.name]
        assert not page.locator('[data-e2e="post_video_button"]').is_enabled()
        # Let the uploader's own media-readiness wait finish while the page
        # keeps the captured draft available to this inspection.
        page.evaluate(
            "document.querySelector('[data-e2e=\"post_video_button\"]').disabled = false"
        )
        wait_for_page_state(
            page,
            lambda: page.locator('[data-e2e="post_video_button"]').is_enabled(),
            child,
            "TikTok media never became ready",
        )
        stdout, stderr = child.communicate(timeout=25)

    assert child.returncode == 0, f"{stdout}\n{stderr}"
    assert f"TikTok video upload: {video}" in stdout.splitlines()
    assert NO_PUBLISH_SUCCESS in stdout.splitlines()
    assert_cli_success(stdout, stderr, summary=TIKTOK_DRY_RUN_READY)
    assert tiktok.submissions == []
    assert_bitbrowser_window_requests(profile)


def test_tiktok_photo_draft_uses_the_photos_entry_and_stops_before_publish(
    tmp_path, installations, playwright_session
):
    tiktok = TikTokSite(ready=False)
    images = [
        write_media(tmp_path, "ticket11-tiktok-photo-1.png"),
        write_media(tmp_path, "ticket11-tiktok-photo-2.png"),
    ]
    title = "BB11 TikTok photo title 8134"
    note = "BB11 TikTok photo caption 8134"
    with ExitStack() as stack:
        profile = BitBrowserProfile(
            tmp_path,
            stack,
            installations,
            playwright_session,
            sites={"www.tiktok.com": tiktok.handler()},
        )
        desktop = profile.mark_desktop_tab("desktop draft untouched")

        child = profile.command(
            "tiktok",
            "--images",
            *(str(image) for image in images),
            "--title",
            title,
            "--note",
            note,
            "--no-publish",
            action="upload-note",
            env={"HUMANIZE": "0"},
        )
        page = matching_page(
            profile,
            lambda candidate: candidate.locator("input[placeholder]").count()
            and candidate.locator("input[placeholder]").input_value() == title
            and candidate.locator("[contenteditable]").inner_text() == note,
            child,
        )

        assert_own_page_in_single_context(profile, page, desktop)
        assert "tiktokstudio/upload?tab=photo" in page.url
        assert page.evaluate(
            "Array.from(document.querySelector('#images').files, file => file.name)"
        ) == [image.name for image in images]
        assert page.locator("div[data-id]").count() > 0
        assert page.locator("input[placeholder]").input_value() == title
        assert page.locator("[contenteditable]").inner_text() == note
        assert not page.locator('[data-e2e="post_video_button"]').is_enabled()
        page.evaluate(
            "document.querySelector('[data-e2e=\"post_video_button\"]').disabled = false"
        )
        wait_for_page_state(
            page,
            lambda: page.locator('[data-e2e="post_video_button"]').is_enabled(),
            child,
            "TikTok photo media never became ready",
        )
        stdout, stderr = child.communicate(timeout=25)

    assert child.returncode == 0, f"{stdout}\n{stderr}"
    assert "TikTok note upload: 2 images" in stdout.splitlines()
    assert NO_PUBLISH_SUCCESS in stdout.splitlines()
    assert_cli_success(stdout, stderr, summary=TIKTOK_DRY_RUN_READY)
    assert tiktok.submissions == []
    assert_bitbrowser_window_requests(profile)


def test_instagram_video_draft_joins_the_window_and_reports_prepared(
    tmp_path, installations, playwright_session
):
    instagram = InstagramSite()
    video = write_media(tmp_path, "ticket11-instagram-video.mp4")
    caption = "BB11 Instagram video draft 8134"
    result_file = tmp_path / "instagram-video-result.json"
    with ExitStack() as stack:
        profile = BitBrowserProfile(
            tmp_path,
            stack,
            installations,
            playwright_session,
            sites={"www.instagram.com": instagram.handler(block_share=True)},
        )
        desktop = profile.mark_desktop_tab("desktop draft untouched")

        child = profile.command(
            "instagram",
            "--file",
            str(video),
            "--title",
            caption,
            "--result",
            str(result_file),
            "--no-publish",
            action="upload-video",
            env={"HUMANIZE": "0"},
        )
        page = matching_page(
            profile,
            lambda candidate: candidate.locator("[contenteditable]").count()
            and candidate.locator("[contenteditable]").inner_text() == caption,
            child,
        )

        assert_own_page_in_single_context(profile, page, desktop)
        assert "instagram.com" in page.url
        wait_for_page_state(
            page,
            lambda: json.loads(page.evaluate("document.body.dataset.observed"))[
                "files"
            ]
            == [video.name],
            child,
            "Instagram video was not attached",
        )
        assert page.locator("[contenteditable]").inner_text() == caption
        assert page.locator("[data-share-blocker]").count() == 1
        assert instagram.submissions == []
        page.locator("[data-share-blocker]").evaluate("blocker => blocker.remove()")
        stdout, stderr = child.communicate(timeout=25)

    assert child.returncode == 0, f"{stdout}\n{stderr}"
    assert_cli_success(stdout, stderr, summary=INSTAGRAM_DRY_RUN_READY)
    printed = printed_instagram_result(stdout)
    saved = json.loads(result_file.read_text(encoding="utf-8"))
    assert printed == saved
    assert saved["platform"] == "instagram"
    assert saved["status"] == "prepared"
    assert saved["title"] == caption
    assert instagram.submissions == []
    assert_bitbrowser_window_requests(profile)


def test_instagram_photo_draft_joins_the_window_and_reports_prepared(
    tmp_path, installations, playwright_session
):
    instagram = InstagramSite()
    images = [
        write_media(tmp_path, "ticket11-instagram-photo-1.png"),
        write_media(tmp_path, "ticket11-instagram-photo-2.png"),
    ]
    caption = "BB11 Instagram photo draft 8134"
    result_file = tmp_path / "instagram-photo-result.json"
    with ExitStack() as stack:
        profile = BitBrowserProfile(
            tmp_path,
            stack,
            installations,
            playwright_session,
            sites={"www.instagram.com": instagram.handler(block_share=True)},
        )
        desktop = profile.mark_desktop_tab("desktop draft untouched")

        child = profile.command(
            "instagram",
            "--images",
            *(str(image) for image in images),
            "--title",
            caption,
            "--result",
            str(result_file),
            "--no-publish",
            action="upload-note",
            env={"HUMANIZE": "0"},
        )
        page = matching_page(
            profile,
            lambda candidate: candidate.locator("[contenteditable]").count()
            and candidate.locator("[contenteditable]").inner_text() == caption,
            child,
        )

        assert_own_page_in_single_context(profile, page, desktop)
        assert "instagram.com" in page.url
        wait_for_page_state(
            page,
            lambda: json.loads(page.evaluate("document.body.dataset.observed"))[
                "files"
            ]
            == [image.name for image in images],
            child,
            "Instagram photos were not attached",
        )
        assert page.locator("[contenteditable]").inner_text() == caption
        assert page.locator("[data-share-blocker]").count() == 1
        assert instagram.submissions == []
        page.locator("[data-share-blocker]").evaluate("blocker => blocker.remove()")
        stdout, stderr = child.communicate(timeout=25)

    assert child.returncode == 0, f"{stdout}\n{stderr}"
    assert_cli_success(stdout, stderr, summary=INSTAGRAM_DRY_RUN_READY)
    printed = printed_instagram_result(stdout)
    saved = json.loads(result_file.read_text(encoding="utf-8"))
    assert printed == saved
    assert saved["platform"] == "instagram"
    assert saved["status"] == "prepared"
    assert saved["title"] == caption
    assert instagram.submissions == []
    assert_bitbrowser_window_requests(profile)
