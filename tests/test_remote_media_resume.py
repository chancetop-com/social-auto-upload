"""Exercise download recovery across independent sau processes."""
import hashlib
import json
from pathlib import Path

import pytest

from tests.remote_media_cli import media_cli, origin
from tests.test_remote_media_wait import sau


PREFIX = bytes(range(256)) * 1024
MOVIE = PREFIX + b"last frame"
TAG = '"movie-v1"'


def reply(handler, status, body, **headers):
    handler.send_response(status)
    for name, value in headers.items():
        handler.send_header(name, value)
    handler.end_headers()
    handler.wfile.write(body)


def interrupted(handler):
    reply(handler, 200, PREFIX, ETag=TAG, **{"Content-Length": str(len(MOVIE))})


def partial(handler, body, start, end, total, tag=TAG):
    headers = {"Content-Range": f"bytes {start}-{end}/{total}"}
    if tag is not None:
        headers["ETag"] = tag
    reply(handler, 206, body, **headers)


def download(sau, url):
    return sau("--task-id", "movie", "--urls", url)


def ready_file(result):
    assert result.returncode == 0, result.stderr + result.stdout
    report = json.loads(result.stdout)
    assert report["status"] == "ready"
    item, = report["items"]
    return Path(item["path"])


def failure(result):
    assert result.returncode == 1, result.stderr + result.stdout
    report = json.loads(result.stdout)
    assert report["status"] == "failed"
    item, = report["items"]
    assert "path" not in item
    return item["reason"]


def test_next_process_resumes_persisted_bytes_of_the_same_version(sau, origin):
    base, assets, _ = origin
    url = base + "/clip.mp4"
    assets["/clip.mp4"] = interrupted
    assert failure(download(sau, url))

    received = []

    def resume(handler):
        received.append((handler.headers.get("Range"), handler.headers.get("If-Range"),
                         handler.headers.get("Accept-Encoding")))
        partial(handler, MOVIE[len(PREFIX):], len(PREFIX), len(MOVIE) - 1, len(MOVIE))

    assets["/clip.mp4"] = resume
    result = download(sau, url)
    assert received == [(f"bytes={len(PREFIX)}-", TAG, "identity")]
    assert hashlib.sha256(ready_file(result).read_bytes()).digest() == hashlib.sha256(MOVIE).digest()


def test_fetches_successive_subranges_until_the_whole_movie_is_ready(sau, origin):
    base, assets, _ = origin
    url = base + "/clip.mp4"
    assets["/clip.mp4"] = interrupted
    assert failure(download(sau, url))
    ranges = []

    def piece(handler):
        ranges.append(handler.headers.get("Range"))
        start = int(ranges[-1].removeprefix("bytes=").removesuffix("-"))
        end = min(start + 3, len(MOVIE) - 1)
        partial(handler, MOVIE[start:end + 1], start, end, len(MOVIE))

    assets["/clip.mp4"] = piece
    assert ready_file(download(sau, url)).read_bytes() == MOVIE
    assert ranges == [f"bytes={len(PREFIX) + offset}-" for offset in (0, 4, 8)]


@pytest.mark.parametrize("offset,extra,tag", [
    (1, 0, TAG), (0, 1, TAG), (0, 0, '"movie-v2"'), (0, 0, None), (0, 0, 'W/"movie-v1"'),
])
def test_inconsistent_range_is_replaced_by_a_fresh_copy(sau, origin, offset, extra, tag):
    base, assets, _ = origin
    url = base + "/clip.mp4"
    assets["/clip.mp4"] = interrupted
    assert failure(download(sau, url))
    ranges = []

    def conflicting(handler):
        ranges.append(handler.headers.get("Range"))
        if ranges[-1]:
            partial(handler, b"spoof", len(PREFIX) + offset, len(MOVIE) - 1, len(MOVIE) + extra, tag)
        else:
            reply(handler, 200, b"fresh")

    assets["/clip.mp4"] = conflicting
    assert ready_file(download(sau, url)).read_bytes() == b"fresh"
    assert ranges == [f"bytes={len(PREFIX)}-", None]


@pytest.mark.parametrize("length,tag,complete", [
    (len(PREFIX), TAG, True), (len(MOVIE), TAG, False), (len(PREFIX), None, False),
    (len(PREFIX), '"another-version"', False),
])
def test_416_requires_proof_that_the_local_version_is_complete(sau, origin, length, tag, complete):
    base, assets, _ = origin
    url = base + "/clip.mp4"

    def missing_chunk_terminator(handler):
        chunk = f"{len(PREFIX):x}\r\n".encode() + PREFIX + b"\r\n"
        reply(handler, 200, chunk, ETag=TAG, **{"Transfer-Encoding": "chunked"})

    assets["/clip.mp4"] = missing_chunk_terminator
    assert failure(download(sau, url))
    ranges = []

    def unsatisfiable(handler):
        ranges.append(handler.headers.get("Range"))
        if ranges[-1]:
            headers = {"Content-Range": f"bytes */{length}"}
            if tag is not None:
                headers["ETag"] = tag
            reply(handler, 416, b"", **headers)
        else:
            reply(handler, 200, b"new complete video")

    assets["/clip.mp4"] = unsatisfiable
    result = ready_file(download(sau, url)).read_bytes()
    if complete:
        assert result == PREFIX
        assert ranges == [f"bytes={len(PREFIX)}-"]
    else:
        assert result == b"new complete video"
        assert ranges == [f"bytes={len(PREFIX)}-", None]


