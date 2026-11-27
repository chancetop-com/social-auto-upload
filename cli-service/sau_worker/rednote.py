"""Author options shared by the distinct Rednote and Xiaohongshu CLI actions."""
from datetime import date


LABELS = {"rednote": "Rednote", "xiaohongshu": "Xiaohongshu"}
CONTENT_TYPES = ("fiction", "ai", "marketing", "self-shot", "repost")


def publish_args(task):
    options = task["settings"]
    title = options.get("title")
    if not isinstance(title, str) or not title.strip() or any(key in title for key in "\r\n\t"):
        raise ValueError("Enter a single-line title")
    if options.keys() - {"title", "location", "original", "contentType", "repostSource", "shootLocation", "shootDate"}:
        raise ValueError("Unsupported author setting")
    media = task["media"]
    if task["action"] == "upload-note":
        args = ["--images", *(item["url"] for item in media)]
        body_flag = "--note="
    else:
        files = {item["role"]: item["url"] for item in media}
        args = ["--file=" + files["video"]]
        if "cover" in files:
            args.append("--thumbnail=" + files["cover"])
        body_flag = "--desc="
    args.append("--title=" + title)
    if task["caption"]:
        args.append(body_flag + task["caption"])

    content_type = options.get("contentType")
    if "contentType" in options:
        if content_type not in CONTENT_TYPES:
            raise ValueError("Select one content declaration")
        args.append("--content-type=" + content_type)
    if "original" in options:
        original = options["original"]
        if (type(original) is not bool or content_type == "repost" or
                (not original and content_type == "self-shot")):
            raise ValueError("Incompatible original declaration")
        args.append("--original" if original else "--no-original")

    for key, flag, declaration in (("location", "location", None),
                                  ("repostSource", "repost-source", "repost"),
                                  ("shootLocation", "shoot-location", "self-shot"),
                                  ("shootDate", "shoot-date", "self-shot")):
        if declaration and ((content_type == declaration) != (key in options)):
            raise ValueError("Incomplete or incompatible content declaration")
        if key not in options:
            continue
        value = options[key]
        if not isinstance(value, str) or not value.strip():
            raise ValueError("Enter a nonblank value for " + flag)
        if key == "shootDate" and date.fromisoformat(value).isoformat() != value:
            raise ValueError("Enter a shooting date in YYYY-MM-DD format")
        args.append(f"--{flag}={value}")
    return args


def confirmed(task, stdout):
    lines = stdout.splitlines()
    if not lines:
        return False
    label = LABELS[task["platform"]]
    if task["action"] == "upload-note":
        return lines[-1] == f'{label} note upload submitted: {len(task["media"])} images'
    prefix = label + " video upload submitted: "
    return lines[-1].startswith(prefix) and bool(lines[-1][len(prefix):].strip())
