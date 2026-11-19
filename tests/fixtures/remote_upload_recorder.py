"""Offline upload receivers installed as sitecustomize by CLI contract tests."""
import json
from pathlib import Path

from sau_commands import facebook, facebook_page, instagram, rednote, xiaohongshu, youtube


def receive(paths):
    files = [Path(path) for path in paths if path is not None]
    Path("received.json").write_text(json.dumps([
        {"path": str(path), "bytes": path.read_bytes().hex()} for path in files
    ]))
    return {"status": "published"}


async def video(self):
    return receive([self.file_path, self.thumbnail_path])


async def note(self):
    return receive(self.image_paths)


async def facebook_post(self):
    return receive(self.files)


async def instagram_post(self):
    return receive([self.video_file, self.thumbnail, *self.image_files])


async def page_post(self):
    return receive([self.video_file, *self.image_files])


xiaohongshu.XiaoHongShuVideo.main = video
xiaohongshu.XiaoHongShuNote.main = note
rednote.RednoteVideo.main = video
rednote.RednoteNote.main = note
youtube.YouTubeVideo.main = video
facebook.FacebookPost.main = facebook_post
instagram.InstagramUploader.upload = instagram_post
facebook_page.MetaBusinessUploader.upload = page_post
