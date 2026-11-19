"""Storage and HTTP transfers for a task's remote media."""
from contextlib import contextmanager
import hashlib
from pathlib import Path, PureWindowsPath
import re
from tempfile import NamedTemporaryFile
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
def open_response(url: str):
    # Session.send builds its next request by draining the entire redirect body,
    # even with allow_redirects=False. The adapter returns just the headers.
    with requests.Session() as session:
        for _ in range(session.max_redirects + 1):
            request = requests.Request("GET", url, headers={"Accept-Encoding": "identity"}).prepare()
            settings = session.merge_environment_settings(request.url, {}, True, None, None)
            adapter = session.get_adapter(request.url)
            with adapter.send(request, timeout=(10, 30), **settings) as response:
                if not response.is_redirect:
                    yield response
                    return
                url = validate_url(urljoin(request.url, response.headers["Location"]))
    raise OSError("Too many HTTP redirects")


def download_item(directory: Path, url: str) -> Path:
    target = item_path(directory, url)
    if target.is_symlink():
        raise OSError("Media file is a symbolic link")
    if target.is_file():
        return target
    with open_response(url) as response:
        if response.status_code != 200:
            raise OSError(f"HTTP {response.status_code}")
        if response.headers.get("Content-Encoding", "identity").lower() != "identity":
            raise OSError("Unsupported Content-Encoding for byte-identical media")
        output = NamedTemporaryFile(dir=directory, prefix=".", suffix=".part", delete=False)
        partial = Path(output.name)
        try:
            with output:
                for chunk in response.iter_content(chunk_size=64 * 1024):
                    output.write(chunk)
                expected = response.headers.get("Content-Length")
                if expected is not None and output.tell() != int(expected):
                    raise OSError("Incomplete HTTP response")
            partial.replace(target)
        finally:
            partial.unlink(missing_ok=True)
    return target
