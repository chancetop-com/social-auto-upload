"""Resolve upload arguments together, before entering any platform session."""
from contextlib import asynccontextmanager
from pathlib import Path
import shutil
import sqlite3
from uuid import uuid4

from sau_commands.arguments import existing_file_path
from utils.media_queue import publish_access, submit, wait_for_result
from utils.remote_media import download_root, task_directory, validate_task_id, validate_url


def is_remote(value):
    return isinstance(value, str) and value.lower().startswith(("http://", "https://"))


def media_source(value: str) -> Path | str:
    return validate_url(value) if is_remote(value) else existing_file_path(value)


def add_task_id(parser):
    parser.add_argument("--task-id", type=validate_task_id, help="Reuse downloads for this task ID")


@asynccontextmanager
async def publish_media(args):
    images = getattr(args, "images", None) or []
    sources = [getattr(args, "file", None), getattr(args, "thumbnail", None), *images]
    urls = list(dict.fromkeys(value for value in sources if is_remote(value)))
    task_id = getattr(args, "task_id", None)
    if not task_id and not urls:
        yield
        return
    temporary = task_id is None
    while True:
        candidate = uuid4().hex if temporary else task_id
        async with publish_access(candidate):
            if temporary and (download_root() / candidate).exists():
                continue
            directory = task_directory(candidate)
            try:
                await _resolve(args, images, urls, candidate)
                yield
            finally:
                if temporary:
                    shutil.rmtree(directory)
            return


async def _resolve(args, images, urls, task_id):
    if not urls:
        return
    try:
        request = await submit(task_id, urls, background=False, priority=True)
        items = await wait_for_result(request, urls, fail_fast=True)
    except (OSError, sqlite3.Error) as exc:
        raise RuntimeError(f"Could not acquire media for {task_id}: {exc}\npublish_attempted=false") from exc
    paths = {url: Path(item["path"]) for url, item in zip(urls, items)}
    for field in ("file", "thumbnail"):
        source = getattr(args, field, None)
        if source in paths:
            setattr(args, field, paths[source])
    if images:
        args.images = [paths.get(source, source) for source in images]
