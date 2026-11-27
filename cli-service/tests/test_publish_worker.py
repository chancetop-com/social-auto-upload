"""Exercise the desktop's outbound wire protocol and a real, isolated child process."""
from dataclasses import replace
import json
import sys

import httpx
import pytest

from sau_worker.worker import Settings, Worker


@pytest.fixture
def child(tmp_path):
    script = tmp_path / "paired fixture CLI.py"
    script.write_text("""
import json, os, sys
from pathlib import Path
if sys.argv[1:] == ["--version"]:
    print("sau 0.1.0")
    sys.exit(0)
root = Path(__file__).parent
with (root / "calls").open("a", encoding="utf-8") as output:
    print(json.dumps({"argv": sys.argv[1:], "credentials": sorted(k for k in os.environ
          if k in ("BITBROWSER_API_KEY", "ADSPOWER_API_KEY", "MLX_API_TOKEN", "SAU_DESKTOP_TOKEN"))}), file=output)
result = json.loads((root / "controlled-result").read_text(encoding="utf-8"))
print(result["stdout"])
print(result["stderr"], file=sys.stderr)
sys.exit(result["code"])
""", encoding="utf-8")
    return script


async def desktop(script, *, prepared=False, provider="local-chrome", code=0,
                  output="TikTok video upload submitted: video.mp4", error="", start_status=200,
                  options=None, lost_start=False, aliases="operator-selected", selection=None):
    root = script.parent
    (root / "controlled-result").write_text(json.dumps({"code": code, "stdout": output, "stderr": error}))
    workflow = "scheduled/shop|first"
    task = {"workflowId": workflow, "postId": "post", "organizationId": "org", "bindingId": "binding",
            "channelId": "channel", "caption": "before edit", "settings": {}, "contractVersion": 1,
            "release": "0.1.0", "platform": "tiktok", "action": "upload-video",
            "provider": provider, "profileId": "operator-selected", "requiredCapability": "tiktok.upload-video",
            "media": [{"id": "v", "url": "https://media.example/old.mp4", "role": "video"}],
            "earliestPublishAt": None, "noPublish": prepared}
    latest = {**task, "caption": "-first line\n#café & second", "settings": options or {},
              "earliestPublishAt": None if prepared else "2026-11-27T15:30:00Z",
              "media": [{"id": "c", "role": "cover", "url": "https://media.example/current.jpg"},
                        {"id": "v2", "role": "video", "url": "https://media.example/current.mp4"}]}
    if selection:
        task.update(selection)
        latest.update(selection)
    starts, reports, receipts = [], [], []

    def gateway(request):
        body = json.loads(request.content)
        if request.url.host == "127.0.0.1":
            assert request.url.path == "/browser/list"
            return httpx.Response(200, json={"success": True, "data": {
                "list": [{"id": "operator-selected", "name": "test"}]}})
        assert request.headers["Authorization"] == "Bearer fixture"
        path = request.url.path
        if path == "/session":
            reports.append(body)
            return httpx.Response(200, json={})
        if path == "/publish-task/claim":
            return httpx.Response(200, json={"task": {"workflowId": workflow, "task": task}})
        if path == "/publish-task/start":
            starts.append(body)
            if lost_start:
                raise httpx.ReadError("connection interrupted")
            return httpx.Response(start_status, json={"task": latest})
        assert path == "/publish-task/result"
        receipts.append(body)
        return httpx.Response(200, json={})

    config = Settings.from_env({"SAU_DESKTOP_TOKEN": "fixture", "SAU_GATEWAY_URL": "https://gateway.test",
                                "BITBROWSER_API_KEY": "fixture-local",
                                "SAU_DEV_CHROME_ALIASES": aliases})
    config = replace(config, cli=(sys.executable, str(script)))
    async with httpx.AsyncClient(transport=httpx.MockTransport(gateway)) as client:
        worker = Worker(config, client)
        await worker.report()
        record = await worker.claim(0)
        try:
            await worker.finish(record)
        except httpx.HTTPError:
            if start_status == 200 and not lost_start:
                raise
    calls = root / "calls"
    return reports, starts, receipts, [json.loads(line) for line in calls.read_text().splitlines()] if calls.exists() else []


