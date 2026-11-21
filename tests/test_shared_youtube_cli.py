"""Installed YouTube commands using an offline Studio and a live peer draft."""
from contextlib import ExitStack
import json
import threading
import time
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from patchright.sync_api import sync_playwright

from tests.shared_publish_sites import InstagramSite
from tests.test_shared_adspower_process import Handler, OfflineProfile, installations, pytestmark


class Studio:
    def __init__(self, outcome):
        self.outcome = outcome
        self.requests = []
        self.submissions = []
        self.records = []
        self.uploaded_files = []
        self.submitted = threading.Event()

    def site(self):
        studio = self

        class Site(Handler):
            def do_GET(self):
                path = urlsplit(self.path).path
                studio.requests.append((self.headers["Host"], path))
                if path == "/":
                    self.send_response(302)
                    self.send_header("Location", "/signin" if studio.outcome == "pre-login" else "/channel/offline")
                    self.end_headers()
                elif path == "/upload":
                    self.respond(studio.editor().encode(), "text/html")
                elif path == "/record":
                    fields = parse_qs(urlsplit(self.path).query)
                    record = {
                        "title": fields["title"][0],
                        "description": fields.get("description", [""])[0],
                        "keywords": fields.get("keywords", [""])[0],
                        "file": fields["file"][0],
                    }
                    studio.records.append(record)
                    studio.submissions.append((record["title"], record["file"]))
                    studio.uploaded_files.append(json.loads(fields["contents"][0]))
                    self.respond(b"OK", "text/plain")
                    studio.submitted.set()
                else:
                    self.respond(b"<p>Offline Studio</p>", "text/html")

        return Site

    def editor(self):
        return """
            <input type=file>
            <ytcp-thumbnail-uploader><input type=file></ytcp-thumbnail-uploader>
            <div id=title-textarea><div id=textbox contenteditable=true>old title</div></div>
            <div id=description-textarea><div id=textbox contenteditable=true></div></div>
            <div id=description-error style="display:none">Description is too long</div>
            <div id=tags-container><input id=text-input value="page-keyword"></div>
            <button id=toggle-button>Show more</button>
            <tp-yt-paper-radio-button name=VIDEO_MADE_FOR_KIDS_NOT_MFK>Adults</tp-yt-paper-radio-button>
            <tp-yt-paper-radio-button name=PUBLIC>Public</tp-yt-paper-radio-button>
            <span class=progress-label>Checks complete</span>
            <a href="https://youtu.be/offline">Draft link</a>
            <button id=done-button>Publish</button>
            <script>
            const outcome = """ + json.dumps(self.outcome) + """;
            const titleBox = document.querySelector('#title-textarea #textbox');
            const descriptionBox = document.querySelector('#description-textarea #textbox');
            if (outcome === 'description-limit') {
                document.querySelector('#description-error').style.display = 'block';
            }
            const descriptionFaults = ['desc-swallow', 'desc-misplace', 'desc-append'];
            let faulted = false;
            descriptionBox.addEventListener('input', () => {
                if (faulted || !descriptionFaults.includes(outcome)) return;
                faulted = true;
                if (outcome === 'desc-swallow') {
                    descriptionBox.textContent = descriptionBox.textContent.slice(0, -1);
                } else if (outcome === 'desc-misplace') {
                    descriptionBox.textContent = 'MOVED ' + descriptionBox.textContent;
                } else {
                    descriptionBox.textContent += ' EXTRA';
                }
            });
            if (outcome === 'pre-failure') {
                document.body.prepend(document.querySelector('#done-button').cloneNode(true));
            }
            document.querySelector('#done-button').onclick = async () => {
                const title = titleBox.innerText;
                const description = descriptionBox.innerText;
                const keywords = document.querySelector('#tags-container #text-input').value;
                const file = document.querySelector('input').files[0].name;
                const files = [...document.querySelectorAll('input[type=file]')].flatMap(i => [...i.files]);
                const contents = JSON.stringify(await Promise.all(files.map(f => f.text())));
                await fetch('/record?' + new URLSearchParams({title, description, keywords, file, contents}));
                if (outcome === 'unconfirmed' || outcome === 'page-lost') return;
                if (outcome === 'post-login') history.pushState({}, '', '/signin');
                document.body.innerHTML = '<div role=dialog><a href="https://youtu.be/offline">Video</a>' +
                                          '<button id=close-button>Close</button></div>';
            };
            </script>
        """


