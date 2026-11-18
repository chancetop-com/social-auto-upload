"""Run XHS and Rednote CLI commands in separate installations on an offline Profile."""
import json
import sys
import threading
import time
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
                    if site.outcome == "login-before":
                        body += b"<script>history.replaceState({}, '', '/login')</script>"
                    if site.outcome == "editor-error":
                        body += b'<div class="edit-container"><div class="length-error">Too long</div></div>'
                    if site.outcome == "unavailable":
                        self.send_error(503)
                    else:
                        self.respond(body, "text/html")
                else:
                    self.respond(b"", "text/plain")

            def do_POST(self):
                assert self.path == "/submit"
                site.clicks.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
                next_page = {"success": "/publish/success", "login-after": "/login", "unknown": None}
                self.respond(json.dumps({"next": next_page[site.outcome]}).encode(), "application/json")

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


def target_monitor(profile):
    cdp = profile.browser.new_browser_cdp_session()
    created = []
    cdp.on("Target.targetCreated", lambda event: created.append(event["targetInfo"]["type"]))
    cdp.send("Target.setDiscoverTargets", {"discover": True})
    return cdp, created


def assert_busy(profile, platform, actions):
    cdp, targets = target_monitor(profile)
    try:
        targets.clear()
        for action in actions:
            denied = command(profile, 1, platform, action)
            output = denied.communicate(timeout=8)[0]
            assert denied.returncode == 1 and platform in output and "占用" in output, output
        cdp.send("Target.getTargets")
        assert "page" not in targets
    finally:
        cdp.detach()


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
    assert_busy(profile, "xiaohongshu", ("check", "upload-video"))
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


def test_tiktok_check_joins_while_xhs_waits(creators):
    profile, sites = creators
    xhs = command(profile, 0, "xiaohongshu", "upload-note", when=10)
    wait_for((profile.root / "waiting-xiaohongshu").exists, xhs)
    tiktok = profile.command(1, "tiktok")
    profile.entered("tiktok", tiktok)
    assert_busy(profile, "xiaohongshu", ("check",))
    assert xhs.poll() is None and sites["xiaohongshu"].clicks == []
    profile.finish("tiktok", tiktok)
    assert not profile.stops
    advance(profile, 10)
    assert "Xiaohongshu note upload submitted" in finish(xhs, 0)
    assert len(sites["xiaohongshu"].clicks) == 1 and profile.stops == ["shared"]


@pytest.mark.parametrize("platform", PLATFORMS)
def test_simultaneous_checks_admit_one_and_exclude_a_publisher(creators, platform):
    profile, sites = creators
    site = sites[platform]
    site.release.clear()
    cdp, targets = target_monitor(profile)
    targets.clear()
    children = [command(profile, i, platform) for i in (0, 1)]
    assert site.arrived.wait(15)
    deadline = time.monotonic() + 8
    while all(child.poll() is None for child in children) and time.monotonic() < deadline:
        time.sleep(.025)
    loser, = [child for child in children if child.poll() is not None]
    winner, = [child for child in children if child.poll() is None]
    output = finish(loser, 1)
    assert platform in output and "占用" in output
    cdp.send("Target.getTargets")
    assert targets.count("page") == 1 and site.documents == ["video"]
    cdp.detach()
    assert_busy(profile, platform, ("upload-note",))
    site.release.set()
    assert "valid" in finish(winner, 0).splitlines()
    assert profile.starts == profile.stops == ["shared"]


def draft_page(profile, platform):
    # Flush target events before reading the inspector connection's page list.
    cdp = profile.browser.new_browser_cdp_session()
    cdp.send("Target.getTargets")
    cdp.detach()
    return [page for page in profile.browser.contexts[0].pages
            if urlsplit(page.url).hostname == f"creator.{platform}.com"]


