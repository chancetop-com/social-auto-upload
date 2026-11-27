"""Supervise one desktop worker and coordinate operator lifecycle commands."""
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time
from uuid import uuid4

from .children import Children
from .login import native_login, start_browsers
from .state import held, lock, read, write
from .worker import Settings
from .rollout import start_monitor


class Backoff:
    delays = (0, 10, 20, 40, 80, 160, 300)

    def __init__(self):
        self.failures = 0

    def after_exit(self, uptime):
        if uptime >= 600:
            self.failures = 0
        delay = self.delays[min(self.failures, len(self.delays) - 1)]
        self.failures += 1
        return delay


def owner_directory():
    if os.name == "nt":
        directory = Path(os.environ["LOCALAPPDATA"]) / "social-auto-upload/.instance"
    else:
        directory = Path.home() / "Library/Caches/social-auto-upload"
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    return directory


def interpreter(root):
    return root / "program/runtime" / ("python.exe" if os.name == "nt" else "bin/python3.11")


def requested(state, generation):
    request = read(state / "request.json")
    return request.get("action") if request.get("generation") == generation else None


def ending(state, generation):
    return (requested(state, generation) or (state / "disabled").exists()
            or read(state / "supervisor.json").get("generation") != generation
            or not held(state / "supervisor.lock"))


def claimed_worker(root, generation):
    state = root / "state"
    # A replacement supervisor cannot start a second claiming process while an
    # orphaned worker finishes its command and attempts its original report.
    with lock(owner_directory() / "claim.lock", lifetime=True) as acquired:
        if not acquired:
            return 1
        if ending(state, generation):
            return 0
        with lock(state / "worker.lock", lifetime=True) as owns_root:
            if not owns_root:
                return 1
            # Works when this supervisor has already died and Popen is gone.
            # The marker addresses this unique worker birth, never a reused PID.
            nonce = uuid4().hex
            kill = state / ("force-" + nonce)
            write(state / "worker-owner.json", {"nonce": nonce})

            def check_force():
                while not kill.exists():
                    time.sleep(.1)
                os._exit(125)

            threading.Thread(target=check_force, daemon=True).start()
            os.environ["SAU_WORKER_GENERATION"] = generation
            sys.argv = ["cli-service", "run"]
            from .__main__ import main
            return main()


def supervise(root):
    state = root / "state"
    owner = owner_directory()
    with lock(owner / "supervisor.lock", lifetime=True) as owns_user, lock(state / "supervisor.lock", lifetime=True) as owns_root:
        if not owns_user or not owns_root or (state / "disabled").exists() or (state / "uninstalled").exists():
            return 0
        previous = read(owner / "owner.json").get("root")
        if previous and previous != str(root) and (held(owner / "claim.lock") or Children(Path(previous) / "state").count()):
            raise ValueError("A worker or CLI under another install root is still active")
        write(owner / "owner.json", {"root": str(root)})
        generation = uuid4().hex
        status_file = state / "supervisor.json"
        status = {"generation": generation, "pid": os.getpid(), "workerPid": None,
                  "lastExit": read(status_file).get("lastExit"), "nextAttempt": None}
        write(status_file, status)
        quitting = False

        def stop_on_signal(_signal, _frame):
            nonlocal quitting
            quitting = True

        signal.signal(signal.SIGTERM, stop_on_signal)
        signal.signal(signal.SIGINT, stop_on_signal)
        children = Children(state)
        retry = Backoff()
        start_browsers(Settings.from_env(os.environ))
        monitor = start_monitor(root)
        release = monitor[0] if monitor else None
        retry_release = 0
        process = None
        due = time.monotonic()
        with (state / "worker.log").open("ab") as log:
            while True:
                action = requested(state, generation)
                if quitting and not action:
                    write(state / "request.json", {"generation": generation, "action": "stop"})
                    action = "stop"
                changing = release and release.needs_drain()
                stopping = action or (state / "disabled").exists() or changing
                if process is not None and process.poll() is not None:
                    elapsed = time.monotonic() - started
                    delay = retry.after_exit(elapsed)
                    reason = action or ("disabled" if stopping else "unexpected")
                    status.update(workerPid=None, lastExit={"reason": reason, "code": process.returncode, "at": time.time()},
                                  nextAttempt=None if stopping else time.time() + delay)
                    write(status_file, status)
                    process = None
                    due = time.monotonic() + delay
                if stopping:
                    if action == "force":
                        # Popen refers to this child; the CLI registry uses per-process nonces.
                        if process is not None:
                            process.kill()
                        elif not held(owner / "claim.lock"):
                            children.terminate()
                    if process is None and not held(owner / "claim.lock") and not children.count():
                        status.update(workerPid=None, nextAttempt=None)
                        write(status_file, status)
                        if changing and not action and not (state / "disabled").exists():
                            if time.monotonic() >= retry_release:
                                if release.after_drain():
                                    monitor[1].set()
                                    return 75
                                retry_release = time.monotonic() + 5
                        else:
                            if monitor:
                                monitor[1].set()
                            return 0
                elif process is None and time.monotonic() >= due and not held(owner / "claim.lock"):
                    started = time.monotonic()
                    process = subprocess.Popen([interpreter(root), "-IB", "-m", "sau_worker.desktop", "_worker",
                                                generation], cwd=root, stdin=subprocess.DEVNULL, stdout=log, stderr=log)
                    status.update(workerPid=process.pid, nextAttempt=None)
                    write(status_file, status)
                time.sleep(.1)