@pytest.fixture
def studio_profile(request, tmp_path, installations):
    studio = Studio(request.param)
    site = studio.site()
    with ExitStack() as stack:
        playwright = stack.enter_context(sync_playwright())
        instagram = InstagramSite()
        profile = OfflineProfile(tmp_path, stack, installations, playwright,
                                 sites={"studio.youtube.com": site, "www.youtube.com": site,
                                        "www.instagram.com": instagram.handler()})
        photo = tmp_path / "peer.png"
        photo.touch()
        result = tmp_path / "peer-result.json"
        clock = tmp_path / "clock"
        gate = tmp_path / "peer-ready"
        clock.write_text("1893456000")
        peer = profile.command(0, "instagram", "--images", str(photo), "--title", "peer draft",
                               "--result", str(result), "--not-before", "2030-01-01T00:00:10Z",
                               action="upload-note", env={"HUMANIZE": "0",
                                   "PYTHONPATH": str(Path(__file__).with_name("fixtures") / "publish_clock"),
                                   "SAU_TEST_CLOCK": str(clock), "SAU_TEST_GATE_ENTERED": str(gate)})
        deadline = time.monotonic() + 20
        while not gate.exists():
            if peer.poll() is not None:
                pytest.fail(peer.communicate()[0])
            if time.monotonic() >= deadline:
                pytest.fail("Instagram did not reach its publish gate")
            time.sleep(.05)

        context = profile.browser.contexts[0]
        # A protocol turn delivers new-target events from the independent CLI connection.
        inspector = profile.browser.new_browser_cdp_session()
        inspector.send("Target.getTargets")
        inspector.detach()
        draft, = [p for p in context.pages if "instagram.com" in p.url]
        caption = draft.locator("[contenteditable]")
        original_pages = set(context.pages)
        original_url = draft.url
        assert caption.inner_text() == "peer draft"
        yield studio, profile

        assert draft.url == original_url and caption.inner_text() == "peer draft"
        caption.fill("peer still editing")
        assert caption.inner_text() == "peer still editing"
        caption.fill("peer draft")
        assert set(context.pages) == original_pages
        assert profile.starts == ["shared"] and not profile.stops and not instagram.submissions
        advanced = tmp_path / "advanced"
        advanced.write_text("1893456010")
        advanced.replace(clock)
        output = peer.communicate(timeout=18)[0]
        assert peer.returncode == 0, output
        assert instagram.submissions == [{"caption": "peer draft", "files": ["peer.png"]}]
        assert json.loads(result.read_text())["status"] == "published"
        assert profile.stops == ["shared"]


def start_video(profile, *, title="YouTube marker", desc=None):
    video = profile.root / "synthetic.mp4"
    video.write_bytes(b"offline fixture")
    args = ["--title", title]
    if desc is not None:
        args += ["--desc", desc]
    return profile.command(1, "youtube", "--file", str(video), *args,
                           action="upload-video", env={"HUMANIZE": "0"})


@pytest.mark.parametrize("studio_profile", ["success"], indirect=True)
def test_description_topics_are_reported_and_prefilled_keywords_survive(studio_profile):
    studio, profile = studio_profile
    description = "第一行 #咖啡，配上 #咖啡。\n链接 https://example.com/#frag"
    child = start_video(profile, title="#标题话题 独立标题", desc=description)
    output = child.communicate(timeout=40)[0]
    assert child.returncode == 0, output
    assert studio.records == [{
        "title": "#标题话题 独立标题",
        "description": description,
        "keywords": "page-keyword",
        "file": "synthetic.mp4",
    }]
    assert "YouTube 简介话题 1/2：#咖啡 保留文字（简介全文逐字回读一致）" in output
    assert "YouTube 简介话题 2/2：#咖啡 保留文字（简介全文逐字回读一致）" in output
    assert "#标题话题" not in output
    assert "#frag" not in output
    assert studio.submissions == [("#标题话题 独立标题", "synthetic.mp4")]


