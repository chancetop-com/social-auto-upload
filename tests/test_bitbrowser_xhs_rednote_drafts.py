"""Prepare mainland Xiaohongshu and Rednote drafts through installed BitBrowser CLIs.

Each case starts the formal ``sau`` entry with ``BITBROWSER_API_KEY`` set, a
simulated BitBrowser Local API, and controlled creator-center pages.  The page
blocks the publisher at the final pre-publish ARM check so the test can read the
draft marker back before the command exits; no publish click is recorded.
"""
import json
import os
import subprocess
import sys
import time
from contextlib import ExitStack
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from patchright.sync_api import sync_playwright

from sau_commands.output import NO_PUBLISH_SUCCESS
from tests.test_shared_adspower_process import (
    Handler,
    OfflineProfile,
    installations,
    serve,
)

pytestmark = pytest.mark.skipif(
    sys.platform == "win32", reason="POSIX console-script fixture"
)

FIXTURES = Path(__file__).with_name("fixtures")
WINDOW_KEY = "offline-bitbrowser-key"
PLATFORMS = {
    "xiaohongshu": {
        "host": "creator.xiaohongshu.com",
        "label": "Xiaohongshu",
        "window": "xhs-window-12",
    },
    "rednote": {
        "host": "creator.rednote.com",
        "label": "Rednote",
        "window": "rednote-window-12",
    },
}

# The uploader types the body after loading the page.  Marking the publish
# button not-ready on the first body input parks both video and note runs at the
# final ARM check, after the metadata is readable and before any publish click.
DRAFT_GATE = b"""
<script>
  (() => {
    const button = document.querySelector('xhs-publish-btn');
    const body = document.querySelector('.tiptap');
    let blocked = false;
    body.addEventListener('input', () => {
      if (!blocked) {
        blocked = true;
        button.setAttribute('is-publish', 'false');
      }
    });
  })();
</script>
"""


class CreatorCenter:
    """Controlled creator center that records loads and publish submissions."""

    def __init__(self):
        self.documents = []
        self.submissions = []

    def handler(self):
        site = self

        class Creator(Handler):
            def do_GET(self):
                if self.path.startswith("/publish/publish?"):
                    query = parse_qs(urlsplit(self.path).query)
                    site.documents.append(query["target"][0])
                    body = (FIXTURES / "xhs_creator.html").read_bytes() + DRAFT_GATE
                    self.respond(body, "text/html")
                elif self.path == "/ready.js":
                    self.respond(b"", "application/javascript")
                else:
                    self.respond(b"", "text/plain")

            def do_POST(self):
                assert self.path == "/submit"
                site.submissions.append(
                    json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                )
                self.respond(b'{"next": null}', "application/json")

        return Creator


class BitBrowserApi:
    """Simulated Local API for one window in a cold-start state."""

    def __init__(self, profile, window_id):
        self.profile = profile
        self.window_id = window_id
        self.running = False
        self.calls = []
        self.open_ids = []
        self.close_ids = []
        self.alive_batches = []
        self.port = urlsplit(profile.endpoint).port

    def handler(self):
        api = self

        class Api(Handler):
            def do_POST(self):
                length = int(self.headers.get("Content-Length", "0"))
                body = json.loads(self.rfile.read(length)) if length else {}
                api.calls.append(
                    (self.path, body, self.headers.get("x-api-key"))
                )
                if self.headers.get("x-api-key") != WINDOW_KEY:
                    self.respond(
                        json.dumps(
                            {"success": False, "msg": "请检查 Token"}
                        ).encode(),
                        "application/json",
                    )
                    return

                if self.path == "/health":
                    payload = {"success": True, "data": {}}
                elif self.path == "/browser/pids/alive":
                    api.alive_batches.append(list(body.get("ids", [])))
                    data = [api.window_id] if api.running else []
                    payload = {"success": True, "data": data}
                elif self.path == "/browser/ports":
                    data = (
                        {api.window_id: str(api.port)} if api.running else {}
                    )
                    payload = {"success": True, "data": data}
                elif self.path == "/browser/open":
                    api.open_ids.append(body.get("id"))
                    api.running = True
                    payload = {
                        "success": True,
                        "data": {"ws": api.profile.endpoint},
                    }
                elif self.path == "/browser/close":
                    api.close_ids.append(body.get("id"))
                    api.running = False
                    payload = {"success": True, "data": None}
                else:
                    self.respond(
                        json.dumps(
                            {"success": False, "msg": "unknown endpoint"}
                        ).encode(),
                        "application/json",
                    )
                    return
                self.respond(json.dumps(payload).encode(), "application/json")

        return Api


