"""Durable media requests shared by CLI processes using the same download root."""
import asyncio
from contextlib import closing, contextmanager
from dataclasses import dataclass
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import time
from threading import Thread
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
    db.execute("""CREATE TABLE IF NOT EXISTS writers (
        token TEXT PRIMARY KEY, directory_key TEXT NOT NULL, task_id TEXT NOT NULL,
        url TEXT NOT NULL, UNIQUE (directory_key, url)
    )""")


def _try_lease(root, filename):
    """A live connection owns this lease until close or OS process termination."""
    lease = _connect(filename, root=root, timeout=0)
    try:
        lease.execute("BEGIN EXCLUSIVE")
    except sqlite3.OperationalError as exc:
        lease.close()
        if "locked" in str(exc).lower():
            return None
        raise
    return lease


def _release_abandoned(root, token):
    # Token locks are created, tested and retired under the queue transaction.
    filename = token + ".lease"
    lease = _try_lease(root, filename)
    if lease is None:
        return False
    lease.close()
    (_queue_directory(root) / filename).unlink()
    return True


@dataclass
class Request:
    id: str
    lease: sqlite3.Connection | None

    def withdraw(self):
        with transaction() as db:
            db.execute("DELETE FROM requests WHERE request_id=?", (self.id,))
            if self.lease is not None:
                self.lease.close()
                (_queue_directory(download_root()) / (self.id + ".lease")).unlink()


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


def _ensure_worker(launching):
    if worker_running():
        return None
    if launching is not None:
        status = launching.poll()
        if status is None:
            return launching
        if status > 0:
            raise OSError("Could not start media worker")
    return _start_worker()


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
        request = Request(request_id, None if background else _try_lease(download_root(), request_id + ".lease"))

    process = None
    deadline = time.monotonic() + 10
    try:
        while True:
            with closing(_connect("requests.sqlite")) as db:
                if not db.execute(
                    "SELECT 1 FROM requests WHERE request_id=? AND accepted=0 LIMIT 1",
                    (request_id,),
                ).fetchone():
                    return request
            if time.monotonic() >= deadline:
                raise OSError("Media worker did not acknowledge the request")
            process = _ensure_worker(process)
            await asyncio.sleep(POLL_SECONDS)
    except BaseException:
        request.withdraw()
        raise


async def wait_for_result(request, urls):
    """Read this caller's results in input order and release its request on exit."""
    process = None
    try:
        while True:
            with closing(_connect("requests.sqlite")) as db:
                rows = db.execute(
                    "SELECT url, path, reason FROM requests WHERE request_id=?", (request.id,),
                ).fetchall()
            if all(path is not None or reason is not None for _, path, reason in rows):
                results = {url: {"path": path} if path else {"reason": reason} for url, path, reason in rows}
                return [results[url] for url in urls]
            process = _ensure_worker(process)
            await asyncio.sleep(POLL_SECONDS)
    finally:
        request.withdraw()


def _interests(db, key, url):
    return db.execute("""SELECT 1 FROM requests WHERE directory_key=? AND url=?
                         AND path IS NULL AND reason IS NULL LIMIT 1""", (key, url)).fetchone()


def _report(db, key, url, path, reason):
    db.execute("""UPDATE requests SET path=?, reason=? WHERE directory_key=? AND url=?
                  AND path IS NULL AND reason IS NULL""", (path, reason, key, url))


def _transfer(root, token):
    # The scheduler owns the pipe's only write end. Even a blocked DNS lookup,
    # TLS handshake or HTTP body read stops when its scheduler dies.
    def watch_scheduler():
        os.read(sys.stdin.fileno(), 1)
        os._exit(1)

    Thread(target=watch_scheduler, daemon=True).start()
    with transaction(root) as db:
        job = db.execute("SELECT directory_key, task_id, url FROM writers WHERE token=?", (token,)).fetchone()
        if not job or not _interests(db, job[0], job[2]):
            return
        lease = _try_lease(root, token + ".lease")
        if lease is None:
            return
    key, task_id, url = job
    with closing(lease):
        try:
            path, reason = str(download_item(root / task_id, url)), None
        except Exception as exc:
            path, reason = None, str(exc)
        with transaction(root) as db:
            _report(db, key, url, path, reason)