@pytest.mark.parametrize("studio_profile", ["description-limit"], indirect=True)
def test_studio_description_error_blocks_before_submit(studio_profile):
    studio, profile = studio_profile
    child = start_video(profile, desc="简介 #话题")
    output = child.communicate(timeout=40)[0]
    assert child.returncode == 1, output
    assert "硬限制" in output and "未点击发布" in output
    assert studio.submissions == [] and studio.records == []


@pytest.mark.parametrize(
    "studio_profile", ["desc-swallow", "desc-misplace", "desc-append"], indirect=True
)
def test_description_readback_mismatch_blocks_before_submit(studio_profile):
    studio, profile = studio_profile
    child = start_video(profile, desc="正文 #a 与 #b")
    output = child.communicate(timeout=40)[0]
    assert child.returncode == 1, output
    assert "简介读回不一致" in output
    assert "偏移" in output and "期望" in output and "实际" in output
    assert "未点击发布" in output
    assert studio.submissions == [] and studio.records == []


@pytest.mark.parametrize("studio_profile", ["post-login"], indirect=True)
def test_video_reports_post_submit_login_and_preserves_peer(studio_profile):
    studio, profile = studio_profile
    child = start_video(profile)
    output = child.communicate(timeout=32)[0]
    assert child.returncode == 10, output
    assert "publish_attempted=true" in output.splitlines()
    assert "AdsPower" in output
    assert "YouTube video upload submitted" not in output
    assert studio.submissions == [("YouTube marker", "synthetic.mp4")]


@pytest.mark.parametrize("studio_profile", ["page-lost"], indirect=True)
def test_lost_result_page_reports_unknown_without_submitting_again(studio_profile):
    studio, profile = studio_profile
    child = start_video(profile)
    assert studio.submitted.wait(20)
    profile.browser.new_browser_cdp_session().send("Target.getTargets")
    upload, = [page for page in profile.browser.contexts[0].pages if "youtube.com/upload" in page.url]
    upload.close()
    output = child.communicate(timeout=12)[0]
    assert child.returncode == 9, output
    assert "禁止自动重发" in output and "YouTube video upload submitted" not in output
    assert studio.submissions == [("YouTube marker", "synthetic.mp4")]


@pytest.mark.parametrize(("studio_profile", "code", "diagnostic", "submitted"), [
    ("success", 0, "YouTube video upload submitted", True),
    ("unconfirmed", 9, "禁止自动重发", True),
    ("pre-failure", 1, "ambiguous", False),
    ("pre-login", 10, "AdsPower", False),
], indirect=["studio_profile"])
def test_video_outcome_reflects_only_its_own_editor(studio_profile, code, diagnostic, submitted):
    studio, profile = studio_profile
    child = start_video(profile)
    output = child.communicate(timeout=32)[0]
    assert child.returncode == code, output
    assert diagnostic in output and "publish_attempted=true" not in output.splitlines()
    assert ("YouTube video upload submitted" in output) == (code == 0)
    assert studio.submissions == ([("YouTube marker", "synthetic.mp4")] if submitted else [])
    assert studio.requests.count(("studio.youtube.com", "/")) == 1
    assert studio.requests.count(("www.youtube.com", "/upload")) == int(studio.outcome != "pre-login")


@pytest.mark.parametrize(("studio_profile", "code", "diagnostic"), [
    ("success", 0, "valid"), ("pre-login", 10, "AdsPower"),
], indirect=["studio_profile"])
def test_login_probe_closes_its_own_page(studio_profile, code, diagnostic):
    studio, profile = studio_profile
    child = profile.command(1, "youtube")
    output = child.communicate(timeout=16)[0]
    assert child.returncode == code, output
    assert diagnostic in output
    assert ("valid" in output.splitlines()) == (code == 0)
    assert studio.requests.count(("studio.youtube.com", "/")) == 1
    assert studio.submissions == []