class BitBrowserProfile(OfflineProfile):
    def __init__(self, root, stack, entries, playwright, *, sites, window_id):
        super().__init__(root, stack, entries, playwright, sites=sites)
        self.window_id = window_id
        self.bitbrowser = BitBrowserApi(self, window_id)
        self.bitbrowser_port = stack.enter_context(
            serve(self.bitbrowser.handler())
        )

    def command(self, installation, platform, action, *, title, body, media):
        work = self.root / f"cwd-{platform}-{action}"
        work.mkdir(exist_ok=True)
        command_env = {
            **os.environ,
            "HOME": str(self.home),
            "ADSPOWER_API_KEY": "",
            "ADSPOWER_API_BASE": "",
            "MLX_API_TOKEN": "",
            "BITBROWSER_API_KEY": WINDOW_KEY,
            "BITBROWSER_API_BASE": f"http://127.0.0.1:{self.bitbrowser_port}",
            "OFFLINE_OS_PROFILE": str(self.home),
            "PYTHONPATH": "",
            "PYTHONNOUSERSITE": "1",
            "NO_PROXY": "localhost,127.0.0.1",
            "HUMANIZE": "0",
        }
        if action == "upload-video":
            media_flags = ["--file", str(media), "--desc", body]
        else:
            media_flags = ["--images", str(media), "--note", body]
        return subprocess.Popen(
            [
                self.entries[installation],
                platform,
                action,
                "--profile-id",
                self.window_id,
                "--title",
                title,
                *media_flags,
                "--no-publish",
            ],
            env=command_env,
            cwd=work,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )


@pytest.fixture
def centers(tmp_path, installations):
    sites = {name: CreatorCenter() for name in PLATFORMS}
    with ExitStack() as stack:
        playwright = stack.enter_context(sync_playwright())

        def make(platform):
            root = tmp_path / platform
            root.mkdir()
            return BitBrowserProfile(
                root,
                stack,
                installations,
                playwright,
                sites={
                    PLATFORMS[name]["host"]: site.handler()
                    for name, site in sites.items()
                },
                window_id=PLATFORMS[platform]["window"],
            )

        yield make, sites


def context_pages(profile):
    """Flush target events before reading the shared context's page list."""
    cdp = profile.browser.new_browser_cdp_session()
    try:
        cdp.send("Target.getTargets")
    finally:
        cdp.detach()
    return list(profile.browser.contexts[0].pages)


def wait_for(predicate, child, *, timeout=30):
    deadline = time.monotonic() + timeout
    while True:
        value = predicate()
        if value:
            return value
        if child.poll() is not None:
            stdout, stderr = child.communicate()
            pytest.fail(f"CLI exited {child.returncode}\nSTDOUT:\n{stdout}\nSTDERR:\n{stderr}")
        if time.monotonic() >= deadline:
            pytest.fail("CLI did not reach its draft synchronization point")
        time.sleep(0.025)


def creator_pages(profile, host):
    pages = []
    for page in context_pages(profile):
        try:
            if urlsplit(page.url).hostname == host:
                pages.append(page)
        except Exception:
            continue
    return pages


def draft_ready(page, title, body):
    try:
        return (
            page.get_by_label("Draft title").input_value() == title
            and page.get_by_label("Draft body").inner_text().strip() == body
            and page.locator("xhs-publish-btn").get_attribute("is-publish")
            == "false"
        )
    except Exception:
        return False


