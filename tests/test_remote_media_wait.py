"""Predownload contract as observed by a caller and its local media origin."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sysconfig
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Event, Thread

import pytest


PROJECT = Path(__file__).resolve().parents[1]


@pytest.fixture
def sau(tmp_path):
    shutil.copyfile(PROJECT / "conf.example.py", tmp_path / "conf.py")
    env = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join(map(str, (tmp_path, PROJECT))),
        "MLX_API_TOKEN": "",
        "ADSPOWER_API_KEY": "",
        "NO_PROXY": "127.0.0.1",
    }
    executable = shutil.which("sau", path=sysconfig.get_path("scripts"))
    assert executable, "Install the project to run the sau CLI tests"

    def run(*args):
        return subprocess.run(
            [executable, "media", "predownload", "--wait", *args],
            cwd=tmp_path, env=env, capture_output=True, text=True, timeout=20,
        )

    return run


@pytest.fixture
def origin():
    assets = {}
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append(self.path)
            asset = assets.get(self.path, (404, b""))
            if callable(asset):
                return asset(self)
            status, body = asset
            self.send_response(status)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield f"http://127.0.0.1:{server.server_port}", assets, requests
        finally:
            server.shutdown()
            thread.join()


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
