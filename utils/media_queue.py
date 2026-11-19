"""Durable media requests shared by CLI processes using the same download root."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, contextmanager
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import time
from uuid import uuid4

from utils.errors import UsageError
from utils.remote_media import QUEUE_DIRECTORY, download_item, download_root, task_directory

POLL_SECONDS = 0.05


def download_concurrency():
    raw = os.environ.get("SAU_DOWNLOAD_CONCURRENCY", "1")
    try:
        count = int(raw)
        if not raw.isascii() or not raw.isdecimal() or count < 1:
            raise ValueError
    except ValueError:
        raise UsageError("SAU_DOWNLOAD_CONCURRENCY must be a positive integer") from None
    return count


def _queue_directory(root):
    directory = root / QUEUE_DIRECTORY
    if root.is_symlink() or directory.is_symlink():
        raise OSError("Media queue directory is a symbolic link")
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    return directory


def _connect(filename, *, root=None, timeout=5):
    path = _queue_directory(root or download_root()) / filename
    if path.is_symlink():
        raise OSError("Media queue file is a symbolic link")
    return sqlite3.connect(path, timeout=timeout)


@contextmanager
def transaction(root=None):
    with closing(_connect("requests.sqlite", root=root)) as db, db:
        db.execute("BEGIN IMMEDIATE")
        yield db


def directory_key(directory):
    """The same physical directory can have several spellings on some filesystems."""
    stat = directory.stat()
    return f"{stat.st_dev}:{stat.st_ino}"


def _initialize(db):
    # One row represents one caller's interest in one URL. Result delivery and
    # accepting a later request for the same transfer share a transaction.
    db.execute("""CREATE TABLE IF NOT EXISTS requests (
        request_id TEXT NOT NULL, task_id TEXT NOT NULL, directory_key TEXT NOT NULL,
        url TEXT NOT NULL, background INTEGER NOT NULL, accepted INTEGER NOT NULL DEFAULT 0,
        path TEXT, reason TEXT, PRIMARY KEY (request_id, url)
    )""")
    db.execute("""CREATE INDEX IF NOT EXISTS media_pending ON requests (directory_key, url)
                  WHERE path IS NULL AND reason IS NULL""")


def _start_worker():
    options = (
        {"creationflags": subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP}
        if os.name == "nt" else {"start_new_session": True}
    )
    # The console script and `python -m` can have different import paths.
    # Preserve the caller's resolved paths, including its configuration.
    env = {**os.environ, "PYTHONPATH": os.pathsep.join(map(os.path.abspath, sys.path))}
    return subprocess.Popen(
        [sys.executable, "-m", "utils.media_queue", str(download_root())],
        cwd=Path(sys.executable).parent, env=env, stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True, **options,
    )


async def submit(task_id, urls, *, background):
    """Persist the complete request and wait until a detached worker acknowledges it."""
    download_concurrency()
    request_id = uuid4().hex
    with transaction() as db:
        _initialize(db)
        directory = task_directory(task_id)
        key = directory_key(directory)
        db.executemany(
            """INSERT INTO requests(request_id, task_id, directory_key, url, background)
               VALUES (?, ?, ?, ?, ?)""",
            ((request_id, task_id, key, url, background) for url in dict.fromkeys(urls)),
        )

    process = None
    deadline = time.monotonic() + 10
    try:
        while True:
            with closing(_connect("requests.sqlite")) as db:
                if not db.execute(
                    "SELECT 1 FROM requests WHERE request_id=? AND accepted=0 LIMIT 1",
                    (request_id,),
                ).fetchone():
                    return request_id
            if time.monotonic() >= deadline:
                raise OSError("Media worker did not acknowledge the request")
            if process is None or process.poll() is not None:
                if process is not None and process.returncode:
                    raise OSError("Could not start media worker")
                if not worker_running():
                    process = _start_worker()
            await asyncio.sleep(POLL_SECONDS)
    except BaseException:
        with transaction() as db:
            db.execute("DELETE FROM requests WHERE request_id=?", (request_id,))
        raise


async def wait_for_result(request_id, urls):
    """Read this caller's results in input order and release its completed request."""
    while True:
        with closing(_connect("requests.sqlite")) as db:
            rows = db.execute(
                "SELECT url, path, reason FROM requests WHERE request_id=?", (request_id,),
            ).fetchall()
        if all(path is not None or reason is not None for _, path, reason in rows):
            results = {url: {"path": path} if path else {"reason": reason} for url, path, reason in rows}
            with transaction() as db:
                db.execute("DELETE FROM requests WHERE request_id=?", (request_id,))
            return [results[url] for url in urls]
        await asyncio.sleep(POLL_SECONDS)


def _drain(root, concurrency):
    active = {}
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        while True:
            with transaction(root) as db:
                db.execute("UPDATE requests SET accepted=1 WHERE accepted=0")
                for key, url in list(active):
                    future = active[key, url]
                    if not future.done():
                        continue
                    try:
                        path, reason = str(future.result()), None
                    except Exception as exc:
                        path, reason = None, str(exc)
                    db.execute("""UPDATE requests SET path=?, reason=? WHERE directory_key=? AND url=?
                                  AND path IS NULL AND reason IS NULL""", (path, reason, key, url))
                    del active[key, url]
                db.execute("DELETE FROM requests WHERE background AND (path IS NOT NULL OR reason IS NOT NULL)")
                slots = concurrency - len(active)
                if slots:
                    pending = db.execute("""SELECT directory_key, url, task_id FROM requests
                                            WHERE path IS NULL AND reason IS NULL
                                            GROUP BY directory_key, url ORDER BY MIN(rowid) LIMIT ?""",
                                         (min(concurrency, sys.maxsize),))
                    for key, url, task_id in pending:
                        if (key, url) in active:
                            continue
                        active[key, url] = pool.submit(download_item, root / task_id, url)
                        slots -= 1
                        if not slots:
                            break
                if not active:
                    return
            time.sleep(POLL_SECONDS)


@contextmanager
def _worker_lease(root):
    # SQLite's exclusive OS lock is released on process death on POSIX and
    # Windows. Keep it on a separate file so submissions never wait on HTTP I/O.
    with closing(_connect("worker.sqlite", root=root, timeout=0)) as lease:
        try:
            lease.execute("BEGIN EXCLUSIVE")
        except sqlite3.OperationalError as exc:
            if "locked" in str(exc).lower():
                yield False
                return
            raise
        yield True


def worker_running():
    with _worker_lease(download_root()) as available:
        return not available


def worker(root):
    with _worker_lease(root) as acquired:
        if acquired:
            _drain(root, download_concurrency())


if __name__ == "__main__":
    worker(Path(sys.argv[1]))