@pytest.mark.parametrize("representation", ["partial-200", "transfer-coded"])
def test_unusable_full_representation_is_never_published(sau, origin, representation):
    base, assets, _ = origin

    def invalid(handler):
        if representation == "partial-200":
            reply(handler, 200, b"ab", **{"Content-Range": "bytes 0-1/10"})
        else:
            reply(handler, 200, b"2\r\nab\r\n0\r\n\r\n", **{"Transfer-Encoding": "gzip, chunked"})

    assets["/clip.mp4"] = invalid
    assert failure(download(sau, base + "/clip.mp4"))


@pytest.mark.parametrize("body,encoding", [(b"xxxx", None), (b"x" * 30, None), (b"xxxx", "gzip")])
def test_bad_range_body_preserves_only_previously_verified_bytes(sau, origin, body, encoding):
    base, assets, _ = origin
    url = base + "/clip.mp4"
    assets["/clip.mp4"] = interrupted
    assert failure(download(sau, url))
    headers = {"ETag": TAG, "Content-Range": f"bytes {len(PREFIX)}-{len(MOVIE) - 1}/{len(MOVIE)}"}
    if encoding:
        headers["Content-Encoding"] = encoding
    assets["/clip.mp4"] = lambda handler: reply(handler, 206, body, **headers)
    assert failure(download(sau, url))

    offsets = []

    def recovered(handler):
        offsets.append(handler.headers.get("Range"))
        partial(handler, MOVIE[len(PREFIX):], len(PREFIX), len(MOVIE) - 1, len(MOVIE))

    assets["/clip.mp4"] = recovered
    assert ready_file(download(sau, url)).read_bytes() == MOVIE
    assert offsets == [f"bytes={len(PREFIX)}-"]


@pytest.mark.parametrize("tag", [None, 'W/"previous"', "malformed", TAG])
def test_full_response_replaces_the_partial_representation_from_zero(sau, origin, tag):
    base, assets, _ = origin
    url = base + "/clip.mp4"
    headers = {"Content-Length": str(len(MOVIE))}
    if tag:
        headers["ETag"] = tag
    assets["/clip.mp4"] = lambda handler: reply(handler, 200, PREFIX, **headers)
    assert failure(download(sau, url))
    ranges = []

    def full(handler):
        ranges.append(handler.headers.get("Range"))
        reply(handler, 200, b"replacement", ETag='"new"')

    assets["/clip.mp4"] = full
    assert ready_file(download(sau, url)).read_bytes() == b"replacement"
    assert ranges == [f"bytes={len(PREFIX)}-" if tag == TAG else None]


def test_replacement_signed_url_starts_fresh_and_keeps_the_expired_urls_progress(sau, origin):
    base, assets, _ = origin
    old, new = "/clip.mp4?sig=old", "/clip.mp4?sig=new"
    assets[old] = interrupted
    assert failure(download(sau, base + old))
    assets[old] = lambda handler: reply(handler, 403, b"", **{"Content-Encoding": "gzip"})
    assert failure(download(sau, base + old)) == "HTTP 403"

    seen = []

    def renewed(handler):
        seen.append(handler.headers.get("Range"))
        reply(handler, 200, b"renewed", ETag=TAG)

    assets[new] = renewed
    assert ready_file(download(sau, base + new)).read_bytes() == b"renewed"

    def original(handler):
        seen.append(handler.headers.get("Range"))
        partial(handler, MOVIE[len(PREFIX):], len(PREFIX), len(MOVIE) - 1, len(MOVIE))

    assets[old] = original
    assert ready_file(download(sau, base + old)).read_bytes() == MOVIE
    assert seen == [None, f"bytes={len(PREFIX)}-"]


def test_redirect_to_a_different_resource_cannot_reuse_an_etag_from_the_old_target(sau, origin):
    base, assets, _ = origin
    url = base + "/clip.mp4"
    assets["/clip.mp4"] = lambda handler: reply(handler, 302, b"", Location="/first")
    assets["/first"] = interrupted
    assert failure(download(sau, url))

    def replacement(handler):
        if handler.headers.get("Range"):
            partial(handler, b"wrong tail", len(PREFIX), len(MOVIE) - 1, len(MOVIE))
        else:
            reply(handler, 200, b"new target", ETag=TAG)

    assets["/clip.mp4"] = lambda handler: reply(handler, 302, b"", Location="/another")
    assets["/another"] = replacement
    assert ready_file(download(sau, url)).read_bytes() == b"new target"
