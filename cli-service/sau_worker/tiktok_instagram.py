"""TikTok and Instagram publish options supported by the paired CLI."""
from pathlib import PurePosixPath
from urllib.parse import urlsplit


def media_args(task):
    media = task["media"]
    if task["action"] == "upload-note":
        return ["--images", *(item["url"] for item in media)]
    files = {item["role"]: item["url"] for item in media}
    args = ["--file=" + files["video"]]
    if "cover" in files:
        args.append("--thumbnail=" + files["cover"])
    return args


def text_option(options, key):
    value = options[key]
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} requires nonblank text")
    return value


def option_keys(options, allowed, booleans):
    if not isinstance(options, dict) or options.keys() - allowed:
        raise ValueError("Unsupported publish option for this action")
    if any(type(options[k]) is not bool for k in booleans if k in options):
        raise ValueError("Boolean publish option expected")


def publish_args(task):
    args = media_args(task)
    options = task["settings"]
    note = task["action"] == "upload-note"
    caption = task["caption"]
    if task["platform"] == "instagram":
        return args + instagram_options(task, options, note, caption)

    presence = {"noComments": "--no-comments", "brandedContent": "--branded-content", "yourBrand": "--your-brand"}
    if not note:
        presence["disableReuse"] = "--disable-reuse"
    allowed = set(presence) | {"privacy", "location", "aigc"}
    if note:
        allowed.add("title")
    option_keys(options, allowed, set(presence) | {"aigc"})
    if note:
        if len(task["media"]) > 35 or len(caption) > 4000:
            raise ValueError("TikTok photo posts support up to 35 images and 4000 body characters")
        if "title" in options:
            title = options["title"]
            if not isinstance(title, str) or len(title) > 90 or any(c in title for c in "\r\n\t"):
                raise ValueError("TikTok photo title must be a single line of up to 90 characters")
            args.append("--title=" + title)
        if caption:
            args.append("--note=" + caption)
    else:
        args.append("--title=" + caption)
    if "privacy" in options:
        privacy = options["privacy"]
        if privacy not in ("public", "friends", "followers", "only-me") or (privacy == "only-me" and options.get("brandedContent")):
            raise ValueError("Invalid TikTok privacy for selected branding")
        args.append("--privacy=" + privacy)
    if "location" in options:
        args.append("--location=" + text_option(options, "location"))
    if "aigc" in options:
        args.append("--aigc" if options["aigc"] else "--no-aigc")
    args.extend(flag for key, flag in presence.items() if options.get(key))
    return args
