"""Control the paired runtime inside a user-level desktop install."""
import csv
from contextlib import contextmanager
from getpass import getpass
from importlib.metadata import version
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
from tempfile import NamedTemporaryFile, TemporaryDirectory
import time
from uuid import uuid4

from . import __version__
from .__main__ import main as worker_main
from .providers import DEFAULT_BASES
from .worker import Settings


CONFIG_KEYS = {"SAU_GATEWAY_URL", "SAU_GATEWAY_CA_FILE", "SAU_DESKTOP_TOKEN", "WORKER_MAX_CONCURRENCY",
               "SAU_PROVIDERS", "BITBROWSER_API_BASE", "BITBROWSER_API_KEY", "ADSPOWER_API_BASE", "ADSPOWER_API_KEY"}


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
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def settings(state, env):
    path = state / "settings.json"
    saved = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    return {key: env[key] if key in env else saved[key] for key in CONFIG_KEYS if key in env or key in saved}


def configure(state, env, prompt=getpass):
    values = settings(state, env)
    providers = values.get("SAU_PROVIDERS")
    if providers is None:
        providers = ",".join(name for name in DEFAULT_BASES if values.get(name.upper() + "_API_KEY")) or "bitbrowser"
    values["SAU_PROVIDERS"] = providers
    selected = Settings.from_env(values).providers
    if not selected:
        raise ValueError("Select bitbrowser, adspower or both in SAU_PROVIDERS")
    for provider in selected:
        key = provider.upper() + "_API_KEY"
        if not values.get(key, "").strip():
            if prompt is getpass and not sys.stdin.isatty():
                raise ValueError(f"Set {key} or run bootstrap from an interactive terminal")
            values[key] = prompt(f"{key}: ").strip()
            if not values[key]:
                raise ValueError(f"Missing {key}")
    atomic_write(state / "settings.json", json.dumps(values))
    return values


@contextmanager
def lock(path):
    # Both primitives release automatically on process death. Leave the inode in place.
    with path.open("a+b") as stream:
        if os.name == "nt":
            import msvcrt
            if stream.tell() == 0:
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


def interpreter(root):
    return root / "program/runtime" / ("python.exe" if os.name == "nt" else "bin/python3.11")


def apply_settings(root):
    os.environ.update(settings(root / "state", os.environ))
    os.environ.pop("SAU_CLI_PATH", None)
    os.environ.update(SAU_CLI_PYTHON=str(interpreter(root)), SAU_INSTALL_ROOT=str(root),
                      SAU_HOME=str(root / "state/cli"))


def private_state(root):
    state = root / "state"
    state.mkdir(mode=0o700, exist_ok=True)
    if os.name == "nt":
        # A custom writable parent may grant access to other local accounts.
        who = subprocess.check_output(["whoami.exe", "/user", "/fo", "csv", "/nh"], text=True)
        sid = next(csv.reader([who.strip()]))[-1]
        subprocess.run(["icacls.exe", state, "/inheritance:r", "/grant:r", f"*{sid}:(OI)(CI)F"],
                       stdout=subprocess.DEVNULL, check=True)
    else:
        state.chmod(0o700)
    return state


def run(root, ready=None):
    if os.name == "nt":
        directory = Path(os.environ["LOCALAPPDATA"]) / "social-auto-upload" / ".instance"
    else:
        directory = Path.home() / "Library/Caches/social-auto-upload"
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    with lock(directory / "claim.lock") as acquired:
        owner = directory / "owner.json"
        if acquired:
            atomic_write(owner, json.dumps({"root": str(root), "pid": os.getpid()}))
        elif not owner.exists() or json.loads(owner.read_text(encoding="utf-8"))["root"] != str(root):
            raise ValueError("A desktop worker is already running under another installation")
        if ready:
            atomic_write(ready, owner.read_text(encoding="utf-8"))
        if acquired:
            sys.argv = ["cli-service", "run"]
            return worker_main()
        return 0


