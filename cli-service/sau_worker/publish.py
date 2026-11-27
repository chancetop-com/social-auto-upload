"""Map a Gateway-authorized TikTok occurrence to the paired CLI's public contract."""
from hashlib import sha256
import re


PREPARED = "素材已上传，发布前检查已通过；已停止，未点击发布按钮。"


def video_args(task, target):
    if task["settings"]:
        raise ValueError("This release supports basic TikTok videos without author options")
    files = {item["role"]: item["url"] for item in task["media"]}
    if (len(files) != len(task["media"]) or set(files) not in ({"video"}, {"cover", "video"})
            or any(not url.startswith(("http://", "https://")) for url in files.values())):
        raise ValueError("TikTok video needs one video URL and an optional cover URL")
    task_id = sha256(task["workflowId"].encode("utf-8")).hexdigest()
    args = ["tiktok", "upload-video", "--file=" + files["video"], "--title=" + task["caption"]]
    if "cover" in files:
        args.append("--thumbnail=" + files["cover"])
    args.extend([*target, "--task-id=" + task_id])
    if task["earliestPublishAt"]:
        args.append("--not-before=" + task["earliestPublishAt"])
    if task["noPublish"]:
        args.append("--no-publish")
    return args


def receipt(proc, *, no_publish):
    evidence = {"cliInvoked": True, "exitCode": proc.returncode}
    attempted = "publish_attempted=true" in proc.stderr.splitlines()
    if proc.returncode == 0:
        if no_publish and PREPARED in proc.stdout.splitlines():
            return {**evidence, "outcome": "prepared"}
        elif not no_publish and any(line.startswith("TikTok video upload submitted: ") for line in proc.stdout.splitlines()):
            return {**evidence, "outcome": "published"}
    if attempted:
        return {**evidence, "outcome": "unknown", "reason": "possible_submission", "publishAttempted": True}
    diagnostics = proc.stderr.splitlines()
    before_timeout = proc.returncode == 1 and diagnostics and re.fullmatch(
        r"(?:TikTok|Instagram|Rednote|小红书) ?发布超时（[0-9]+ 分钟）：尚未点击发布，未发布任何内容。",
        diagnostics[-1],
    )
    explicit_failure = proc.returncode == 1 and diagnostics[-1:] == ["publish_attempted=false"]
    if proc.returncode in (2, 10, 11) or explicit_failure or before_timeout:
        reason = "pre_submit_failure"
        if proc.returncode == 10:
            reason = "login_required"
        elif before_timeout:
            reason = "upload_timeout"
        return {**evidence, "outcome": "failed", "reason": reason}
    return {**evidence, "outcome": "unknown", "reason": "possible_submission"}