def local_status(root):
    state = root / "state"
    manifest = read(root / "program/release.json")
    supervisor = read(state / "supervisor.json")
    worker = read(state / "worker.json")
    running = held(state / "supervisor.lock")
    worker_live = held(state / "worker.lock") and worker.get("pid") == supervisor.get("workerPid")
    enabled = not (state / "disabled").exists()
    ready = (worker_live and running and enabled and worker.get("claimReady", False)
             and not requested(state, supervisor.get("generation")) and time.time() - worker.get("updatedAt", 0) < 60)
    active = Children(state).count(excluding=worker.get("sessionId") if worker_live else None)
    if worker_live:
        active += worker.get("active", 0)
    capacity = worker.get("capacity") if worker_live else None
    capacity = capacity or int(os.environ.get("WORKER_MAX_CONCURRENCY", 1))
    upgrade = read(state / "upgrade.json")
    return {"upgrade": {k: upgrade.get(k) for k in ("releaseId","batchId","step","defect")} if upgrade else None,
            "root": str(root), "running": running, "enabled": enabled, "claimReady": bool(ready and active < capacity),
            "release": manifest.get("version"), "revision": manifest.get("revision"),
            "activeCount": active, "capacity": capacity,
            "pid": supervisor.get("pid") if running else None, "workerPid": supervisor.get("workerPid") if worker_live else None,
            "sessionId": worker.get("sessionId") if worker_live else None,
            "lastExit": supervisor.get("lastExit"), "nextAttempt": supervisor.get("nextAttempt") if running else None}


def drain(root, force=False):
    state = root / "state"
    children = Children(state)
    while True:
        supervisor = read(state / "supervisor.json")
        if held(state / "supervisor.lock"):
            action = "force" if force or requested(state, supervisor.get("generation")) == "force" else "stop"
            if supervisor.get("generation") and requested(state, supervisor["generation"]) != action:
                write(state / "request.json", {"generation": supervisor["generation"], "action": action})
        elif not held(state / "worker.lock"):
            if not children.count():
                return
            if force:
                children.terminate()
        if force and held(state / "worker.lock"):
            nonce = read(state / "worker-owner.json").get("nonce")
            if nonce:
                (state / ("force-" + nonce)).touch()
        time.sleep(.1)


def start(root):
    state = root / "state"
    if (state / "disabled").exists() or (state / "uninstalled").exists():
        return local_status(root)
    owner = owner_directory()
    if held(owner / "supervisor.lock") and read(owner / "owner.json").get("root") not in (None, str(root)):
        raise ValueError("A desktop worker is already running under another installation")
    retry_at = 0
    deadline = time.monotonic() + 15
    while True:
        snapshot = read(state / "supervisor.json")
        if snapshot.get("pid") and held(state / "supervisor.lock"):
            return {"root": str(root), "pid": snapshot["pid"]}
        if time.monotonic() >= deadline:
            raise ValueError("Supervisor did not start; see state/worker.log and the user's login task")
        if time.monotonic() >= retry_at:
            native_login(root, start=True)
            retry_at = time.monotonic() + 2
        time.sleep(.05)
