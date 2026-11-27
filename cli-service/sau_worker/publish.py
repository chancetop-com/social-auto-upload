"""Map a Gateway-authorized TikTok occurrence to the paired CLI's public contract."""
from .media import media_task_id


PREPARED = "素材已上传，发布前检查已通过；已停止，未点击发布按钮。"


def video_args(task, target):
    if task["settings"]:
        raise ValueError("This release supports basic TikTok videos without author options")
    files = {item["role"]: item["url"] for item in task["media"]}
    if (len(files) != len(task["media"]) or set(files) not in ({"video"}, {"cover", "video"})
            or any(not url.startswith(("http://", "https://")) for url in files.values())):
        raise ValueError("TikTok video needs one video URL and an optional cover URL")
    task_id = media_task_id(task["workflowId"])
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
    before_timeout = proc.returncode == 1 and "尚未点击发布" in proc.stderr and "发布超时" in proc.stderr
    explicit_failure = proc.returncode == 1 and "publish_attempted=false" in proc.stderr.splitlines()
    if proc.returncode in (2, 10, 11) or explicit_failure or before_timeout:
        reason = "pre_submit_failure"
        if proc.returncode == 10:
            reason = "login_required"
        elif before_timeout:
            reason = "upload_timeout"
        return {**evidence, "outcome": "failed", "reason": reason}
    return {**evidence, "outcome": "unknown", "reason": "possible_submission"}
