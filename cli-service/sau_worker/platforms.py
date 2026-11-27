"""Translate an authorized occurrence to one paired CLI invocation."""
from hashlib import sha256
from urllib.parse import urlsplit

from . import tiktok_instagram
from .publish import PREPARED


PUBLISH_PLATFORMS = ("rednote", "xiaohongshu", "tiktok", "instagram")
PUBLISH_ACTIONS = ("upload-video", "upload-note")
PUBLISH_CAPABILITIES = [{"platform": p, "action": a} for p in PUBLISH_PLATFORMS for a in PUBLISH_ACTIONS]


def publish_args(task, target):
    platform, action = task["platform"], task["action"]
    if platform not in PUBLISH_PLATFORMS or action not in PUBLISH_ACTIONS:
        raise ValueError("Unsupported publish capability")
    roles = []
    for item in task["media"]:
        url = urlsplit(item["url"])
        if url.scheme not in ("http", "https") or not url.hostname or url.username or url.password:
            raise ValueError("Select desktop-readable media URLs")
        roles.append(item["role"])
    if action == "upload-video":
        if sorted(roles) not in (["video"], ["cover", "video"]):
            raise ValueError("Select one video and an optional cover")
    elif not roles or set(roles) != {"image"}:
        raise ValueError("Select ordered images for an image post")
    if platform in ("rednote", "xiaohongshu"):
        from .rednote import publish_args as rednote_args
        fields = rednote_args(task)
    else:
        fields = tiktok_instagram.publish_args(task)
    task_id = sha256(task["workflowId"].encode("utf-8")).hexdigest()
    args = [platform, action, *fields, *target, "--task-id=" + task_id]
    if task["earliestPublishAt"]:
        args.append("--not-before=" + task["earliestPublishAt"])
    if task["noPublish"]:
        args.append("--no-publish")
    return args


def successful_receipt(task, stdout, no_publish):
    if task["platform"] == "instagram":
        return tiktok_instagram.instagram_success(task, stdout, no_publish)
    if no_publish:
        return {"outcome": "prepared"} if PREPARED in stdout.splitlines() else {}
    if task["platform"] in ("rednote", "xiaohongshu"):
        from .rednote import confirmed
        success = confirmed(task, stdout)
    else:
        label = "video" if task["action"] == "upload-video" else "note"
        success = any(line.startswith(f"TikTok {label} upload submitted: ") for line in stdout.splitlines())
    # The paired CLI confirms the submit. TikTok Studio's fuzzy list lookup cannot certify an ID.
    return {"outcome": "published"} if success else {}
