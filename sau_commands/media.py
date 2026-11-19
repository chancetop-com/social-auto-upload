"""Download media for a scheduled post."""
import json

from utils.remote_media import download_item, task_directory, validate_task_id, validate_url


def register(platform_parsers):
    media = platform_parsers.add_parser("media", help="Manage downloaded media")
    actions = media.add_subparsers(dest="action", required=True)
    predownload = actions.add_parser("predownload", help="Fetch media from direct HTTP(S) URLs")
    predownload.add_argument("--task-id", type=validate_task_id, required=True)
    predownload.add_argument("--urls", nargs="+", type=validate_url, required=True)
    predownload.add_argument("--wait", action="store_true", required=True)


async def run(args):
    directory = task_directory(args.task_id)
    results = {}
    for url in dict.fromkeys(args.urls):
        try:
            results[url] = {"path": str(download_item(directory, url))}
        except (OSError, ValueError) as exc:
            results[url] = {"reason": str(exc)}
    items = [results[url] for url in args.urls]
    failed = any("reason" in item for item in items)
    print(json.dumps({"task_id": args.task_id, "status": "failed" if failed else "ready", "items": items}))
    return 1 if failed else 0
