"""Installed YouTube commands using an offline Studio and a live peer draft."""
from contextlib import ExitStack
from urllib.parse import parse_qs, urlsplit

import pytest
from patchright.sync_api import sync_playwright

from tests.test_shared_adspower_process import Handler, OfflineProfile, installations, pytestmark


class Studio:
    def __init__(self, outcome):
        self.outcome = outcome
        self.requests = []
        self.submissions = []

    def site(self):
        studio = self

        class Site(Handler):
            def do_GET(self):
                path = urlsplit(self.path).path
                studio.requests.append((self.headers["Host"], path))
                if path == "/":
                    self.send_response(302)
                    self.send_header("Location", "/channel/offline")
                    self.end_headers()
                elif path == "/upload":
                    self.respond(studio.editor().encode(), "text/html")
                elif path == "/record":
                    fields = parse_qs(urlsplit(self.path).query)
                    studio.submissions.append((fields["title"][0], fields["file"][0]))
                    self.respond(b"OK", "text/plain")
                else:
                    self.respond(b"<p>Offline Studio</p>", "text/html")

        return Site

    def editor(self):
        return """
            <input type=file>
            <div id=title-textarea><div id=textbox contenteditable=true>old title</div></div>
            <tp-yt-paper-radio-button name=VIDEO_MADE_FOR_KIDS_NOT_MFK>Adults</tp-yt-paper-radio-button>
            <tp-yt-paper-radio-button name=PUBLIC>Public</tp-yt-paper-radio-button>
            <span class=progress-label>Checks complete</span>
            <button id=done-button>Publish</button>
            <script>
            document.querySelector('#done-button').onclick = async () => {
                const title = document.querySelector('#textbox').innerText;
                const file = document.querySelector('input').files[0].name;
                await fetch('/record?' + new URLSearchParams({title, file}));
                history.pushState({}, '', '/signin');
                document.body.innerHTML = '<button id=close-button>Close</button>';
            };
            </script>
        """


@pytest.fixture
def studio_profile(request, tmp_path, installations):
    studio = Studio(request.param)
    site = studio.site()
    with ExitStack() as stack:
        playwright = stack.enter_context(sync_playwright())
        profile = OfflineProfile(tmp_path, stack, installations, playwright,
                                 sites={"studio.youtube.com": site, "www.youtube.com": site})
        peer = profile.command(0, "instagram")
        profile.entered("instagram", peer)
        context = profile.browser.contexts[0]
        # A protocol turn delivers new-target events from the independent CLI connection.
        profile.browser.new_browser_cdp_session().send("Target.getTargets")
        draft, = [p for p in context.pages if "instagram.com" in p.url]
        original_pages = set(context.pages)
        original_url = draft.url
        draft.locator("textarea").fill("peer draft")
        yield studio, profile
        assert draft.url == original_url
        assert draft.locator("textarea").input_value() == "peer draft"
        draft.locator("textarea").fill("peer still editing")
        assert draft.locator("textarea").input_value() == "peer still editing"
        assert set(context.pages) == original_pages
        assert profile.starts == ["shared"] and not profile.stops
        profile.finish("instagram", peer)
        assert profile.stops == ["shared"]


@pytest.mark.parametrize("studio_profile", ["post-login"], indirect=True)
def test_video_reports_post_submit_login_and_preserves_peer(studio_profile):
    studio, profile = studio_profile
    video = profile.root / "synthetic.mp4"
    video.write_bytes(b"offline fixture")
    child = profile.command(1, "youtube", "--file", str(video), "--title", "YouTube marker",
                            action="upload-video", env={"HUMANIZE": "0"})
    output = child.communicate(timeout=32)[0]
    assert child.returncode == 10, output
    assert "publish_attempted=true" in output.splitlines()
    assert "AdsPower" in output
    assert "YouTube video upload submitted" not in output
    assert studio.submissions == [("YouTube marker", video.name)]
