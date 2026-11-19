"""Resolve upload arguments together, before entering any platform session."""
import asyncio
from contextlib import asynccontextmanager, contextmanager, nullcontext
from copy import copy
import os
from pathlib import Path
import signal
import sqlite3
import sys
import threading
from uuid import uuid4

from sau_commands.arguments import existing_file_path
from utils.media_queue import clear_media, publish_access, submit, task_gate, wait_for_result
from utils.remote_media import validate_task_id, validate_url


def is_remote(value):
    return isinstance(value, str) and value.lower().startswith(("http://", "https://"))


def media_source(value: str) -> Path | str:
    return validate_url(value) if is_remote(value) else existing_file_path(value)


def add_task_id(parser):
    parser.add_argument("--task-id", type=validate_task_id, help="Reuse downloads for this task ID")


@contextmanager
def _finish_temporary_task_on_termination():
    # Give this CLI's temporary directory its normal asynchronous teardown
    # before delivering the original POSIX termination status to its caller.
    if (os.name == "nt" or threading.current_thread() is not threading.main_thread()
            or signal.getsignal(signal.SIGTERM) != signal.SIG_DFL):
        yield
        return
    loop = asyncio.get_running_loop()
    task = asyncio.current_task()
    terminating = False

    def terminate(signum, frame):
        nonlocal terminating
        if not terminating:
            terminating = True
            loop.call_soon_threadsafe(task.cancel)

    previous = signal.signal(signal.SIGTERM, terminate)
    try:
        yield
    finally:
        signal.signal(signal.SIGTERM, previous)
        if terminating:
            signal.raise_signal(signal.SIGTERM)


@asynccontextmanager
async def publish_media(args):
    images = getattr(args, "images", None) or []
    sources = [getattr(args, "file", None), getattr(args, "thumbnail", None), *images]
    urls = list(dict.fromkeys(value for value in sources if is_remote(value)))
    task_id = getattr(args, "task_id", None)
    if not task_id and not urls:
        yield args
        return
    temporary = task_id is None
    with _finish_temporary_task_on_termination() if temporary else nullcontext():
        async with _acquire(args, images, urls, task_id) as resolved:
            yield resolved


@asynccontextmanager
async def _acquire(args, images, urls, task_id):
    temporary = task_id is None
    while True:
        candidate = uuid4().hex if temporary else task_id
        published = False
        try:
            async with publish_access(candidate, new=temporary) as directory:
                if directory is None:
                    continue
                try:
                    resolved = await _resolve(args, images, urls, candidate)
                    # Only the platform knows which successful runs actually published.
                    resolved.post_published = False
                    yield resolved
                    published = resolved.post_published
                finally:
                    if temporary or published:
                        await _release(candidate, published)
        except Exception as error:
            if not published:
                raise
            # Neither filesystem removal nor release of the task lock changes the post.
            print(f"Post published. Could not release media task {candidate}: {error}", file=sys.stderr)
        return


async def _release(task_id, published):
    async def clear():
        try:
            async with task_gate(task_id):
                await clear_media(task_id)
        except Exception as error:
            if published:
                raise
            # Preserve the original platform outcome on temporary task teardown as well.
            print(f"Could not release media task {task_id}: {error}", file=sys.stderr)

    # Finish draining this generation even when a first SIGINT arrives during cleanup.
    cleanup = asyncio.create_task(clear())
    try:
        await asyncio.shield(cleanup)
    except asyncio.CancelledError:
        await cleanup
        if not published:
            raise


async def _resolve(args, images, urls, task_id):
    resolved = copy(args)
    if not urls:
        return resolved
    try:
        request = await submit(task_id, urls, background=False, priority=True)
        items = await wait_for_result(request, urls, fail_fast=True)
    except (OSError, sqlite3.Error) as exc:
        raise RuntimeError(f"Could not acquire media for {task_id}: {exc}\npublish_attempted=false") from exc
    paths = {url: Path(item["path"]) for url, item in zip(urls, items)}
    for field in ("file", "thumbnail"):
        source = getattr(args, field, None)
        if source in paths:
            setattr(resolved, field, paths[source])
    if images:
        resolved.images = [paths.get(source, source) for source in images]
    return resolved
