"""Download media for a scheduled post."""
import json
import sqlite3
import sys

from utils.media_queue import TaskCleared, cleanup_idle_tasks, clear_media, submit, task_gate, wait_for_result
from utils.remote_media import validate_task_id, validate_url


def register(platform_parsers):
    media = platform_parsers.add_parser("media", help="Manage downloaded media")
    actions = media.add_subparsers(dest="action", required=True)
    predownload = actions.add_parser("predownload", help="Fetch media from direct HTTP(S) URLs")
    predownload.add_argument("--task-id", type=validate_task_id, required=True)
    predownload.add_argument("--urls", nargs="+", type=validate_url, required=True)
    predownload.add_argument("--wait", action="store_true")
    actions.add_parser("cleanup", help="Remove managed media tasks idle for seven days")
    delete = actions.add_parser("delete", help="Remove downloaded media and cancel queued transfers",
                                usage="%(prog)s --task-id ID [--url URL]")
    # Delete reports a missing ID as a one-line operational failure (exit 1).
    delete.add_argument("--task-id", nargs="?", metavar="ID", help="Required task ID")
    delete.add_argument("--url", help="Remove only this full HTTP(S) URL")


async def run(args):
    if args.action == "cleanup":
        cleanup_idle_tasks()
        return 0
    if args.action == "delete":
        try:
            task_id = validate_task_id(args.task_id)
            url = validate_url(args.url) if args.url is not None else None
            async with task_gate(task_id, refuse_publish=True):
                await clear_media(task_id, url)
        except (OSError, sqlite3.Error, ValueError) as exc:
            print(" ".join(str(exc).splitlines()), file=sys.stderr)
            return 1
        return 0
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
