"""Durable media requests shared by CLI processes using the same download root."""
import asyncio
from contextlib import asynccontextmanager, closing, contextmanager, ExitStack
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
from utils.remote_media import (
    QUEUE_DIRECTORY, TASK_OWNER_FILE, download_item, download_root, item_path, owned_task_stat, remove_task_files,
    task_directory, validate_task_id,
)

POLL_SECONDS = 0.05
TEMPORARY_OWNER_FILE = ".sau-temporary-owner"


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


def _directory_key(info):
    """The same physical directory can have several spellings on some filesystems."""
    return f"{info.st_dev}:{info.st_ino}"


def _refresh_retained(root, task_id, key):
    directory = root / validate_task_id(task_id)
    try:
        info = owned_task_stat(directory)
    except OSError:
        return  # The path no longer identifies an owned task.
    try:
        if info is not None and _directory_key(info) == key:
            os.utime(directory, follow_symlinks=False)
    except FileNotFoundError:
        pass  # A clear can already have retired this request's directory.


def _finish_requests(db, root, where, parameters=()):
    # A withdrawn request must never refresh a new generation of the same ID.
    tasks = db.execute(f"""SELECT DISTINCT task_id, directory_key FROM requests
                           WHERE ({where}) AND reason IS NOT 'task_cleared'""", parameters).fetchall()
    for task_id, key in tasks:
        _refresh_retained(root, task_id, key)
    db.execute(f"DELETE FROM requests WHERE {where}", parameters)


def _initialize(db):
    # One row represents one caller's interest in one URL. Result delivery and
    # accepting a later request for the same transfer share a transaction.
    db.execute("""CREATE TABLE IF NOT EXISTS requests (
        request_id TEXT NOT NULL, task_id TEXT NOT NULL, directory_key TEXT NOT NULL,
        url TEXT NOT NULL, background INTEGER NOT NULL, accepted INTEGER NOT NULL DEFAULT 0,
        path TEXT, reason TEXT, PRIMARY KEY (request_id, url)
    )""")
    if "priority" not in {row[1] for row in db.execute("PRAGMA table_info(requests)")}:
        db.execute("ALTER TABLE requests ADD COLUMN priority INTEGER NOT NULL DEFAULT 0")
    db.execute("""CREATE INDEX IF NOT EXISTS media_pending ON requests (directory_key, url)
                  WHERE path IS NULL AND reason IS NULL""")
    db.execute("""CREATE TABLE IF NOT EXISTS writers (
        token TEXT PRIMARY KEY, directory_key TEXT NOT NULL, task_id TEXT NOT NULL,
        url TEXT NOT NULL, UNIQUE (directory_key, url)
    )""")
    _upgrade_writer_state(db)


def _upgrade_writer_state(db):
    if "reported" not in {row[1] for row in db.execute("PRAGMA table_info(writers)")}:
        db.execute("ALTER TABLE writers ADD COLUMN reported INTEGER NOT NULL DEFAULT 0")


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
            _finish_requests(db, download_root(), "request_id=?", (self.id,))
            if self.lease is not None:
                self.lease.close()
                (_queue_directory(download_root()) / (self.id + ".lease")).unlink()


