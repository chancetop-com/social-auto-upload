"""TikTok and Instagram publish options supported by the paired CLI."""
import json
import re
from pathlib import PurePosixPath
from urllib.parse import urlsplit


from .media import media_args


def validate_formats(task):
    media = task["media"]
    instagram = task["platform"] == "instagram"
    formats = ({"video": {"mp4", "mov"}, "cover": {"jpg", "jpeg", "png"},
                "image": {"jpg", "jpeg", "png", "avif", "heic", "heif"}} if instagram
               else {"image": {"jpg", "jpeg", "png", "webp"}})
    for item in media:
        allowed = formats.get(item["role"])
        suffix = PurePosixPath(urlsplit(item["url"]).path).suffix.lower().lstrip(".")
        if suffix and allowed and suffix not in allowed:
            raise ValueError("Media format is unsupported by the selected action")


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
    validate_formats(task)
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


def instagram_options(task, options, note, caption):
    fields = {"title", "noComments", "aiGenerated", "location", "collaborators"}
    if note:
        fields.add("altText")
    option_keys(options, fields, {"noComments", "aiGenerated"})
    title = text_option(options, "title")
    if len("\n\n".join(filter(None, (title.strip(), caption.strip())))) > 2200:
        raise ValueError("Instagram caption exceeds 2200 characters")
    args = ["--title=" + title]
    if caption:
        args.append(("--note=" if note else "--desc=") + caption)
    if "location" in options:
        args.append("--location=" + text_option(options, "location"))
    if options.get("noComments"):
        args.append("--no-comments")
    if "aiGenerated" in options:
        args.append("--ai-generated" if options["aiGenerated"] else "--no-ai-generated")
    if "collaborators" in options:
        names = options["collaborators"]
        if not isinstance(names, list) or not 1 <= len(names) <= 5 or not all(isinstance(name, str) for name in names):
            raise ValueError("Supply one to five collaborator usernames")
        normalized = [name.strip().removeprefix("@").lower() for name in names]
        if "" in normalized or len(set(normalized)) != len(names):
            raise ValueError("Collaborators must be nonempty and distinct")
        for raw, name in zip(names, normalized):
            # The CLI removes exactly one @. Preserve double prefixes for its own normalization.
            args.append("--collaborator=" + (raw.strip().lower() if name.startswith("@") else name))
    if "altText" in options:
        texts = options["altText"]
        if not isinstance(texts, list) or len(texts) != len(task["media"]):
            raise ValueError("Provide one alt text for each image")
        for text in texts:
            if not isinstance(text, str) or not 1 <= len(text.strip()) <= 1000:
                raise ValueError("Each alt text must have 1 to 1000 characters")
            args.append("--alt-text=" + text.strip())
    return args


def instagram_success(task, stdout, no_publish):
    # instagram_command returns only frames authenticated for this invocation, without raw logs.
    try:
        event = json.loads(stdout)
    except ValueError:
        return {}
    if not isinstance(event, dict):
        return {}
    if no_publish:
        return {"outcome": "prepared"} if event.get("status") == "prepared" else {}
    if event.get("status") != "published":
        return {}
    post_id = event.get("post_id")
    kind = "reel" if task["action"] == "upload-video" else "p"
    if not isinstance(post_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", post_id):
        return {}
    url = f"https://www.instagram.com/{kind}/{post_id}/"
    if url != event.get("post_url"):
        return {}
    return {"outcome": "published", "releaseId": post_id, "url": url}