@pytest.mark.asyncio
async def test_desktop_uses_one_fresh_authorization_and_complete_argv(child, monkeypatch):
    for variable in ("MLX_API_TOKEN", "SAU_DESKTOP_TOKEN", "ADSPOWER_API_KEY", "BITBROWSER_API_KEY"):
        monkeypatch.setenv(variable, "fixture-must-stay-out-of-child")
    reports, starts, receipts, calls = await desktop(child)
    assert {"platform": "tiktok", "action": "upload-video"} in reports[0]["capabilities"]
    assert {"provider": "local-chrome", "available": True, "profiles": [
        {"profileId": "operator-selected", "name": "operator-selected"}]} in reports[0]["providers"]
    identity = {"workflowId": "scheduled/shop|first", "sessionId": reports[0]["sessionId"]}
    assert starts == [identity]
    assert receipts == [{**identity, "receipt": {"outcome": "published", "cliInvoked": True, "exitCode": 0}}]
    assert len(calls) == 1 and calls[0]["credentials"] == []
    argv = calls[0]["argv"]
    assert argv[:2] == ["tiktok", "upload-video"]
    assert "--title=-first line\n#café & second" in argv
    assert "--account=operator-selected" in argv and "--local-browser=chrome" in argv
    assert "--file=https://media.example/current.mp4" in argv
    assert "--thumbnail=https://media.example/current.jpg" in argv
    assert "--not-before=2026-11-27T15:30:00Z" in argv and "--schedule" not in argv
    assert any(arg.startswith("--task-id=") and len(arg.removeprefix("--task-id=")) == 64 for arg in argv)


@pytest.mark.parametrize(("code", "output", "error", "outcome"), [
    (0, "素材已上传，发布前检查已通过；已停止，未点击发布按钮。", "", "prepared"),
    (0, "valid", "", "unknown"),
    (9, "", "uncertain", "unknown"),
    (10, "", "publish_attempted=true", "unknown"),
    (10, "", "login required", "failed"),
    (2, "", "usage", "failed"),
    (130, "", "interrupted", "unknown"),
])
@pytest.mark.asyncio
async def test_immediate_preparation_and_actual_child_evidence(child, code, output, error, outcome, monkeypatch):
    monkeypatch.setenv("PYTHONIOENCODING", "ascii")
    _, _, receipts, calls = await desktop(child, prepared=True, provider="bitbrowser", code=code,
                                         output=output, error=error)
    assert receipts[0]["receipt"].items() >= {"outcome": outcome, "cliInvoked": True, "exitCode": code}.items()
    assert len(calls) == 1
    assert calls[0]["credentials"] == ["BITBROWSER_API_KEY"]
    argv = calls[0]["argv"]
    assert "--profile-id=operator-selected" in argv
    assert "--no-publish" in argv and not any(a.startswith(("--not-before", "--account", "--local-browser")) for a in argv)


@pytest.mark.parametrize(("status", "lost"), [(403, False), (409, False), (503, False), (200, True)])
@pytest.mark.asyncio
async def test_no_cli_or_result_on_refused_or_lost_start(child, status, lost):
    _, starts, receipts, calls = await desktop(child, start_status=status, lost_start=lost)
    assert len(starts) == 1
    assert receipts == [] and calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("changes", [{"options": {"unsupported": True}}, {"aliases": ""}, {"aliases": "another"}])
async def test_worker_without_explicit_dev_alias_or_option_support_never_falls_back(child, changes):
    _, _, receipts, calls = await desktop(child, **changes)
    assert calls == []
    assert receipts[0]["receipt"] == {"outcome": "failed", "cliInvoked": False, "exitCode": None}

@pytest.mark.asyncio
async def test_photo_capability_dispatch_and_fuzzy_lookup(child):
    media = [{"id": key, "role": "image", "url": f"https://media.test/{key}.png"} for key in ("b", "a", "b")]
    selection = {"platform": "tiktok", "action": "upload-note", "requiredCapability": "tiktok.upload-note",
                 "caption": "line one\n#话题", "settings": {"title": "-title", "privacy": "friends", "aigc": False,
                 "brandedContent": True, "yourBrand": True, "location": "City", "noComments": True}, "media": media}
    reports, _, receipts, calls = await desktop(child, selection=selection, output="photo post id: 123")
    assert {"platform": "tiktok", "action": "upload-note"} in reports[0]["capabilities"]
    args = calls[0]["argv"]
    assert args[:6] == ["tiktok", "upload-note", "--images", "https://media.test/b.png",
                        "https://media.test/a.png", "https://media.test/b.png"]
    assert set(["--title=-title", "--note=line one\n#话题", "--privacy=friends", "--no-aigc", "--location=City",
                "--branded-content", "--your-brand", "--no-comments"]).issubset(args)
    assert receipts[-1]["receipt"]["outcome"] == "unknown"

