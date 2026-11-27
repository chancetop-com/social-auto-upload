"""The desktop's argument vector, parsed and executed by the paired CLI against a local media origin."""
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from tests.remote_media_cli import origin


@pytest.mark.parametrize("platform", ["tiktok", "instagram"])
@pytest.mark.parametrize("action", ["upload-video", "upload-note"])
def test_desktop_arguments_reach_platform_upload_boundary(platform, action, origin, tmp_path, monkeypatch):
    import sau_cli
    from sau_commands import instagram, tiktok

    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "cli-service"))
    from sau_worker.platforms import publish_args

    base, assets, _ = origin
    assets.update({"/clip.mp4": (200, b"movie"), "/b.jpg": (200, b"second"), "/a.png": (200, b"first")})
    for name in ("ADSPOWER_API_KEY", "BITBROWSER_API_KEY", "MLX_API_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("SAU_HOME", str(tmp_path))
    from utils import remote_media
    monkeypatch.setattr(remote_media.conf, "BASE_DIR", tmp_path)
    note = action == "upload-note"
    fields = {"location": "Town", "noComments": True}
    if platform == "tiktok":
        fields.update(aigc=False, yourBrand=True, brandedContent=True, privacy="friends")
        fields.update({"title": "-photo"} if note else {"disableReuse": True})
        receiver = AsyncMock()
        monkeypatch.setattr(tiktok, "_upload_note" if note else "_upload_video", receiver)
    else:
        fields.update(title="-title", aiGenerated=False, collaborators=[" @Alice ", "bob"])
        if note:
            fields["altText"] = ["B one", "A", "B two"]
        receiver = AsyncMock(return_value={"status": "prepared"})
        monkeypatch.setattr(instagram, "upload_instagram_content", receiver)

    paths = [("image", "/b.jpg"), ("image", "/a.png"), ("image", "/b.jpg")] if note else [("video", "/clip.mp4"), ("cover", "/a.png")]
    caption = "-body\n#话题"
    task = {"workflowId": "paired/" + platform + "/" + action, "platform": platform, "action": action,
            "media": [{"id": path, "url": base + path, "role": role} for role, path in paths],
            "settings": fields, "caption": caption, "earliestPublishAt": None, "noPublish": True}
    command = publish_args(task, ["--account=fixture", "--local-browser=chrome"])
    assert sau_cli.main(command) == 0
    request = receiver.await_args.args[0]
    assert request.no_publish
    if note:
        assert [path.read_bytes() for path in request.image_files] == [b"second", b"first", b"second"]
    else:
        assert request.video_file.read_bytes() == b"movie"
        cover = request.thumbnail if platform == "instagram" else request.thumbnail_file
        assert cover.read_bytes() == b"first"
    if platform == "tiktok":
        assert request.title == ("-photo" if note else caption)
        if note:
            assert request.note == caption
        assert request.options.privacy == "friends" and request.options.aigc is False
        assert request.options.branded_content and request.options.your_brand
        assert request.options.allow_reuse is (None if note else False)
    else:
        assert (request.title, request.description) == ("-title", caption)
        assert request.options.collaborators == ("alice", "bob")
        assert request.options.ai_generated is False
        assert request.options.alt_texts == (("B one", "A", "B two") if note else None)
