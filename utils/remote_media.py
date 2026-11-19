"""Storage and HTTP transfers for a task's remote media."""
from contextlib import contextmanager
from dataclasses import asdict, dataclass
import hashlib
import json
import os
from pathlib import Path, PureWindowsPath
import re
from urllib.parse import urljoin, urlsplit

import requests

import conf


QUEUE_DIRECTORY = ".sau-queue"
TASK_OWNER_FILE = ".sau-task-id"


def download_root() -> Path:
    return Path(conf.BASE_DIR).resolve() / "downloads"


def validate_task_id(task_id: str) -> str:
    if (
        not task_id
        or task_id.casefold() == QUEUE_DIRECTORY
        or task_id.endswith((" ", "."))
        or re.search(r'[<>:"/\\|?*\x00-\x1f\x7f]', task_id)
        or PureWindowsPath(task_id).is_reserved()
        or len(task_id.encode("utf-8")) > 255
    ):
        raise ValueError("Expected a task ID that is a single directory name")
    return task_id


def validate_url(url: str) -> str:
    parts = urlsplit(url)
    if (
        parts.scheme not in ("http", "https")
        or not parts.hostname
        or any(c.isspace() or ord(c) < 32 for c in url)
    ):
        raise ValueError("Expected a direct HTTP(S) URL")
    try:
        requests.Request("GET", url).prepare()
        # urllib3 and urllib.parse reject different malformed authorities.
        if parts.port == 0:
            raise ValueError("Invalid URL port")
    except requests.RequestException as exc:
        raise ValueError("Invalid HTTP(S) URL") from exc
    return url


def validate_task_owner(directory: Path, task_id: str) -> bool:
    """Reject alternate spellings. Return whether the CLI created this directory."""
    marker = directory / TASK_OWNER_FILE
    if marker.is_symlink() or (marker.exists() and not marker.is_file()):
        raise OSError("Invalid media task owner file")
    if marker.is_file():
        with marker.open("rb") as stream:
            if stream.read(256) != task_id.encode("utf-8"):
                raise OSError("Task ID conflicts with an existing directory")
        return True
    # Older downloads had no owner marker. Preserve their contents without
    # converting an arbitrary existing directory into a CLI-managed one.
    if not any(child.name == task_id for child in directory.parent.iterdir()):
        raise OSError("Task ID conflicts with an existing directory")
    return False


def task_directory(task_id: str) -> Path:
    root = download_root()
    directory = root / validate_task_id(task_id)
    if root.is_symlink() or directory.is_symlink():
        raise OSError("Media directory is a symbolic link")
    try:
        directory.mkdir(parents=True)
    except FileExistsError:
        if not directory.is_dir():
            raise
        validate_task_owner(directory, task_id)
    else:
        with (directory / TASK_OWNER_FILE).open("xb") as marker:
            marker.write(task_id.encode("utf-8"))
    return directory


def item_path(directory: Path, url: str) -> Path:
    key = hashlib.sha256(url.encode("utf-8")).hexdigest()
    suffix = Path(urlsplit(url).path).suffix
    if not re.fullmatch(r"\.[A-Za-z0-9]{1,16}", suffix):
        suffix = ""
    return directory / (key + suffix)


@contextmanager
def open_response(url: str, headers: dict):
    # Session.send builds its next request by draining the entire redirect body,
    # even with allow_redirects=False. The adapter returns just the headers.
    with requests.Session() as session:
        for _ in range(session.max_redirects + 1):
            request = requests.Request("GET", url, headers=headers).prepare()
            settings = session.merge_environment_settings(request.url, {}, True, None, None)
            adapter = session.get_adapter(request.url)
            with adapter.send(request, timeout=(10, 30), **settings) as response:
                if not response.is_redirect:
                    yield response
                    return
                url = validate_url(urljoin(request.url, response.headers["Location"]))
    raise OSError("Too many HTTP redirects")


def checkpoint_paths(target: Path) -> tuple[Path, Path, Path]:
    return tuple(target.with_name(f".{target.name}.{suffix}")
                 for suffix in ("part", "resume", "resume.tmp"))


def strong_etag(value):
    return isinstance(value, str) and re.fullmatch(r'"[!#-~\x80-\xff]*"', value) is not None


@dataclass(frozen=True)
class Checkpoint:
    source: str
    etag: str
    total: int | None
    offset: int

    @classmethod
    def load(cls, metadata, partial):
        try:
            with metadata.open(encoding="utf-8") as stream:
                # A valid journal contains only a hash, two integers and one HTTP header.
                if os.fstat(stream.fileno()).st_size > 512 * 1024:
                    return None
                saved = cls(**json.load(stream))
            if not strong_etag(saved.etag) or type(saved.offset) is not int:
                return None
            if saved.total is not None and (type(saved.total) is not int or saved.total < saved.offset):
                return None
            if 0 < saved.offset <= partial.stat().st_size:
                return saved
        except (FileNotFoundError, ValueError, TypeError):
            pass
        return None

    def save(self, output, metadata, temporary):
        output.flush()
        os.fsync(output.fileno())
        temporary.unlink(missing_ok=True)
        with temporary.open("x", encoding="utf-8") as stream:
            json.dump(asdict(self), stream)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(metadata)


