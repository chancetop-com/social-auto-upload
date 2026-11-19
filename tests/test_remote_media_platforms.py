"""Remote media as delivered by the installed CLI to each platform uploader."""
from contextlib import ExitStack
import json
from pathlib import Path
import shutil
import sys

import pytest
from patchright.sync_api import sync_playwright

from tests.remote_media_cli import origin, sau_cli, set_publish_clock
from tests.test_shared_adspower_process import OfflineProfile, installations
from tests.test_shared_youtube_cli import Studio


PLATFORMS = ("xiaohongshu", "rednote", "youtube", "facebook", "facebook-page", "instagram")
WITH_COVER = {"xiaohongshu", "rednote", "youtube", "instagram"}


@pytest.fixture
def receiver(tmp_path):
    shutil.copyfile(Path(__file__).parent / "fixtures/remote_upload_recorder.py",
                    tmp_path / "sitecustomize.py")
    return tmp_path / "received.json"


def finish(child):
    stdout, stderr = child.communicate(timeout=20)
    assert child.returncode == 0, (stdout, stderr)
    return stdout


@pytest.mark.parametrize("platform", PLATFORMS)
def test_local_and_predownloaded_video_and_cover(tmp_path, origin, sau_cli, receiver, platform):
    base, assets, requests = origin
    video_path = tmp_path / "mine.mp4"
    video_path.write_bytes(b"local video")
    cover_path = tmp_path / "mine.jpg"
    cover_path.write_bytes(b"local cover")
    video = "/movie.mp4?key=signed"
    cover = "/cover.jpg?key=signed"
    assets.update({video: (200, b"downloaded video"), cover: (200, b"downloaded cover")})
    local_flags = ["--file", str(video_path)]
    remote_flags = ["--file", base + video]
    files = [video]
    local_bytes = [b"local video"]
    remote_bytes = [b"downloaded video"]
    if platform in WITH_COVER:
        files.append(cover)
        local_flags.extend(["--thumbnail", str(cover_path)])
        remote_flags.extend(["--thumbnail", base + cover])
        local_bytes.append(b"local cover")
        remote_bytes.append(b"downloaded cover")
    command = (platform, "upload-video", "--account", "local", "--title", "Video")
    finish(sau_cli(*command, *local_flags))
    assert [bytes.fromhex(item["bytes"]) for item in json.loads(receiver.read_text())] == local_bytes
    assert not (tmp_path / "downloads").exists()
    receiver.unlink()

    prepared = finish(sau_cli("media", "predownload", "--wait", "--task-id", "prepared",
                              "--urls", *(base + path for path in files)))
    prepared_paths = [item["path"] for item in json.loads(prepared)["items"]]
    assets[video] = (403, b"signature expired")
    assets[cover] = (403, b"signature expired")
    finish(sau_cli(*command, "--task-id", "prepared", *remote_flags))
    handoff = json.loads(receiver.read_text())
    assert [item["path"] for item in handoff] == prepared_paths
    assert [bytes.fromhex(item["bytes"]) for item in handoff] == remote_bytes
    assert requests == files
    assert not Path(prepared_paths[0]).parent.exists()


@pytest.mark.parametrize("platform", [name for name in PLATFORMS if name != "youtube"])
def test_temporary_note_preserves_image_order_and_repeated_positions(
        tmp_path, origin, sau_cli, receiver, platform):
    base, assets, requests = origin
    signed = "/first.png?sig=s1"
    assets[signed] = (200, b"remote image")
    local = tmp_path / "middle.jpg"
    local.write_bytes(b"local image")

    finish(sau_cli(platform, "upload-note", "--account", "local", "--title", "Images",
                   "--images", base + signed, str(local), base + signed))

    first, middle, last = json.loads(receiver.read_text())
    assert [bytes.fromhex(item["bytes"]) for item in (first, middle, last)] == [
        b"remote image", b"local image", b"remote image",
    ]
    assert first == last
    assert not Path(first["path"]).parent.exists()
    assert Path(middle["path"]) == local and local.read_bytes() == b"local image"
    assert requests == [signed]


@pytest.mark.parametrize(("platform", "action", "flags", "code", "diagnostic"), [
    ("facebook", "upload-note", ["--account", "local", "--images", "/movie.mp4"],
     1, "不支持的图片格式: .mp4"),
    ("instagram", "upload-note", ["--account", "local", "--images", "/one.jpg", "/one.jpg",
                                  "--alt-text", "One description"],
     2, "替代文字数量不符"),
    ("youtube", "upload-video", ["--file", "/movie.mp4"], 2, "本地模式需要 --account"),
])
def test_platforms_apply_existing_input_constraints_to_downloaded_files(
        origin, sau_cli, receiver, platform, action, flags, code, diagnostic):
    base, assets, requests = origin
    assets.update({"/movie.mp4": (200, b"movie"), "/one.jpg": (200, b"photo")})
    args = [base + flag if flag in assets else flag for flag in flags]
    child = sau_cli(platform, action, "--title", "Offline", *args)
    _, stderr = child.communicate(timeout=15)
    assert child.returncode == code, stderr
    assert diagnostic in stderr
    assert not receiver.exists()


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX isolated Chromium fixture")
def test_managed_youtube_publishes_video_and_cover_after_eighteen_minute_download(
        tmp_path, installations, origin, set_publish_clock):
    base, assets, requests = origin
    assets["/movie.mp4"] = (200, b"movie bytes")

    def late_cover(handler):
        set_publish_clock(1080)
        handler.send_response(200)
        handler.send_header("Content-Length", "11")
        handler.end_headers()
        handler.wfile.write(b"cover bytes")

    assets["/cover.jpg"] = late_cover

    class TimedStudio(Studio):
        def editor(self):
            # The real uploader entered Studio. Spend 899 of its 900 seconds.
            set_publish_clock(1979)
            return super().editor()

    studio = TimedStudio("success")
    with ExitStack() as stack:
        profile = OfflineProfile(tmp_path, stack, installations, stack.enter_context(sync_playwright()),
                                 sites={"studio.youtube.com": studio.site(), "www.youtube.com": studio.site()})
        child = profile.command(0, "youtube", "--title", "Offline movie", "--file", base + "/movie.mp4",
                                "--thumbnail", base + "/cover.jpg", action="upload-video",
                                env={"HUMANIZE": "0", "PYTHONPATH": str(tmp_path)})
        finish(child)
    assert studio.uploaded_files == [["movie bytes", "cover bytes"]]
    assert requests == ["/movie.mp4", "/cover.jpg"]
