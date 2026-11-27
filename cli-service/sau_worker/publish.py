"""Map a Gateway-authorized TikTok occurrence to the paired CLI's public contract."""
from hashlib import sha256


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
    lines = proc.stdout.splitlines()
    outcome = "unknown"
    if proc.returncode == 0:
        if no_publish and PREPARED in lines:
            outcome = "prepared"
        elif not no_publish and any(line.startswith("TikTok video upload submitted: ") for line in lines):
            outcome = "published"
    elif (proc.returncode in (2, 11) or
          (proc.returncode == 10 and "publish_attempted=true" not in proc.stderr.splitlines())):
        outcome = "failed"
    return {"outcome": outcome, "cliInvoked": True, "exitCode": proc.returncode}
