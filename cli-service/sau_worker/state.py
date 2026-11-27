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
def lock(path, *, existing=False):
    # Both primitives release automatically on process death. Leave the inode in place.
    with path.open("r+b" if existing else "a+b") as stream:
        if os.name == "nt":
            import msvcrt
            if stream.seek(0, os.SEEK_END) == 0:
                stream.write(b"\0")
                stream.flush()
            stream.seek(0)
            try:
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                acquired = True
            except OSError:
                acquired = False
        else:
            import fcntl
            try:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
            except BlockingIOError:
                acquired = False
        yield acquired


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