@pytest.mark.parametrize("platform", PLATFORMS)
@pytest.mark.parametrize("action", ["check", "upload-video", "upload-note"])
def test_entry_outcomes_clean_only_their_own_page(creators, platform, action):
    profile, sites = creators
    other, = [name for name in PLATFORMS if name != platform]
    peer = command(profile, 0, other, "upload-video", when=20)
    wait_for((profile.root / f"waiting-{other}").exists, peer)
    page, = draft_page(profile, other)
    url = page.url
    marker = f"{other} draft"
    title = page.get_by_label("Draft title")
    assert title.input_value() == marker
    assert page.get_by_label("Draft body").inner_text().strip() == f"{other} body"
    assert_busy(profile, other, ("check", "upload-note"))
    site = sites[platform]
    if action == "check":
        cases = [("success", 0), ("login-before", 10), ("unavailable", 1)]
    else:
        cases = [("success", 0), ("login-before", 10), ("editor-error", 1),
                 ("login-after", 10), ("unknown", 9)]
    for outcome, code in cases:
        site.outcome = outcome
        site.documents.clear()
        site.clicks.clear()
        child = command(profile, 1, platform, action)
        output = finish(child, code)
        target = "image" if action == "upload-note" else "video"
        assert site.documents == [target]
        assert ("publish_attempted=true" in output.splitlines()) == (outcome == "login-after")
        if action == "check":
            assert ("valid" if code == 0 else "invalid") in output.splitlines()
        elif code == 0:
            assert f"{platform.capitalize()} {action[7:]} upload submitted:" in output
        if action != "check" and outcome in {"success", "login-after", "unknown"}:
            filename = f"{platform}.png" if target == "image" else f"{platform}.mp4"
            assert site.clicks == [{"target": target, "file": filename, "title": f"{platform} draft",
                                    "body": f"{platform} body"}]
        else:
            assert site.clicks == []
        assert draft_page(profile, platform) == []
        assert draft_page(profile, other) == [page]
        assert page.url == url and title.input_value() == marker
        marker = f"peer after {outcome}"
        title.fill(marker)
        assert title.input_value() == marker
        assert peer.poll() is None and sites[other].clicks == [] and not profile.stops

    advance(profile, 20)
    assert f"{other.capitalize()} video upload submitted:" in finish(peer, 0)
    assert sites[other].clicks == [{"target": "video", "file": f"{other}.mp4", "title": marker,
                                   "body": f"{other} body"}]
    assert profile.starts == profile.stops == ["shared"]


@pytest.mark.parametrize("platform", PLATFORMS)
def test_same_platform_can_publish_while_another_profile_is_checking(creators, platform):
    first, sites = creators
    second_root = first.root / "second"
    second_root.mkdir()
    second_site = CreatorSite()
    second = OfflineProfile(second_root, first.stack, first.entries, first.playwright,
                            sites={f"creator.{platform}.com": second_site.handler()})
    second.home = first.home
    second.api_port = first.api_port
    first.profiles["second"] = second
    sites[platform].release.clear()
    checking = command(first, 0, platform)
    wait_for(sites[platform].arrived.is_set, checking)
    publishing = command(second, 1, platform, "upload-note", profile_id="second")
    assert f"{platform.capitalize()} note upload submitted:" in finish(publishing, 0)
    assert second.starts == second.stops == ["second"]
    assert len(second_site.clicks) == 1 and sites[platform].clicks == []
    assert checking.poll() is None and not first.stops
    sites[platform].release.set()
    assert "valid" in finish(checking, 0).splitlines()
    assert first.starts == first.stops == ["shared"]


@pytest.mark.parametrize("platform", PLATFORMS)
def test_platform_stays_busy_while_its_browser_disconnects(creators, platform, monkeypatch):
    import asyncio
    from concurrent.futures import ThreadPoolExecutor
    from patchright.async_api import Browser
    from sau_cli import main

    profile, sites = creators
    closing = threading.Event()
    release = threading.Event()
    close = Browser.close

    async def delayed_disconnect(browser, **kwargs):
        closing.set()
        await asyncio.to_thread(release.wait, 20)
        return await close(browser, **kwargs)

    # Hold the browser connection at the end of the first actual command.
    # The second installation and the observer use their own connections.
    monkeypatch.setattr(Browser, "close", delayed_disconnect)
    monkeypatch.setattr("utils.profile_store._user_profile_directory", lambda: profile.home)
    monkeypatch.setenv("MLX_API_TOKEN", "")
    monkeypatch.setenv("ADSPOWER_API_KEY", "offline-key-0")
    monkeypatch.setenv("ADSPOWER_API_BASE", f"http://127.0.0.1:{profile.api_port}")
    with ThreadPoolExecutor(max_workers=1) as worker:
        first = worker.submit(main, [platform, "check", "--profile-id", "shared"])
        try:
            assert closing.wait(15)
            assert_busy(profile, platform, ("upload-video",))
            assert sites[platform].documents == ["video"]
        finally:
            release.set()
        assert first.result(timeout=15) == 0
    assert profile.starts == profile.stops == ["shared"]
