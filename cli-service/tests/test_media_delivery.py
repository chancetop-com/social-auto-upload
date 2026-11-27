"""Exercise the desktop, paired SAU process, detached media queue and cache with offline boundaries."""
import asyncio
from dataclasses import replace
from hashlib import sha256
import json
import os
from pathlib import Path
import time

import httpx
import pytest

from sau_worker.worker import Settings, Worker


ROOT = Path(__file__).resolve().parents[2]
CLI_PYTHON = os.environ.get("SAU_MEDIA_TEST_PYTHON")
pytestmark = pytest.mark.skipif(not CLI_PYTHON, reason="set SAU_MEDIA_TEST_PYTHON to a Python with the paired CLI dependencies")


async def until(predicate):
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        if predicate():
            return
        await asyncio.sleep(.04)
    raise AssertionError("paired CLI did not reach the expected stage")


@pytest.mark.asyncio
@pytest.mark.parametrize("reclaim", [False, True])
async def test_edited_manifest_and_receipt_survive_cleanup(tmp_path, monkeypatch, reclaim):
    root = tmp_path
    monkeypatch.setenv("SAU_HOME", str(root / "state"))
    monkeypatch.setenv("PYTHONPATH", os.pathsep.join(map(str, (root, ROOT / "cli"))))
    monkeypatch.setenv("SAU_DOWNLOAD_CONNECT_SECONDS", "2.5")
    monkeypatch.setenv("SAU_DOWNLOAD_IDLE_READ_SECONDS", "3.5")
    monkeypatch.setenv("SAU_DOWNLOAD_ENQUEUE_SECONDS", "45")
    # Exercise requests' transport timeout parameters and the actual CLI platform adapter
    # without opening any sockets, reading an OS browser profile or touching a platform.
    (root / "sitecustomize.py").write_text("""
from pathlib import Path
import io, json, sys, time
from urllib.parse import urlsplit
from requests import Response
from requests.adapters import HTTPAdapter
root = Path(__file__).parent
def transport(self, request, **options):
    url = urlsplit(request.url)
    assert url.hostname == "fixture.invalid"
    data = (root / Path(url.path).name).read_bytes()
    with (root / "fetches").open("a") as log:
        print(json.dumps([url.path, options["timeout"]]), file=log)
    response = Response()
    response.raw, response.url, response.status_code = io.BytesIO(data), request.url, 200
    response.headers["Content-Length"] = str(len(data))
    return response
HTTPAdapter.send = transport
if sys.argv[0].endswith("sau_cli.py"):
    from sau_commands import tiktok
    async def upload(request, target):
        assert target is None
        with (root / "upload").open("a") as log:
            print(json.dumps([request.video_file.read_text(), request.thumbnail_file.read_text()]), file=log)
        for _ in range(3000):
            if (root / "release").exists(): return
            time.sleep(.02)
        raise RuntimeError("fixture did not release upload")
    tiktok._upload_video = upload
""")
    (root / "movie.mp4").write_text("version one")
    (root / "cover.jpg").write_text("retained cover")
    workflow = "../series:27/occurrence"
    base = "https://fixture.invalid"
    media = [{"id": "one", "url": base + "/movie.mp4#one", "role": "video"},
             {"id": "cover", "url": base + "/cover.jpg#cover", "role": "cover"}]
    task = {"provider": "local-chrome", "profileId": "alias", "workflowId": workflow, "postId": "p",
            "channelId": "channel", "organizationId": "org", "bindingId": "binding", "release": "0.1.0",
            "contractVersion": 1, "requiredCapability": "tiktok.upload-video", "platform": "tiktok",
            "action": "upload-video", "noPublish": False, "settings": {}, "caption": "fixture", "media": media,
            "earliestPublishAt": "2025-11-27T10:00:00Z"}
    latest = {**task, "media": [{**media[0], "id": "two", "url": base + "/movie.mp4#two"}, media[1]]}
    receipts = []
    def gateway(request):
        if request.url.path == "/publish-task/start":
            return httpx.Response(200, json={"task": latest})
        if request.url.path == "/publish-task/result":
            receipts.append(json.loads(request.content)["receipt"])
        return httpx.Response(200, json={})

    settings = replace(Settings.from_env({"SAU_DESKTOP_TOKEN": "fixture", "SAU_DEV_CHROME_ALIASES": "alias"}),
                       cli=(CLI_PYTHON, str(ROOT / "cli/sau_cli.py")))
    path = root / "state/downloads" / sha256(workflow.encode()).hexdigest()
    old = time.time() - 8 * 86400
    async with httpx.AsyncClient(transport=httpx.MockTransport(gateway)) as client:
        worker = Worker(settings, client)
        await worker.report()
        assert worker.paired
        record = {"workflowId": workflow, "task": task}
        await worker.finish({**record, "operation": "prepare"})
        await until(lambda: len(list(path.glob("*.mp4"))) == len(list(path.glob("*.jpg"))) == 1)
        assert receipts == [] and not (root / "upload").exists()
        if reclaim:
            # A transfer may still own its writer after the completed file appears.
            # Simulate seven idle days after that process releases the cache.
            def reclaimed():
                os.utime(path, (old, old))
                assert worker.command(["media", "cleanup"]).returncode == 0
                return not path.exists()
            await until(reclaimed)
        (root / "movie.mp4").write_text("version two")
        job = asyncio.create_task(worker.finish(record))
        try:
            await until(lambda: (root / "upload").exists() or job.done())
            assert not job.done(), receipts
            assert json.loads((root / "upload").read_text()) == ["version two", "retained cover"]
            os.utime(path, (old, old))
            assert worker.command(["media", "cleanup"]).returncode == 0
            assert path.exists()  # Active publish owns its files.
        finally:
            (root / "release").touch()
            await job
        assert not path.exists()  # Success removed task files before the worker consumed stdout.
        assert receipts == [{"outcome": "published", "cliInvoked": True, "exitCode": 0}]
    fetches = [json.loads(line) for line in (root / "fetches").read_text().splitlines()]
    assert sum(path == "/movie.mp4" for path, _ in fetches) == 2
    assert sum(path == "/cover.jpg" for path, _ in fetches) == 1 + int(reclaim)
    assert all(timeout == [2.5, 3.5] for _, timeout in fetches)