def start(root):
    apply_settings(root)
    Settings.from_env(os.environ)
    ready = root / "state" / ("starting-" + uuid4().hex)
    flags = {"creationflags": subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" else {"start_new_session": True}
    try:
        with (root / "state/worker.log").open("ab") as log:
            child = subprocess.Popen([interpreter(root), "-IB", "-m", "sau_worker.desktop", "_claim", ready.name],
                                     stdin=subprocess.DEVNULL, stdout=log, stderr=log, cwd=root, **flags)
        deadline = time.monotonic() + 15
        while not ready.is_file():
            if child.poll() is not None or time.monotonic() > deadline:
                raise ValueError("Worker did not start; see state/worker.log")
            time.sleep(0.05)
        print(ready.read_text(encoding="utf-8"))
    finally:
        ready.unlink(missing_ok=True)
    return 0


def install(root, revision, sha256, target):
    root = Path(root).resolve()
    image = Path(sys.prefix).resolve().parent
    manifest = json.loads((image / "release.json").read_text(encoding="utf-8"))
    system = ("windows" if os.name == "nt" else "macos")
    machine = {"amd64": "x86_64"}.get(platform.machine().lower(), platform.machine().lower())
    expected = dict(schema=1, revision=revision, target=target, version=__version__)
    if (manifest != expected or target != system + "-" + machine or
            version("social-auto-upload") != __version__ or version("social-media-worker") != __version__):
        raise ValueError("Package revision, target or paired CLI version mismatch")
    launcher = root / ("cli-service.cmd" if os.name == "nt" else "cli-service")
    program = root / "program"
    if not program.exists() and launcher.exists():
        raise ValueError("Install root already contains another cli-service")
    if any(p.is_symlink() for p in (program, root / "state", launcher)):
        raise ValueError("Install paths must be local directories and files")
    state = private_state(root)
    with lock(state / "install.lock") as acquired:
        if not acquired:
            raise ValueError("Another installer is active")
        marker = program / "package.sha256"
        if program.exists() and (not marker.is_file() or marker.read_text(encoding="ascii") != sha256):
            raise ValueError("Another release occupies this root; use the managed upgrade")
        configure(state, os.environ)
        if not program.exists():
            # Copy out of the running staged interpreter on Windows before the atomic rename.
            with TemporaryDirectory(dir=root, prefix=".install-") as scratch:
                installing = Path(scratch) / "program"
                shutil.copytree(image, installing)
                (installing / "package.sha256").write_text(sha256, encoding="ascii")
                installing.rename(program)
        script = ('@echo off\r\n"%~dp0program\\runtime\\python.exe" -IB -m sau_worker.desktop %*\r\n'
                  if os.name == "nt" else '#!/bin/sh\nexec "$(dirname "$0")/program/runtime/bin/python3.11" -IB -m sau_worker.desktop "$@"\n')
        atomic_write(launcher, script, executable=True)
        # Always start through the installed copy; the bootstrap stage is disposable.
        return subprocess.call([interpreter(root), "-IB", "-m", "sau_worker.desktop", "start"], cwd=root)


def main():
    args = sys.argv[1:]
    if len(args) == 5 and args[0] == "install":
        return install(*args[1:])
    root = Path(sys.prefix).resolve().parents[1]
    if not (root / "program/release.json").is_file():
        raise ValueError("Run the installed cli-service launcher")
    apply_settings(root)
    if args == ["start"]:
        return start(root)
    if args == ["run"]:
        return run(root)
    if len(args) == 2 and args[0] == "_claim":
        from uuid import UUID
        nonce = UUID(hex=args[1].removeprefix("starting-"))
        return run(root, root / "state" / ("starting-" + nonce.hex))
    return worker_main()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (EOFError, OSError, ValueError, subprocess.CalledProcessError) as exc:
        raise SystemExit(str(exc))
