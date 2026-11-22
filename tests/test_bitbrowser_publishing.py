# -*- coding: utf-8 -*-
"""Facebook, Facebook Page and YouTube publishing in a BitBrowser window.

Ticket 13 covers the five publish entries without a pre-publish stop switch.
Each test runs the formal ``sau`` console script against a loopback BitBrowser
Local API and controlled platform pages, then checks the exact window ID, the
publish target, page ownership, stdout/stderr, exit code and submission count.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
from contextlib import ExitStack
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from patchright.sync_api import sync_playwright

from tests.test_shared_adspower_process import (
    Handler,
    OfflineProfile,
    installations,
    pytestmark,
    serve,
)
from tests.test_shared_facebook_process import FacebookSite
from tests.test_shared_youtube_cli import Studio

WINDOW = "window-13-7f3c9a"
TOKEN = "SENTINEL-BITBROWSER-TOKEN-13"
EPOCH = 1893456000  # 2030-01-01 00:00:00 UTC
CLOCK_FIXTURES = Path(__file__).parent / "fixtures" / "publish_clock"
ANSI = re.compile(r"\x1b\[[0-9;]*m")


def plain(stream):
    """Remove the CLI's ANSI colouring without hiding any message text."""
    return ANSI.sub("", stream)


def lines(stream):
    return plain(stream).splitlines()


def advance(profile, seconds):
    clock = profile.root / "clock"
    pending = clock.with_suffix(".tmp")
    pending.write_text(str(EPOCH + seconds))
    pending.replace(clock)


def wait_until(check, child, timeout=20, message="CLI did not reach its offline state"):
    deadline = time.monotonic() + timeout
    while not check():
        if child.poll() is not None:
            out, err = child.communicate()
            pytest.fail(f"{message}\nexit={child.returncode}\nstdout={out}\nstderr={err}")
        if time.monotonic() >= deadline:
            pytest.fail(message)
        time.sleep(.025)