def read_draft(page, child, title, body):
    wait_for(lambda: draft_ready(page, title, body), child)
    return (
        page.get_by_label("Draft title").input_value(),
        page.get_by_label("Draft body").inner_text().strip(),
    )


def payload_ids(body):
    """Every window ID a Local API request carries, in body order."""
    if "ids" in body:
        return list(body["ids"])
    if "id" in body:
        return [body["id"]]
    return []


@pytest.mark.parametrize("platform", PLATFORMS)
@pytest.mark.parametrize(
    "action,kind,target",
    [
        ("upload-video", "video", "video"),
        ("upload-note", "note", "image"),
    ],
)
def test_bitbrowser_prepares_xhs_and_rednote_drafts(
    centers, platform, action, kind, target
):
    make, sites = centers
    profile = make(platform)
    meta = PLATFORMS[platform]
    other = next(name for name in PLATFORMS if name != platform)
    host = meta["host"]
    title = f"{platform}-{kind}-draft"
    body = f"{platform} {kind} body marker"
    media = profile.root / (
        f"{platform}-{kind}.mp4" if kind == "video" else f"{platform}-{kind}.png"
    )
    media.write_bytes(b"offline media")

    assert len(profile.browser.contexts) == 1
    original = profile.browser.contexts[0].pages[0]
    original.set_content("<textarea>desktop draft</textarea>")

    child = profile.command(
        0, platform, action, title=title, body=body, media=media
    )
    try:
        page, = wait_for(
            lambda: creator_pages(profile, host) or None, child
        )
        assert urlsplit(page.url).hostname == host
        assert parse_qs(urlsplit(page.url).query)["target"] == [target]

        assert read_draft(page, child, title, body) == (title, body)
        if kind == "video":
            assert page.locator("input.upload-input").evaluate(
                "el => el.files[0]?.name"
            ) == media.name
        else:
            assert page.locator(".img-preview-area .pr").count() == 1
            assert page.locator(".img-preview-area .mask.uploading").count() == 0
            assert page.locator("input.upload-input").evaluate(
                "el => el.files[0]?.name"
            ) == media.name

        # The command owns one new page in the one existing context; the
        # desktop page is untouched and points at the other creator center.
        pages = context_pages(profile)
        assert len(pages) == 2 and original in pages and page in pages
        assert len([item for item in pages if urlsplit(item.url).hostname == host]) == 1
        assert original.locator("textarea").input_value() == "desktop draft"
        assert sites[platform].documents == [target]
        assert sites[other].documents == []
        assert sites[platform].submissions == sites[other].submissions == []

        page.evaluate(
            "document.querySelector('xhs-publish-btn')"
            ".setAttribute('is-publish', 'true')"
        )
        stdout, stderr = child.communicate(timeout=40)
    finally:
        if child.poll() is None:
            child.kill()
            child.communicate(timeout=10)

    assert child.returncode == 0, (stdout, stderr)
    assert stderr == ""
    expected_media = str(media) if kind == "video" else "1 images"
    assert f"{meta['label']} {kind} upload: {expected_media}" in stdout
    assert NO_PUBLISH_SUCCESS in stdout
    assert "upload submitted:" not in stdout
    assert f"{PLATFORMS[other]['label']} {kind} upload:" not in stdout

    api = profile.bitbrowser
    assert api.open_ids == [meta["window"]]
    assert api.close_ids == [meta["window"]]
    assert api.alive_batches and all(
        batch == [meta["window"]] for batch in api.alive_batches
    )
    assert all(key == WINDOW_KEY for _path, _body, key in api.calls)
    assert all(
        item == meta["window"]
        for _path, body, _key in api.calls
        for item in payload_ids(body)
    )
    assert api.running is False
    # The AdsPower double saw no request: only the BitBrowser Local API was used.
    assert profile.keys == [] and profile.starts == [] and profile.stops == []
    assert sites[platform].submissions == sites[other].submissions == []

    assert len(profile.browser.contexts) == 1
    pages = context_pages(profile)
    assert pages == [original]
    assert original.locator("textarea").input_value() == "desktop draft"