@pytest.mark.asyncio
@pytest.mark.parametrize("platform,label", [("rednote", "Rednote"), ("xiaohongshu", "Xiaohongshu")])
@pytest.mark.parametrize("action", ["upload-video", "upload-note"])
async def test_regional_channels_dispatch_their_own_cli_and_accept_idless_confirmation(child, platform, label, action):
    selection = {"platform": platform, "action": action, "requiredCapability": platform + "." + action,
                 "settings": {"title": "-title", "contentType": "self-shot", "shootLocation": "Garden",
                              "shootDate": "2024-02-29", "original": True, "location": "Town"}}
    if action == "upload-note":
        selection["media"] = [{"id": key, "role": "image", "url": f"https://media.test/{key}.jpg"}
                              for key in ("b", "a", "b")]
        expected = ["--images", "https://media.test/b.jpg", "https://media.test/a.jpg", "https://media.test/b.jpg"]
        body_flag, summary = "--note=", "note upload submitted: 3 images"
    else:
        expected = ["--file=https://media.example/current.mp4", "--thumbnail=https://media.example/current.jpg"]
        body_flag, summary = "--desc=", "video upload submitted: fixture.mp4"
    _, _, receipts, calls = await desktop(child, selection=selection, output=label + " " + summary)
    assert len(calls) == 1
    argv = calls[0]["argv"]
    assert argv[:2] == [platform, action]
    index = argv.index(expected[0])
    assert argv[index:index + len(expected)] == expected
    assert {"--title=-title", body_flag + "-first line\n#café & second", "--location=Town", "--content-type=self-shot",
            "--original", "--shoot-location=Garden", "--shoot-date=2024-02-29"}.issubset(argv)
    assert receipts[0]["receipt"] == {"outcome": "published", "exitCode": 0, "cliInvoked": True}


@pytest.mark.asyncio
@pytest.mark.parametrize(("code", "output", "error", "expected"), [
    (0, "Xiaohongshu video upload submitted: clip.mp4", "", "unknown"),
    (0, "Rednote note upload submitted: 2 images", "", "unknown"),
    (0, "素材已上传，发布前检查已通过；已停止，未点击发布按钮。", "", "unknown"),
    (10, "", "login required", "failed"),
    (10, "", "publish_attempted=true", "unknown"),
    (9, "", "submission uncertain", "unknown"),
])
async def test_regional_video_accepts_only_its_own_formal_confirmation(child, code, output, error, expected):
    selected = {"platform": "rednote", "action": "upload-video", "requiredCapability": "rednote.upload-video",
                "settings": {"title": "Regional"}}
    _, _, receipts, calls = await desktop(child, selection=selected, code=code, output=output, error=error)
    assert len(calls) == 1
    receipt = receipts[0]["receipt"]
    assert (receipt["outcome"], receipt["cliInvoked"], receipt["exitCode"]) == (expected, True, code)
    if code:
        assert receipt["reason"] == ("login_required" if expected == "failed" else "possible_submission")


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid", [
    {"contentType": "repost", "original": False, "repostSource": "Agency"},
    {"contentType": "self-shot", "shootLocation": "Studio", "shootDate": "2026-02-31"},
    {"contentType": ["fiction", "ai"]}, {"location": "  "}, {"shootLocation": "Studio"}, {"unsupported": True},
])
async def test_incompatible_regional_options_fail_before_cli_invocation(child, invalid):
    selected = {"platform": "xiaohongshu", "action": "upload-video", "requiredCapability": "xiaohongshu.upload-video",
                "settings": {"title": "Regional", **invalid}}
    _, _, receipts, calls = await desktop(child, selection=selected)
    assert not calls
    assert receipts[0]["receipt"] == {"outcome": "failed", "cliInvoked": False, "exitCode": None}


@pytest.mark.parametrize(("code", "stderr", "outcome", "reason"), [
    (1, "TikTok发布超时（15 分钟）：尚未点击发布，结束。", "failed", "upload_timeout"),
    (1, "Private media URL", "unknown", "possible_submission"),
    (1, "Private media URL\npublish_attempted=false", "failed", "pre_submit_failure"),
    (10, "private account label", "failed", "login_required"),
    (9, "private diagnostic", "unknown", "possible_submission"),
    (10, "private diagnostic\npublish_attempted=true", "unknown", "possible_submission"),
    (-9, "", "unknown", "possible_submission"),
])
@pytest.mark.asyncio
async def test_merchant_safe_receipt_on_failure(child, code, stderr, outcome, reason):
    _, _, reports, calls = await desktop(child, code=code, output="", error=stderr)
    receipt = reports[0]["receipt"]
    assert (receipt["outcome"], receipt["reason"]) == (outcome, reason)
    assert "private" not in json.dumps(receipt).lower()
    assert len(calls) == 1