class BitBrowserProfile(OfflineProfile):
    """A disposable Chromium window exposed through a BitBrowser Local API."""

    default_profile_id = WINDOW

    def __init__(self, root, stack, entries, playwright, *, sites=None):
        super().__init__(root, stack, entries, playwright, sites=sites)
        self.active = False
        self.keys = []
        self.starts = []
        self.stops = []
        self.open_bodies = []
        self.close_bodies = []
        self.alive_bodies = []
        self.port_bodies = []
        self.open_response = None
        self.stop_response = None
        self.cdp_port = int(urlsplit(self.endpoint).port)
        profile = self

        class Provider(Handler):
            def respond_json(self, payload):
                self.respond(json.dumps(payload).encode(), "application/json")

            def body(self):
                length = int(self.headers.get("Content-Length") or 0)
                return json.loads(self.rfile.read(length)) if length else {}

            def do_POST(self):
                profile.keys.append(self.headers.get("x-api-key"))
                request = self.body()
                if self.path == "/health":
                    self.respond_json({"success": True, "data": None})
                elif self.path == "/browser/open":
                    profile.open_bodies.append(request)
                    profile.starts.append(request.get("id"))
                    if profile.open_response is not None:
                        return profile.open_response(self)
                    profile.active = True
                    self.respond_json(
                        {"success": True, "data": {"ws": profile.endpoint}}
                    )
                elif self.path == "/browser/close":
                    profile.close_bodies.append(request)
                    profile.stops.append(request.get("id"))
                    if profile.stop_response is not None:
                        return profile.stop_response(self)
                    profile.active = False
                    self.respond_json({"success": True, "data": None})
                elif self.path == "/browser/pids/alive":
                    profile.alive_bodies.append(request)
                    ids = request.get("ids") or []
                    alive = [
                        value
                        for value in ids
                        if profile.active and value == WINDOW
                    ]
                    self.respond_json({"success": True, "data": alive})
                elif self.path == "/browser/ports":
                    profile.port_bodies.append(request)
                    data = {WINDOW: str(profile.cdp_port)} if profile.active else {}
                    self.respond_json({"success": True, "data": data})
                else:
                    self.send_error(404)

        self.bitbrowser_port = stack.enter_context(serve(Provider))

    def command(self, installation, platform, *flags, action="upload-video", env=None):
        work = self.root / f"cwd-{installation}"
        work.mkdir(exist_ok=True)
        command_env = {
            **os.environ,
            "HOME": str(self.home),
            "ADSPOWER_API_KEY": "",
            "MLX_API_TOKEN": "",
            "BITBROWSER_API_KEY": TOKEN,
            "BITBROWSER_API_BASE": f"http://127.0.0.1:{self.bitbrowser_port}",
            "OFFLINE_OS_PROFILE": str(self.home),
            "PYTHONPATH": "",
            "PYTHONNOUSERSITE": "1",
            "NO_PROXY": "localhost,127.0.0.1",
            **(env or {}),
        }
        child = subprocess.Popen(
            [
                self.entries[installation],
                platform,
                action,
                "--profile-id",
                WINDOW,
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


@pytest.fixture
def publishing_profile(tmp_path, installations):
    with ExitStack() as stack:
        facebook = FacebookSite()
        studio = Studio("success")
        studio_site = studio.site()
        profile = BitBrowserProfile(
            tmp_path,
            stack,
            installations,
            stack.enter_context(sync_playwright()),
            sites={
                "www.facebook.com": facebook.handler(),
                "business.facebook.com": facebook.handler(),
                "studio.youtube.com": studio_site,
                "www.youtube.com": studio_site,
            },
        )
        yield profile, facebook, studio


def finish(child, code, timeout=45):
    out, err = child.communicate(timeout=timeout)
    assert child.returncode == code, f"exit={child.returncode}\nstdout={out}\nstderr={err}"
    return out, err


def media(profile, name, content=b"offline media"):
    path = profile.root / name
    path.write_bytes(content)
    return path


def publish_waiting(profile, installation, platform, action, flags, *, env=None):
    """Start a publish command and wait at its final pre-submit clock gate."""
    clock = profile.root / "clock"
    gate = profile.root / f"waiting-{platform}-{action}"
    clock.write_text(str(EPOCH))
    child = profile.command(
        installation,
        platform,
        *flags,
        "--not-before",
        "2030-01-01T00:00:30Z",
        action=action,
        env={
            "HUMANIZE": "0",
            "PYTHONPATH": str(CLOCK_FIXTURES),
            "SAU_TEST_CLOCK": str(clock),
            "SAU_TEST_GATE_ENTERED": str(gate),
            **(env or {}),
        },
    )
    wait_until(gate.exists, child, timeout=30, message="publish gate was not reached")
    return child


def editor_page(profile, child, hostname):
    context = profile.browser.contexts[0]
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        context.pages[0].wait_for_timeout(50)
        editors = [
            page
            for page in context.pages
            if page.url and hostname in (urlsplit(page.url).hostname or "")
        ]
        if editors:
            assert len(editors) == 1, [page.url for page in editors]
            return editors[0]
        if child.poll() is not None:
            out, err = child.communicate()
            pytest.fail(f"exit={child.returncode}\nstdout={out}\nstderr={err}")
    pytest.fail(f"editor page missing from {[page.url for page in context.pages]}")


def wait_page_closed(profile, page, timeout=5):
    deadline = time.monotonic() + timeout
    while not page.is_closed():
        try:
            profile.browser.new_browser_cdp_session().send("Target.getTargets")
        except Exception:
            pass
        if time.monotonic() >= deadline:
            return False
        time.sleep(.05)
    return True


def assert_window_contract(profile, out, err):
    assert profile.open_bodies == [{"id": WINDOW}]
    assert profile.close_bodies == [{"id": WINDOW}]
    assert profile.starts == [WINDOW] and profile.stops == [WINDOW]
    assert profile.alive_bodies and all(
        body == {"ids": [WINDOW]} for body in profile.alive_bodies
    )
    assert profile.keys and all(key == TOKEN for key in profile.keys)
    for stream in (out, err):
        assert TOKEN not in stream
        assert f"127.0.0.1:{profile.bitbrowser_port}" not in stream


PUBLISH_CASES = (
    ("facebook", "upload-video", "ticket13.mp4"),
    ("facebook", "upload-note", "ticket13.png"),
    ("facebook-page", "upload-video", "ticket13-page.mp4"),
    ("facebook-page", "upload-note", "ticket13-page.png"),
    ("youtube", "upload-video", "ticket13.mp4"),
)


def success_flags(platform, action, path, result):
    flags = [
        "--file" if action == "upload-video" else "--images",
        str(path),
        "--title",
        "Ticket 13 " + platform + " " + action,
    ]
    if platform == "facebook-page":
        flags += ["--page", "Page A", "--result", str(result)]
    return flags


@pytest.mark.parametrize(
    ("platform", "action", "filename"),
    PUBLISH_CASES,
    ids=["facebook-video", "facebook-note", "page-video", "page-note", "youtube"],
)
def test_each_publish_entry_submits_exactly_once(
    publishing_profile, platform, action, filename
):
    profile, site, studio = publishing_profile
    source = media(profile, filename)
    result = profile.root / "publish-result.json"
    child = publish_waiting(
        profile,
        1,
        platform,
        action,
        success_flags(platform, action, source, result),
    )

    host = {
        "facebook": "www.facebook.com",
        "facebook-page": "business.facebook.com",
        "youtube": "www.youtube.com",
    }[platform]
    desktop, = [
        page
        for page in profile.browser.contexts[0].pages
        if page.url == "about:blank"
    ]
    editor = editor_page(profile, child, host)
    assert editor is not desktop
    assert len(profile.browser.contexts[0].pages) == 2

    advance(profile, 30)
    out, err = finish(child, 0)

    title = "Ticket 13 " + platform + " " + action
    if platform == "facebook":
        expected = (
            f"Facebook video upload submitted: {source}"
            if action == "upload-video"
            else "Facebook image post submitted"
        )
        assert expected in lines(out)
        post, = site.personal_posts
        assert (post["actor"], post["id"], post["files"], post["clicks"]) == (
            "Personal author",
            "777",
            [filename],
            1,
        )
        assert post["caption"] == title
    elif platform == "facebook-page":
        post, = site.posts
        assert (post["actor"], post["id"], post["file"]) == (
            "Page A",
            "111",
            filename,
        )
        assert post["title"] == (title if action == "upload-video" else "")
        record = json.loads(result.read_text())
        assert (
            record["platform"],
            record["page_name"],
            record["page_id"],
            record["title"],
        ) == ("facebook-page", "Page A", "111", title)
        expected_status = "processing" if action == "upload-video" else "published"
        assert record["status"] == expected_status
        assert f'"status": "{expected_status}"' in plain(out)
        assert '"page_name": "Page A"' in plain(out)
    else:
        assert f"YouTube video upload submitted: {source}" in lines(out)
        record, = studio.records
        assert record == {
            "title": title,
            "description": "",
            "keywords": "page-keyword",
            "file": filename,
        }
        assert studio.submissions == [(title, filename)]

    assert wait_page_closed(profile, editor) and not desktop.is_closed()
    assert profile.browser.contexts[0].pages == [desktop]
    assert plain(err) == ""
    assert_window_contract(profile, out, err)


def run_publish(profile, installation, platform, action, flags, *, env=None):
    return profile.command(
        installation,
        platform,
        *flags,
        action=action,
        env={"HUMANIZE": "0", **(env or {})},
    )


def note_flags(profile, platform, filename="ticket13.png"):
    source = media(profile, filename)
    flags = ["--images", str(source), "--title", f"Ticket 13 {platform} note"]
    if platform == "facebook-page":
        flags += ["--page", "Page A"]
    return flags


def video_flags(profile, platform, filename="ticket13.mp4"):
    source = media(profile, filename)
    flags = ["--file", str(source), "--title", f"Ticket 13 {platform} video"]
    if platform == "facebook-page":
        flags += ["--page", "Page A"]
    return flags


PRE_LOGIN_CASES = (
    ("facebook", "upload-note", "www.facebook.com"),
    ("facebook-page", "upload-note", "business.facebook.com"),
    ("youtube", "upload-video", "www.youtube.com"),
)


@pytest.mark.parametrize(
    ("platform", "action", "host"),
    PRE_LOGIN_CASES,
    ids=["facebook", "facebook-page", "youtube"],
)
def test_login_before_dispatch_exits_ten_without_attempt_marker(
    publishing_profile, platform, action, host
):
    profile, site, studio = publishing_profile
    site.logged_out = True
    if platform == "youtube":
        studio.outcome = "pre-login"
    flags = (
        note_flags(profile, platform)
        if action == "upload-note"
        else video_flags(profile, platform)
    )
    child = run_publish(profile, 1, platform, action, flags)
    out, err = finish(child, 10)

    assert "publish_attempted=true" not in lines(err)
    assert "比特浏览器" in err and WINDOW in err
    assert not site.personal_posts and not site.posts and not studio.submissions
    desktop = profile.browser.contexts[0].pages
    assert len(desktop) == 1 and desktop[0].url == "about:blank"
    assert_window_contract(profile, out, err)


POST_LOGIN_CASES = (
    ("facebook", "upload-video"),
    ("facebook-page", "upload-note"),
    ("youtube", "upload-video"),
)


@pytest.mark.parametrize(
    ("platform", "action"),
    POST_LOGIN_CASES,
    ids=["facebook", "facebook-page", "youtube"],
)
def test_login_after_dispatch_exits_ten_with_a_standalone_attempt_marker(
    publishing_profile, platform, action
):
    profile, site, studio = publishing_profile
    if platform == "facebook":
        site.personal_outcome = "login"
    elif platform == "facebook-page":
        site.page_unknown = site.page_expires_on_submit = True
    else:
        studio.outcome = "post-login"
    flags = (
        note_flags(profile, platform)
        if action == "upload-note"
        else video_flags(profile, platform)
    )
    child = run_publish(profile, 1, platform, action, flags)
    out, err = finish(child, 10)

    assert lines(err).count("publish_attempted=true") == 1
    if platform == "youtube":
        assert "YouTube 需要登录或验证" in err
    else:
        assert "需要重新登录" in err
    if platform == "facebook":
        post, = site.personal_posts
        assert post["clicks"] == 1
    elif platform == "facebook-page":
        post, = site.posts
        assert (post["actor"], post["caption"]) == (
            "Page A",
            "Ticket 13 facebook-page note",
        )
    else:
        assert studio.submissions == [("Ticket 13 youtube video", "ticket13.mp4")]
    assert_window_contract(profile, out, err)


def test_personal_disconnect_after_dispatch_is_unknown_and_never_replays(
    publishing_profile,
):
    profile, site, _ = publishing_profile
    site.personal_outcome = "unconfirmed"
    child = run_publish(profile, 1, "facebook", "upload-note", note_flags(profile, "facebook"))
    wait_until(lambda: bool(site.personal_posts), child)
    editor_page(profile, child, "www.facebook.com").close()
    out, err = finish(child, 9)

    assert "禁止自动重发" in err
    assert "publish_attempted=true" not in lines(err)
    assert "Facebook image post submitted" not in lines(out)
    post, = site.personal_posts
    assert (post["caption"], post["clicks"]) == ("Ticket 13 facebook note", 1)
    assert_window_contract(profile, out, err)


def test_page_unconfirmable_creation_response_exits_nine_without_replay(
    publishing_profile,
):
    profile, site, _ = publishing_profile
    site.page_unknown = True
    result = profile.root / "page-unknown.json"
    flags = video_flags(profile, "facebook-page") + ["--result", str(result)]
    child = run_publish(profile, 1, "facebook-page", "upload-video", flags)
    out, err = finish(child, 9)

    assert "勿重复提交" in err
    assert "publish_attempted=true" not in lines(err)
    assert '"status": "published"' not in plain(out)
    post, = site.posts
    assert (post["actor"], post["id"], post["file"], post["caption"]) == (
        "Page A",
        "111",
        "ticket13.mp4",
        "",
    )
    assert json.loads(result.read_text())["status"] == "submission_unknown"
    assert_window_contract(profile, out, err)


def test_youtube_unconfirmed_submit_exits_nine_without_replay(
    publishing_profile,
):
    profile, _, studio = publishing_profile
    studio.outcome = "unconfirmed"
    child = run_publish(profile, 1, "youtube", "upload-video", video_flags(profile, "youtube"))
    out, err = finish(child, 9)

    assert "禁止自动重发" in err
    assert "publish_attempted=true" not in lines(err)
    assert "YouTube video upload submitted" not in lines(out)
    assert studio.submissions == [("Ticket 13 youtube video", "ticket13.mp4")]
    assert_window_contract(profile, out, err)


def test_cleanup_failure_while_exiting_nine_keeps_the_unknown_result(
    publishing_profile,
):
    profile, site, _ = publishing_profile
    site.page_unknown = True
    profile.stop_response = lambda request: request.send_error(429)
    result = profile.root / "cleanup-nine.json"
    flags = video_flags(profile, "facebook-page") + ["--result", str(result)]
    child = run_publish(profile, 1, "facebook-page", "upload-video", flags)
    out, err = finish(child, 9)

    assert "勿重复提交" in err
    assert "publish_attempted=true" not in lines(err)
    assert "停止或清理失败" in plain(out)
    assert json.loads(result.read_text())["status"] == "submission_unknown"
    post, = site.posts
    assert (post["actor"], post["id"], post["file"]) == (
        "Page A",
        "111",
        "ticket13.mp4",
    )
    assert profile.active
    assert_window_contract(profile, out, err)


def test_cleanup_failure_while_exiting_post_dispatch_ten_keeps_the_token(
    publishing_profile,
):
    profile, site, _ = publishing_profile
    site.personal_outcome = "login"
    profile.stop_response = lambda request: request.respond(
        json.dumps({"success": False, "msg": "offline close rejected"}).encode(),
        "application/json",
    )
    child = run_publish(
        profile, 1, "facebook", "upload-note", note_flags(profile, "facebook")
    )
    out, err = finish(child, 10)

    assert lines(err).count("publish_attempted=true") == 1
    assert "需要重新登录" in err
    assert "停止或清理失败" in plain(out)
    post, = site.personal_posts
    assert (post["caption"], post["clicks"]) == ("Ticket 13 facebook note", 1)
    assert profile.active
    assert_window_contract(profile, out, err)


def test_cleanup_failure_while_exiting_pre_dispatch_ten_keeps_the_marker_absent(
    publishing_profile,
):
    profile, site, _ = publishing_profile
    site.logged_out = True
    profile.stop_response = lambda request: request.send_error(429)
    child = run_publish(
        profile, 1, "facebook-page", "upload-note", note_flags(profile, "facebook-page")
    )
    out, err = finish(child, 10)

    assert "publish_attempted=true" not in lines(err)
    assert "比特浏览器" in err and WINDOW in err
    assert "停止或清理失败" in plain(out)
    assert not site.posts
    assert profile.active
    assert_window_contract(profile, out, err)
