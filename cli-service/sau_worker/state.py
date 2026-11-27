"""Private, process-shared desktop state primitives."""
from contextlib import contextmanager
import json
import os
import time
from pathlib import Path
from tempfile import NamedTemporaryFile


def atomic_write(path, value, *, executable=False):
    with NamedTemporaryFile(dir=path.parent, delete=False) as file:
        temporary = Path(file.name)
        try:
            file.write(value.encode("utf-8"))
            file.flush()
            os.fsync(file.fileno())
        except BaseException:
            file.close()
            temporary.unlink(missing_ok=True)
            raise
    try:
        temporary.chmod(0o700 if executable else 0o600)
        deadline = time.monotonic() + 2
        while True:
            try:
                temporary.replace(path)
                break
            except PermissionError:
                if os.name != "nt" or time.monotonic() >= deadline:
                    raise
                # Windows readers may briefly prevent replacing an open snapshot.
                time.sleep(.02)
    finally:
        temporary.unlink(missing_ok=True)


@contextmanager
def lock(path, *, existing=False, lifetime=False):
    # A non-inheritable raw descriptor can be owned by the OS until this PID
    # actually exits, including while CPython joins non-daemon cleanup threads.
    flags = os.O_RDWR if existing else os.O_RDWR | os.O_CREAT
    fd = os.open(path, flags, 0o600)
    acquired = False
    try:
        if os.name == "nt":
            import msvcrt
            if os.fstat(fd).st_size == 0:
                os.write(fd, b"\0")
            os.lseek(fd, 0, os.SEEK_SET)
            try:
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                acquired = True
            except OSError:
                pass
        else:
            import fcntl
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
            except BlockingIOError:
                pass
        yield acquired
    finally:
        if not lifetime or not acquired:
            os.close(fd)


def read(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}


def write(path, value):
    atomic_write(path, json.dumps(value))


def held(path):
    try:
        with lock(path, existing=True) as acquired:
            return not acquired
    except FileNotFoundError:
        return False
