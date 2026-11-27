"""Occupancy follows the paired CLI process, even if its worker disappears."""
from contextlib import contextmanager
import os
from pathlib import Path
import runpy
import subprocess
import sys
import threading
import time
from uuid import uuid4

from .state import held, lock


class Children:
    def __init__(self, state):
        self.directory = state / "children"

    def live(self, excluding=None):
        for marker in self.directory.glob("*.lock"):
            if marker.name.split(".", 1)[0] != excluding and held(marker):
                yield marker

    def count(self, excluding=None):
        return sum(1 for _ in self.live(excluding))

    def terminate(self):
        for marker in self.live():
            # The matching process monitors its unique marker. Never signal a stored PID.
            marker.with_suffix(".terminate").touch()

    @contextmanager
    def launch(self, session, python, args, env):
        self.directory.mkdir(mode=0o700, exist_ok=True)
        marker = self.directory / (session + "." + uuid4().hex + ".lock")
        argv = [*python, "-m", "sau_worker.children", str(marker), *args]
        with subprocess.Popen(argv, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, encoding="utf-8", errors="replace") as proc:
            try:
                # Grant execution only after the child holds its own occupancy lock.
                # EOF before that grant (parent crash) means no command may start.
                deadline = time.monotonic() + 15
                while not marker.with_suffix(".ready").exists() and proc.poll() is None:
                    if time.monotonic() >= deadline:
                        raise subprocess.TimeoutExpired(argv, 15)
                    time.sleep(.02)
                if proc.poll() is None:
                    proc.stdin.write("run\n")
                    proc.stdin.close()
                    proc.stdin = None
                yield proc
            except BaseException:
                proc.kill()
                proc.wait()
                raise
            finally:
                marker.with_suffix(".ready").unlink(missing_ok=True)
                marker.unlink(missing_ok=True)
                marker.with_suffix(".terminate").unlink(missing_ok=True)


def dispatch():
    marker = Path(sys.argv.pop(1))
    # Readers can briefly hold the lock while checking capacity.
    while True:
        with lock(marker) as acquired:
            if acquired:
                marker.with_suffix(".ready").touch()
                if sys.stdin.readline() == "run\n":
                    run_cli(marker)
                return
        time.sleep(.01)


def run_cli(marker):
    def watch():
        while not marker.with_suffix(".terminate").exists():
            time.sleep(.1)
        os._exit(125)
    threading.Thread(target=watch, daemon=True).start()
    sys.argv[0] = "sau"
    runpy.run_module("sau_cli", run_name="__main__", alter_sys=True)


if __name__ == "__main__":
    dispatch()