CHUNK_SIZE = 64 * 1024
CHECKPOINT_INTERVAL = 4 * 1024 * 1024


def read_full(response, partial, metadata, temporary, source):
    if "Content-Range" in response.headers:
        raise OSError("Unexpected Content-Range on full HTTP response")
    length = response.headers.get("Content-Length")
    if length is not None and not re.fullmatch(r"[0-9]+", length):
        raise OSError("Invalid HTTP Content-Length")
    total = int(length) if length is not None else None
    etag = response.headers.get("ETag")
    resumable = strong_etag(etag)
    # Invalidate the old version before replacing any of its bytes.
    metadata.unlink(missing_ok=True)
    partial.unlink(missing_ok=True)
    with partial.open("xb") as output:
        next_checkpoint = 1
        try:
            for chunk in response.iter_content(chunk_size=CHUNK_SIZE):
                output.write(chunk)
                if resumable and output.tell() >= next_checkpoint:
                    Checkpoint(source, etag, total, output.tell()).save(output, metadata, temporary)
                    next_checkpoint = output.tell() + CHECKPOINT_INTERVAL
        except requests.RequestException:
            if resumable and output.tell():
                Checkpoint(source, etag, total, output.tell()).save(output, metadata, temporary)
            raise
        if total is not None and output.tell() != total:
            raise OSError("Incomplete HTTP response")
        output.flush()
        os.fsync(output.fileno())


def read_range(response, partial, metadata, temporary, saved, source):
    if response.headers.get("ETag") != saved.etag or source != saved.source:
        return None
    match = re.fullmatch(r"bytes ([0-9]+)-([0-9]+)/([0-9]+)", response.headers.get("Content-Range", ""))
    if not match:
        return None
    start, end, total = map(int, match.groups())
    if start != saved.offset or not start <= end < total or saved.total not in (None, total):
        return None
    with partial.open("r+b") as output:
        # Ignore any uncommitted tail from an earlier interrupted range request.
        output.seek(start)
        output.truncate()
        for chunk in response.iter_content(chunk_size=CHUNK_SIZE):
            if output.tell() + len(chunk) > end + 1:
                raise OSError("Excess HTTP range data")
            output.write(chunk)
        if output.tell() != end + 1:
            raise OSError("Incomplete HTTP range")
        following = Checkpoint(source, saved.etag, total, end + 1)
        following.save(output, metadata, temporary)
        return following


def download_item(directory: Path, url: str) -> Path:
    target = item_path(directory, url)
    if target.is_symlink():
        raise OSError("Media file is a symbolic link")
    if target.is_file():
        return target
    partial, metadata, temporary = checkpoint_paths(target)
    if partial.is_symlink() or metadata.is_symlink():
        raise OSError("Media checkpoint is a symbolic link")
    saved = Checkpoint.load(metadata, partial)
    while True:
        headers = {"Accept-Encoding": "identity"}
        if saved:
            headers.update({"Range": f"bytes={saved.offset}-", "If-Range": saved.etag})
        with open_response(url, headers) as response:
            source = hashlib.sha256(response.url.encode("utf-8")).hexdigest()
            if response.status_code == 416 and saved:
                if (source == saved.source and response.headers.get("ETag") == saved.etag
                        and response.headers.get("Content-Range") == f"bytes */{saved.offset}"
                        and saved.total in (None, saved.offset)):
                    # A previous unvalidated 206 may have left a speculative tail.
                    with partial.open("r+b") as output:
                        output.truncate(saved.offset)
                    break
                saved = None
                continue
            if response.status_code != 200 and not (response.status_code == 206 and saved):
                raise OSError(f"HTTP {response.status_code}")
            if response.headers.get("Content-Encoding", "identity").lower() != "identity":
                raise OSError("Unsupported Content-Encoding for byte-identical media")
            transfer = response.headers.get("Transfer-Encoding", "").lower()
            if transfer and (transfer != "chunked" or "Content-Length" in response.headers):
                raise OSError("Unsupported HTTP transfer encoding or ambiguous length")
            if response.status_code == 200:
                read_full(response, partial, metadata, temporary, source)
                break
            saved = read_range(response, partial, metadata, temporary, saved, source)
            if saved and saved.offset == saved.total:
                break
    partial.replace(target)
    metadata.unlink(missing_ok=True)
    return target