def _withdraw_dead_waiters(db, root):
    waiters = db.execute("SELECT DISTINCT request_id FROM requests WHERE NOT background")
    for (owner,) in waiters.fetchall():
        if _release_abandoned(root, owner):
            db.execute("DELETE FROM requests WHERE request_id=?", (owner,))


def _reap_writer(db, root, token):
    # The old process can still be exiting after a scheduler crash. A
    # never-started child checks its token under this same transaction.
    if _release_abandoned(root, token):
        db.execute("DELETE FROM writers WHERE token=?", (token,))


def _collect_writers(db, root, children):
    for token, key, url in db.execute("SELECT token, directory_key, url FROM writers").fetchall():
        child = children.get(token)
        if child is not None:
            if child.poll() is None:
                if not child.stdin.closed and not _interests(db, key, url):
                    child.stdin.close()
                    child.kill()
                continue
            if child.returncode and not child.stdin.closed:
                _report(db, key, url, None, "Media transfer process failed")
            child.stdin.close()
            del children[token]
        _reap_writer(db, root, token)


async def wait_for_writers(task_id, url=None):
    """After withdrawing interest under the task guard, wait until writing has stopped."""
    root = download_root()
    while True:
        with transaction(root) as db:
            _initialize(db)
            rows = db.execute("""SELECT token FROM writers
                                 WHERE task_id=? AND (? IS NULL OR url=?)""",
                              (task_id, url, url)).fetchall()
            if not rows:
                return
            with _worker_lease(root) as abandoned:
                if abandoned:
                    # A dead scheduler cannot clear its own assignments. Its
                    # children stop at pipe EOF and release their writer locks.
                    for (token,) in rows:
                        _reap_writer(db, root, token)
        await asyncio.sleep(POLL_SECONDS)


def _drain(root, concurrency):
    children = {}
    try:
        while True:
            with transaction(root) as db:
                _withdraw_dead_waiters(db, root)
                db.execute("UPDATE requests SET accepted=1 WHERE accepted=0")
                _collect_writers(db, root, children)
                db.execute("DELETE FROM requests WHERE background AND (path IS NOT NULL OR reason IS NOT NULL)")
                running, = db.execute("SELECT COUNT(*) FROM writers").fetchone()
                slots = min(concurrency, sys.maxsize) - running
                if slots > 0:
                    pending = db.execute("""SELECT directory_key, url, task_id FROM requests r
                                            WHERE path IS NULL AND reason IS NULL AND NOT EXISTS
                                              (SELECT 1 FROM writers w WHERE w.directory_key=r.directory_key AND w.url=r.url)
                                            GROUP BY directory_key, url ORDER BY MIN(rowid) LIMIT ?""",
                                         (slots,)).fetchall()
                    for key, url, task_id in pending:
                        token = uuid4().hex
                        db.execute("INSERT INTO writers VALUES (?, ?, ?, ?)", (token, key, task_id, url))
                        children[token] = subprocess.Popen(
                            [sys.executable, "-m", "utils.media_queue", str(root), token],
                            stdin=subprocess.PIPE, close_fds=True,
                        )
                        running += 1
                if not running:
                    return
            time.sleep(POLL_SECONDS)
    finally:
        for child in children.values():
            child.stdin.close()
            child.wait()


@contextmanager
def _worker_lease(root):
    # This lock is independent of submission and per-transfer locks.
    lease = _try_lease(root, "worker.sqlite")
    try:
        yield lease is not None
    finally:
        if lease is not None:
            lease.close()


def worker_running():
    with _worker_lease(download_root()) as available:
        return not available


def worker(root):
    with _worker_lease(root) as acquired:
        if acquired:
            _drain(root, download_concurrency())


if __name__ == "__main__":
    if len(sys.argv) == 3:
        _transfer(Path(sys.argv[1]), sys.argv[2])
    else:
        worker(Path(sys.argv[1]))
