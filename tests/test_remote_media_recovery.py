"""Transfer ownership as observed by CLI callers, the media origin and the filesystem."""
import json
import os
from pathlib import Path
from random import Random
import signal
import subprocess
import time
from threading import Event

import pytest

from tests.remote_media_cli import media_cli, origin


PREFIX = Random(42).randbytes(8 * 1024 * 1024)
MOVIE = PREFIX + b"the end"
ETAG = '"movie-v1"'


def interrupted_movie(assets):
    sent = Event()
    disconnected = Event()
    ranges = []

    def serve(handler):
        requested = handler.headers.get("Range")
        ranges.append(requested)
        if requested:
            assert handler.headers["If-Range"] == ETAG
            start = int(requested.removeprefix("bytes=").removesuffix("-"))
            assert 0 < start <= len(PREFIX)
            handler.send_response(206)
            handler.send_header("Content-Range", f"bytes {start}-{len(MOVIE)-1}/{len(MOVIE)}")
            body = MOVIE[start:]
        else:
            handler.send_response(200)
            body = MOVIE
        handler.send_header("ETag", ETAG)
        handler.send_header("Content-Length", str(len(body)))
        handler.end_headers()
        if len(ranges) == 1:
            handler.wfile.write(PREFIX)
            sent.set()
            handler.connection.settimeout(15)
            try:
                if not handler.connection.recv(1):
                    disconnected.set()
            except ConnectionResetError:
                disconnected.set()
        else:
            handler.wfile.write(body)

    assets["/movie"] = serve
    return sent, disconnected, ranges


def ready(process):
    out, err = process.communicate(timeout=10)
    assert process.returncode == 0, err
    return [Path(item["path"]) for item in json.loads(out)["items"]]


@pytest.mark.parametrize("interruption,expected_exit", [
    pytest.param(signal.SIGINT, 130, marks=pytest.mark.skipif(os.name == "nt", reason="POSIX SIGINT")),
    (signal.SIGTERM, 1 if os.name == "nt" else -signal.SIGTERM),
])
def test_stopping_exclusive_waiter_withdraws_queue_and_retains_its_breakpoint(
    media_cli, origin, interruption, expected_exit,
):
    base, assets, requests = origin
    sent, disconnected, ranges = interrupted_movie(assets)
    assets["/ready"] = (200, b"ready")
    args = ("--wait", "--task-id", "post", "--urls")
    existing, = ready(media_cli(*args, base + "/ready"))
    waiter = media_cli(*args, base + "/ready", base + "/movie", base + "/queued")
    try:
        assert sent.wait(8)
        waiter.send_signal(interruption)
        waiter.communicate(timeout=5)
        assert waiter.returncode == expected_exit
        assert disconnected.wait(3), "exclusive transfer is still reading a stalled response"
        assert existing.read_bytes() == b"ready"
        movie, = ready(media_cli(*args, base + "/movie"))
        assert movie.read_bytes() == MOVIE
        assert len(ranges) == 2 and ranges[1].startswith("bytes=")
        assert requests == ["/ready", "/movie", "/movie"]
    finally:
        if waiter.poll() is None:
            waiter.kill()
            waiter.wait()


def worker_of(caller):
    # Discover the detached worker via the OS process tree while its original
    # CLI is still waiting. No queue or lockfile format is part of the test.
    processes = subprocess.check_output(["ps", "-A", "-o", "pid=,ppid="], text=True)
    children = [int(pid) for pid, parent in (line.split() for line in processes.splitlines())
                if int(parent) == caller.pid]
    worker, = children
    return worker


@pytest.mark.skipif(os.name == "nt", reason="Uses the POSIX process tree and SIGKILL")
def test_waiters_recover_a_killed_worker_without_another_cli_call(media_cli, origin):
    base, assets, requests = origin
    sent, disconnected, ranges = interrupted_movie(assets)
    args = ("--wait", "--task-id", "post", "--urls", base + "/movie")
    waiters = [media_cli(*args, SAU_DOWNLOAD_CONCURRENCY="2")]
    try:
        assert sent.wait(8)
        for i in range(2):
            path = f"/image-{i}"
            assets[path] = (200, b"image")
            waiters.append(media_cli(*args, base + path))
        deadline = time.monotonic() + 8
        while not {"/image-0", "/image-1"}.issubset(requests):
            assert time.monotonic() < deadline, requests
            time.sleep(.05)
        os.kill(worker_of(waiters[0]), signal.SIGKILL)
        assert disconnected.wait(3), "killing the scheduler left a stalled writer at the origin"
        for waiter in waiters:
            movie, *_ = ready(waiter)
            assert movie.read_bytes() == MOVIE
        assert len(ranges) == 2 and ranges[1].startswith("bytes=")
    finally:
        for waiter in waiters:
            if waiter.poll() is None:
                waiter.kill()
                waiter.wait()


@pytest.mark.skipif(os.name == "nt", reason="Uses the POSIX process tree and SIGKILL")
def test_accepted_interest_survives_waiter_and_worker_until_next_acquisition(media_cli, origin):
    base, assets, requests = origin
    sent, disconnected, ranges = interrupted_movie(assets)
    args = ("--task-id", "background", "--urls", base + "/movie")
    waiter = media_cli("--wait", *args)
    try:
        assert sent.wait(8)
        worker = worker_of(waiter)
        background = media_cli(*args)
        out, err = background.communicate(timeout=8)
        assert background.returncode == 0 and json.loads(out)["status"] == "accepted", err
        waiter.kill()
        waiter.wait()
        assert not disconnected.wait(.4)
        os.kill(worker, signal.SIGKILL)
        assert disconnected.wait(3)
        time.sleep(.4)
        assert requests == ["/movie"]
        # An unrelated acquisition restarts the durable background request.
        assets["/image"] = (200, b"image")
        ready(media_cli("--wait", "--task-id", "other", "--urls", base + "/image"))
        movie, = ready(media_cli("--wait", *args))
        assert movie.read_bytes() == MOVIE
        assert len(ranges) == 2 and ranges[1].startswith("bytes=")
        assert requests == ["/movie", "/movie", "/image"]
    finally:
        if waiter.poll() is None:
            waiter.kill()
            waiter.wait()


def test_terminating_one_waiter_leaves_shared_transfer_running(media_cli, origin):
    base, assets, requests = origin
    started, joined, release = Event(), Event(), Event()

    def slow(handler):
        handler.send_response(200)
        handler.send_header("Content-Length", "5")
        handler.end_headers()
        started.set()
        if release.wait(12):
            handler.wfile.write(b"video")

    def image(handler):
        handler.send_response(200)
        handler.send_header("Content-Length", "0")
        handler.end_headers()
        joined.set()

    assets.update({"/movie": slow, "/image": image})
    args = ("--wait", "--task-id", "shared", "--urls", base + "/movie")
    first = media_cli(*args, SAU_DOWNLOAD_CONCURRENCY="2")
    try:
        assert started.wait(8)
        second = media_cli(*args, base + "/image")
        assert joined.wait(8)
        first.kill()
        first.wait()
    finally:
        release.set()
        if first.poll() is None:
            first.kill()
            first.wait()
    movie, _ = ready(second)
    assert movie.read_bytes() == b"video"
    assert requests == ["/movie", "/image"]
