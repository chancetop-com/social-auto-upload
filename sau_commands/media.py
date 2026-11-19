"""Download media for a scheduled post."""
import json
import sqlite3
import sys

from utils.media_queue import TaskCleared, submit, wait_for_result
from utils.remote_media import validate_task_id, validate_url


def register(platform_parsers):
    media = platform_parsers.add_parser("media", help="Manage downloaded media")
    actions = media.add_subparsers(dest="action", required=True)
    predownload = actions.add_parser("predownload", help="Fetch media from direct HTTP(S) URLs")
    predownload.add_argument("--task-id", type=validate_task_id, required=True)
    predownload.add_argument("--urls", nargs="+", type=validate_url, required=True)
    predownload.add_argument("--wait", action="store_true")


async def run(args):
    try:
        request_id = await submit(args.task_id, args.urls, background=not args.wait)
        if not args.wait:
            print(json.dumps({"task_id": args.task_id, "status": "accepted"}))
            return 0
        items = await wait_for_result(request_id, args.urls)
    except TaskCleared:
        print(json.dumps({"task_id": args.task_id, "status": "task_cleared", "items": []}))
        return 1
    except (OSError, sqlite3.Error) as exc:
        print(str(exc), file=sys.stderr)
        print(json.dumps({"task_id": args.task_id, "status": "failed", "reason": "queue_unavailable", "items": []}))
        return 1
    failed = any("reason" in item for item in items)
    print(json.dumps({"task_id": args.task_id, "status": "failed" if failed else "ready", "items": items}))
    return 1 if failed else 0
