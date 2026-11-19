"""Predownload contract as observed by a caller and its local media origin."""
import json
from pathlib import Path
from subprocess import CompletedProcess
from threading import Event

import pytest

from tests.remote_media_cli import media_cli, origin


@pytest.fixture
def sau(media_cli):
    def run(*args):
        process = media_cli("--wait", *args)
        stdout, stderr = process.communicate(timeout=20)
        return CompletedProcess(process.args, process.returncode, stdout, stderr)

    return run


def test_wait_returns_complete_files_in_input_order(sau, origin, tmp_path):
    base, assets, _ = origin
    assets.update({"/video.mp4": (200, b"video"), "/cover.jpg": (200, b"cover")})
    result = sau("--task-id", "post-42", "--urls", base + "/video.mp4", base + "/cover.jpg")
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert (report["task_id"], report["status"]) == ("post-42", "ready")
    paths = [Path(item["path"]) for item in report["items"]]
    assert [p.read_bytes() for p in paths] == [b"video", b"cover"]
    assert all(p.parent == tmp_path / "downloads" / "post-42" for p in paths)


def test_opaque_assets_receive_local_media_suffixes(sau, origin):
    base, assets, _ = origin
    samples = [
        (".bmp", b"BM" + b"\x00" * 24), (".gif", b"GIF89a"),
        (".avi", b"RIFF\x00\x00\x00\x04AVI "), (".flv", b"FLV\x01"),
        (".wmv", bytes.fromhex("3026b2758e66cf11a6d900aa0062ce6c")),
        (".webm", b"\x1a\x45\xdf\xa3\x87\x42\x82\x84webm"),
        (".mkv", b"\x1a\x45\xdf\xa3\x8b\x42\x82\x88matroska"),
        (".mov", b"\x00\x00\x00\x10ftypqt  " + b"\x00" * 4),
        (".m4v", b"\x00\x00\x00\x10ftypM4V " + b"\x00" * 4),
    ]
    urls = []
    for i, (_, body) in enumerate(samples):
        path = f"/asset?file={i}"
        urls.append(base + path)
        assets[path] = (200, body)
    result = sau("--task-id", "formats", "--urls", *urls)
    assert result.returncode == 0, result.stderr
    paths = [Path(item["path"]) for item in json.loads(result.stdout)["items"]]
    assert [(path.suffix, path.read_bytes()) for path in paths] == samples


def test_full_url_and_task_id_identify_reusable_copies(sau, origin):
    base, assets, requests = origin
    first, second = "/pic.jpg?sig=one", "/pic.jpg?sig=two"
    assets.update({first: (200, b"first"), second: (200, b"second")})
    urls = [base + first, base + second, base + first]
    result = sau("--task-id", "alpha", "--urls", *urls)
    assert result.returncode == 0, result.stderr
    paths = [Path(item["path"]) for item in json.loads(result.stdout)["items"]]
    assert [p.read_bytes() for p in paths] == [b"first", b"second", b"first"]
    assert paths[0] == paths[2] and paths[0] != paths[1]
    assert requests.count(first) == requests.count(second) == 1

    assets[first] = (200, b"new version")
    result = sau("--task-id", "alpha", "--urls", urls[0])
    assert result.returncode == 0, result.stderr
    cached = Path(json.loads(result.stdout)["items"][0]["path"])
    assert cached == paths[0] and cached.read_bytes() == b"first"
    assert requests.count(first) == 1

    result = sau("--task-id", "beta", "--urls", urls[0])
    assert result.returncode == 0, result.stderr
    separate = Path(json.loads(result.stdout)["items"][0]["path"])
    assert separate != cached and separate.read_bytes() == b"new version"
    assert requests.count(first) == 2


def test_failed_batch_reports_each_position_and_keeps_successes(sau, origin):
    base, assets, requests = origin
    assets.update({"/expired?sig=old": (403, b"expired"), "/good": (200, b"kept")})
    paths = ["/missing", "/good", "/expired?sig=old", "/missing"]
    result = sau("--task-id", "mixed", "--urls", *(base + p for p in paths))
    assert result.returncode == 1, result.stderr
    report = json.loads(result.stdout)
    assert (report["task_id"], report["status"]) == ("mixed", "failed")
    missing, good, expired, duplicate = report["items"]
    assert missing == duplicate == {"reason": "HTTP 404"}
    assert expired == {"reason": "HTTP 403"}
    assert Path(good["path"]).read_bytes() == b"kept"
    assert requests.count("/missing") == 1


@pytest.mark.parametrize("args", [
    ["--urls", "{base}/valid"],
    ["--task-id", "post"],
    ["--task-id", "../outside", "--urls", "{base}/valid"],
    ["--task-id", "post", "--urls", "{base}/valid", "file:///some/image.jpg"],
    ["--task-id", "post", "--urls", "{base}/valid", "https://host:bad/file"],
])
def test_invalid_batch_exits_before_any_request(sau, origin, args):
    base, _, requests = origin
    result = sau(*(arg.format(base=base) for arg in args))
    assert result.returncode == 2
    assert not result.stdout and result.stderr.strip()
    assert not requests


def test_truncated_download_is_never_reused_as_a_complete_file(sau, origin):
    base, assets, requests = origin

    def truncated(handler):
        handler.send_response(200)
        handler.send_header("Content-Length", str(256 * 1024))
        handler.end_headers()
        handler.wfile.write(b"x" * 128 * 1024)

    assets["/movie.mp4"] = truncated
    args = ("--task-id", "partial", "--urls", base + "/movie.mp4")
    failed = sau(*args)
    assert failed.returncode == 1
    failed_item, = json.loads(failed.stdout)["items"]
    assert failed_item["reason"] and "path" not in failed_item

    assets["/movie.mp4"] = (200, b"complete")
    completed = sau(*args)
    assert completed.returncode == 0, completed.stderr
    item, = json.loads(completed.stdout)["items"]
    assert Path(item["path"]).read_bytes() == b"complete"
    assert requests == ["/movie.mp4", "/movie.mp4"]


def test_follows_redirect_without_waiting_for_its_irrelevant_body(sau, origin):
    base, assets, _ = origin
    reached_media = Event()
    stalled_on_redirect = Event()

    def redirect(handler):
        handler.send_response(302)
        handler.send_header("Location", "/actual")
        handler.send_header("Content-Length", str(64 * 1024 * 1024))
        handler.end_headers()
        if not reached_media.wait(timeout=3):
            stalled_on_redirect.set()

    def media(handler):
        reached_media.set()
        handler.send_response(200)
        handler.send_header("Content-Length", "5")
        handler.end_headers()
        handler.wfile.write(b"media")

    assets.update({"/redirect": redirect, "/actual": media})
    result = sau("--task-id", "redirect", "--urls", base + "/redirect")
    assert result.returncode == 0, result.stdout + result.stderr
    item, = json.loads(result.stdout)["items"]
    assert Path(item["path"]).read_bytes() == b"media"
    assert not stalled_on_redirect.is_set()


def test_rejects_encoded_response_before_reading_compressed_media(sau, origin):
    base, assets, _ = origin

    def encoded(handler):
        handler.send_response(200)
        handler.send_header("Content-Encoding", "gzip")
        handler.end_headers()
        # Empty gzip stream. Decoding it would deliver a spurious zero-byte file.
        handler.wfile.write(bytes.fromhex("1f8b080000000000000303000000000000000000"))

    assets["/video"] = encoded
    result = sau("--task-id", "encoded", "--urls", base + "/video")
    assert result.returncode == 1
    item, = json.loads(result.stdout)["items"]
    assert "encoding" in item["reason"].lower() and "path" not in item