def _start_queue_process(*arguments, stdin=subprocess.DEVNULL):
    options = (
        {"creationflags": subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP}
        if os.name == "nt" else {"start_new_session": True}
    )
    # The console script and `python -m` can have different import paths.
    # Preserve the caller's resolved paths, including its configuration.
    env = {**os.environ, "PYTHONPATH": os.pathsep.join(map(os.path.abspath, sys.path))}
    return subprocess.Popen(
        [sys.executable, "-m", "utils.media_queue", str(download_root()), *arguments],
        cwd=Path(sys.executable).parent, env=env, stdin=stdin,
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
    return _start_queue_process()


async def submit(task_id, urls, *, background, priority=False):
    """Persist the complete request and wait until a detached worker acknowledges it."""
    download_concurrency()
    request_id = uuid4().hex
    async with task_gate(task_id):
        with transaction() as db:
            _initialize(db)
            directory = task_directory(task_id)
            key = _directory_key(directory.stat())
            for url in dict.fromkeys(urls):
                target = item_path(directory, url)
                cached = str(target) if not target.is_symlink() and target.is_file() else None
                db.execute("""INSERT INTO requests(request_id, task_id, directory_key, url,
                                                   background, priority, path)
                              VALUES (?, ?, ?, ?, ?, ?, ?)""",
                           (request_id, task_id, key, url, background, priority, cached))
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


class TaskCleared(Exception):
    """The task was cleared before this request could collect its results."""


async def wait_for_result(request, urls, *, fail_fast=False):
    """Read this caller's results in input order and release its request on exit."""
    process = None
    try:
        while True:
            with closing(_connect("requests.sqlite")) as db:
                rows = db.execute(
                    "SELECT url, path, reason FROM requests WHERE request_id=?", (request.id,),
                ).fetchall()
            if any(reason == "task_cleared" for _, _, reason in rows):
                raise TaskCleared
            if fail_fast:
                for url, _, reason in rows:
                    if reason is not None:
                        raise OSError(f"{url}: {reason}")
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
            # Publish the result and record the end of file I/O atomically.
            # The last waiter can withdraw before this child process exits.
            _report(db, key, url, path, reason)
            db.execute("UPDATE writers SET reported=1 WHERE token=?", (token,))


def _abandoned_waiters(db, root, task_id=None):
    waiters = db.execute("""SELECT DISTINCT request_id FROM requests
                            WHERE NOT background AND (? IS NULL OR task_id=?)""", (task_id, task_id))
    for (owner,) in waiters.fetchall():
        if _release_abandoned(root, owner):
            yield owner


def _reap_writer(db, root, token, *, interrupted=True):
    # The old process can still be exiting after a scheduler crash. A
    # never-started child checks its token under this same transaction.
    if _release_abandoned(root, token):
        if interrupted:
            unfinished = db.execute("""SELECT task_id, directory_key FROM writers
                                       WHERE token=? AND NOT reported""", (token,)).fetchone()
            if unfinished:
                _refresh_retained(root, *unfinished)
        db.execute("DELETE FROM writers WHERE token=?", (token,))


def _collect_writers(db, root, children):
    writers = db.execute("SELECT token, directory_key, url, reported FROM writers").fetchall()
    for token, key, url, reported in writers:
        child = children.get(token)
        if child is not None:
            if child.poll() is None:
                if not reported and not child.stdin.closed and not _interests(db, key, url):
                    child.stdin.close()
                    child.kill()
                continue
            if not reported and child.returncode and not child.stdin.closed:
                _report(db, key, url, None, "Media transfer process failed")
            child.stdin.close()
            del children[token]
        _reap_writer(db, root, token, interrupted=child is None or child.returncode != 0)


async def revoke_task(task_id, url=None):
    """Under task_gate, invalidate existing interests and drain their writers."""
    with transaction() as db:
        _initialize(db)
        scope = (task_id, url, url)
        _finish_requests(db, download_root(), "task_id=? AND (? IS NULL OR url=?) AND background", scope)
        reason = "task_cleared" if url is None else "item_deleted"
        db.execute("""UPDATE requests SET accepted=1, path=NULL, reason=?
                      WHERE task_id=? AND (? IS NULL OR url=?) AND NOT background
                        AND reason IS NOT 'task_cleared'""", (reason, *scope))
    await wait_for_writers(task_id, url)


async def clear_media(task_id, url=None):
    """Under task_gate, revoke existing work and remove its owned files."""
    directory = download_root() / validate_task_id(task_id)
    original = owned_task_stat(directory)
    await revoke_task(task_id, url)
    remove_task_files(directory, original, url)


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
                for owner in _abandoned_waiters(db, root):
                    _finish_requests(db, root, "request_id=?", (owner,))
                db.execute("UPDATE requests SET accepted=1 WHERE accepted=0")
                _collect_writers(db, root, children)
                _finish_requests(db, root, "background AND (path IS NOT NULL OR reason IS NOT NULL)")
                running, = db.execute("SELECT COUNT(*) FROM writers").fetchone()
                slots = min(concurrency, sys.maxsize) - running
                if slots > 0:
                    pending = db.execute("""SELECT directory_key, url, task_id FROM requests r
                                            WHERE path IS NULL AND reason IS NULL AND NOT EXISTS
                                              (SELECT 1 FROM writers w WHERE w.directory_key=r.directory_key AND w.url=r.url)
                                            GROUP BY directory_key, url
                                            ORDER BY MAX(priority) DESC, MIN(rowid) LIMIT ?""",
                                         (slots,)).fetchall()
                    for key, url, task_id in pending:
                        token = uuid4().hex
                        db.execute("INSERT INTO writers(token, directory_key, task_id, url) VALUES (?, ?, ?, ?)",
                                   (token, key, task_id, url))
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


@contextmanager
def task_lease(task_id, purpose):
    """Try the ID's admission or publish lock; occupancy ends on process death."""
    root = download_root()
    # The filesystem resolves spelling aliases here exactly as it does in the
    # download root. Names that are distinct on this volume use separate locks.
    parent = Path("task-locks") / validate_task_id(task_id)
    filename = parent / (purpose + ".lease")
    with transaction(root):
        queue = _queue_directory(root)
        for directory in (queue / parent.parent, queue / parent):
            if directory.is_symlink():
                raise OSError("Media lock directory is a symbolic link")
            directory.mkdir(mode=0o700, exist_ok=True)
        lease = _try_lease(root, filename)
    try:
        yield lease is not None
    finally:
        if lease is not None:
            try:
                with transaction(root):
                    lease.close()
                    (queue / filename).unlink()
                    if not any((queue / parent).iterdir()):
                        (queue / parent).rmdir()
            finally:
                lease.close()  # Also release the OS lock if the queue became inaccessible.


@asynccontextmanager
async def task_gate(task_id, *, refuse_publish=False):
    """Serialize admissions and destructive operations on this ID only."""
    while True:
        with task_lease(task_id, "gate") as acquired:
            if refuse_publish:
                # A publisher may itself hold the gate while draining writers.
                # Check its lease on each attempt, even if the gate is busy.
                root = download_root()
                filename = Path("task-locks") / task_id / "publish.lease"
                with transaction(root):
                    if (_queue_directory(root) / filename).exists():
                        probe = _try_lease(root, filename)
                        if probe is None:
                            raise OSError("Task is in use by a publish command")
                        probe.close()
            if acquired:
                yield
                return
        await asyncio.sleep(POLL_SECONDS)


@asynccontextmanager
async def publish_access(task_id, *, new=False):
    """Hold occupancy from admission through upload/cleanup; death releases it."""
    with ExitStack() as stack:
        while True:
            async with task_gate(task_id):
                if stack.enter_context(task_lease(task_id, "publish")):
                    try:
                        with transaction() as db:
                            _initialize(db)
                            directory = task_directory(task_id, new=new)
                            if new:
                                stack.callback(_watch_temporary_owner(directory).stdin.close)
                    except FileExistsError:
                        if not new:
                            raise
                        directory = None
                    break
                stack.close()
            await asyncio.sleep(POLL_SECONDS)
        key = _directory_key(directory.stat()) if directory is not None else None
        # After admission the platform owns the outcome. Keep release errors
        # outside its exception path, including on cancellation or interruption.
        release = stack.pop_all()
        try:
            yield directory
        finally:
            try:
                with release:
                    if directory is not None:
                        _refresh_retained(directory.parent, task_id, key)
            except (OSError, sqlite3.Error) as exc:
                print(f"Could not release media task {task_id}: {exc}", file=sys.stderr)


def _watch_temporary_owner(directory):
    # A pipe detects even a hard kill after the download queue has drained.
    # The separate process holds no download slot or scheduler lease.
    token = uuid4().hex
    original = owned_task_stat(directory)
    try:
        with (directory / TEMPORARY_OWNER_FILE).open("x") as marker:
            marker.write(token)
        return _start_queue_process("--watch-owner", directory.name, token, stdin=subprocess.PIPE)
    except OSError:
        remove_task_files(directory, original, None)
        raise


async def _clear_orphaned_publish(root, task_id, token):
    directory = root / validate_task_id(task_id)
    marker = directory / TEMPORARY_OWNER_FILE
    if not marker.is_file():
        return  # Normal teardown already removed this generation.
    while True:
        async with task_gate(task_id):
            if owned_task_stat(directory) is None or marker.is_symlink() or not marker.is_file():
                return
            with marker.open("rb") as stream:
                if stream.read(33) != token.encode("ascii"):
                    return  # Another temporary generation owns this ID now.
            with task_lease(task_id, "publish") as available:
                if available:
                    await clear_media(task_id)
                    return
        await asyncio.sleep(POLL_SECONDS)


def worker_running():
    with _worker_lease(download_root()) as available:
        return not available


def cleanup_idle_tasks():
    root = download_root()
    if root.is_symlink() or not (root / QUEUE_DIRECTORY / "requests.sqlite").is_file():
        return
    cutoff = time.time_ns() - 7 * 24 * 60 * 60 * 10**9
    for directory in root.iterdir():
        try:
            validate_task_id(directory.name)
            if not (directory / TASK_OWNER_FILE).is_file():
                continue
            original = owned_task_stat(directory)
            if original is None or original.st_mtime_ns > cutoff:
                continue
            with task_lease(directory.name, "gate") as admitted:
                if not admitted:
                    continue
                with task_lease(directory.name, "publish") as available:
                    if not available:
                        continue
                    with transaction(root) as db:
                        _upgrade_writer_state(db)
                        # The worker can exit before a foreground waiter dies.
                        # Retire abandoned leases without extending retention.
                        for owner in _abandoned_waiters(db, root, directory.name):
                            db.execute("DELETE FROM requests WHERE request_id=?", (owner,))
                        with _worker_lease(root) as stopped:
                            if stopped:
                                writers = db.execute("SELECT token FROM writers WHERE task_id=?", (directory.name,))
                                for (token,) in writers.fetchall():
                                    _reap_writer(db, root, token, interrupted=False)
                                db.execute("""DELETE FROM requests WHERE task_id=? AND background
                                              AND (path IS NOT NULL OR reason IS NOT NULL)""", (directory.name,))
                        active = db.execute("""SELECT 1 FROM requests WHERE task_id=?
                                               UNION ALL SELECT 1 FROM writers WHERE task_id=? AND NOT reported LIMIT 1""",
                                            (directory.name, directory.name)).fetchone()
                    if not active and directory.lstat().st_mtime_ns <= cutoff:
                        remove_task_files(directory, original, None)
        except (ValueError, OSError, sqlite3.Error):
            continue


def worker(root):
    with _worker_lease(root) as acquired:
        if acquired:
            _drain(root, download_concurrency())


if __name__ == "__main__":
    if sys.argv[2:3] == ["--watch-owner"]:
        sys.stdin.buffer.read(1)
        asyncio.run(_clear_orphaned_publish(Path(sys.argv[1]), sys.argv[3], sys.argv[4]))
    elif len(sys.argv) == 3:
        _transfer(Path(sys.argv[1]), sys.argv[2])
    else:
        worker(Path(sys.argv[1]))
