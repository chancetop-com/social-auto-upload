"""Control the paired runtime inside a user-level desktop install."""
import csv
from getpass import getpass
from importlib.metadata import version
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory

from . import __version__
from .state import atomic_write, lock, read, write
from .host import write_host
from .rollout import assignment_for, verify_image
from .login import native_login
from .supervisor import claimed_worker, drain, interpreter, local_status, start, supervise
from .__main__ import main as worker_main
from .providers import DEFAULT_BASES
from .worker import Settings


CONFIG_KEYS = {"SAU_RELEASE_CHECK_PROVIDER", "SAU_RELEASE_CHECK_PROFILE", "SAU_RELEASE_CHECK_PLATFORM", "SAU_GATEWAY_URL", "SAU_GATEWAY_CA_FILE", "SAU_DESKTOP_TOKEN", "WORKER_MAX_CONCURRENCY",
               "SAU_PROVIDERS", "SAU_DEV_CHROME_ALIASES", "BITBROWSER_APP_PATH", "ADSPOWER_APP_PATH", "BITBROWSER_API_BASE", "BITBROWSER_API_KEY", "ADSPOWER_API_BASE", "ADSPOWER_API_KEY"}


def settings(state, env):
    path = state / "settings.json"
    saved = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    return {key: env[key] if key in env else saved[key] for key in CONFIG_KEYS if key in env or key in saved}


def configure(state, env, prompt=getpass):
    values = settings(state, env)
    paired = Settings.from_env(values)
    if "SAU_PROVIDERS" not in values:
        if paired.providers or paired.dev_aliases:
            values["SAU_PROVIDERS"] = ",".join(paired.providers)
        else:
            values["SAU_PROVIDERS"] = "bitbrowser"
    selected = Settings.from_env(values)
    if not selected.providers and not selected.dev_aliases:
        raise ValueError("Select a managed provider or an explicit development Chrome alias")
    for provider in selected.providers:
        key = provider.upper() + "_API_KEY"
        if not values.get(key, "").strip():
            if prompt is getpass and not sys.stdin.isatty():
                raise ValueError(f"Set {key} or run bootstrap from an interactive terminal")
            values[key] = prompt(f"{key}: ").strip()
            if not values[key]:
                raise ValueError(f"Missing {key}")
    atomic_write(state / "settings.json", json.dumps(values))
    return values


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


def launcher_script(*, windows):
    # The calling shell outlives the private interpreter. In particular Windows
    # can only remove its executable/DLLs after the uninstall command exits.
    if windows:
        return r"""@echo off
setlocal
"%~dp0program\runtime\python.exe" -IB -m sau_worker.desktop %*
if errorlevel 1 exit /b %errorlevel%
if /i not "%~1"=="uninstall" exit /b 0
rd /s /q "%~dp0program"
if exist "%~dp0program" exit /b 1
del "%~f0" & exit /b 0
""".replace("\n", "\r\n")
    return """#!/bin/sh
set -eu
root=$(CDPATH= cd -- "$(dirname "$0")" && pwd -P)
if [ "${1:-}" = uninstall ]; then
    "$root/program/runtime/bin/python3.11" -IB -m sau_worker.desktop "$@"
    /bin/rm -rf -- "$root/program"
    /bin/rm -f -- "$root/cli-service"
else
    exec "$root/program/runtime/bin/python3.11" -IB -m sau_worker.desktop "$@"
fi
"""


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
        if (state / "uninstalled").exists() and program.exists():
            raise ValueError("Uninstall is still pending; finish cli-service uninstall before reinstalling")
        marker = program / "package.sha256"
        assignment_path = os.environ.get("SAU_BOOTSTRAP_ASSIGNMENT")
        batch = assignment_for(read(Path(assignment_path)), target) if assignment_path else None
        if batch and (batch["sha256"] != sha256 or batch["revision"] != revision):
            raise ValueError("Installer pin differs from the Gateway assignment")
        if batch and program.exists() and not (root / ("release-host.ps1" if os.name == "nt" else "release-host.sh")).exists():
            if not marker.is_file() or not interpreter(root).is_file() or not (program / "release.json").is_file():
                raise ValueError("Expected an existing paired desktop installation")
            return adopt(root, image, batch)

        if program.exists() and (not marker.is_file() or marker.read_text(encoding="ascii") != sha256):
            raise ValueError("Another release occupies this root; use the managed upgrade")
        configure(state, os.environ)
        if batch and not read(state / "upgrade.json"):
            write(state / "upgrade.json", {**batch, "step": "draining"})
        if not program.exists():
            # Copy out of the running staged interpreter on Windows before the atomic rename.
            with TemporaryDirectory(dir=root, prefix=".install-") as scratch:
                installing = Path(scratch) / "program"
                shutil.copytree(image, installing)
                (installing / "package.sha256").write_text(sha256, encoding="ascii")
                installing.rename(program)
        write_host(root, windows=os.name == "nt")
        atomic_write(launcher, launcher_script(windows=os.name == "nt"), executable=True)
        (state / "uninstalled").unlink(missing_ok=True)
        # Always start through the installed copy; the bootstrap stage is disposable.
        return subprocess.call([interpreter(root), "-IB", "-m", "sau_worker.desktop", "start"], cwd=root)


def adopt(root, image, batch):
    """Use a verified new bootstrap to enroll a pre-rollout supervisor in its first batch."""
    from .state import held
    from .supervisor import owner_directory
    from .rollout import start_monitor
    state = root / "state"
    if (state / "disabled").exists() or (state / "uninstalled").exists():
        raise ValueError("This installation is disabled")
    with lock(state / "control.lock") as acquired:
        if not acquired:
            raise ValueError("Another maintenance command is active")
        configure(state, os.environ)
        apply_settings(root)
        write(state / "upgrade.json", {**batch, "step": "draining"})
        monitor, stopping = start_monitor(root)
        try:
            if not monitor.progress(batch, "draining")["active"]:
                raise ValueError("Validation batch has expired; run approved install again")
            drain(root)
            if held(owner_directory() / "claim.lock"):
                raise ValueError("Previous worker still running; wait for the old process to exit before upgrading")
            if not monitor.progress(batch, "staging")["active"]:
                raise ValueError("Validation batch has expired; run approved install again")
            verify_image(image, batch)
            versions = root / ".versions"
            versions.mkdir(mode=0o700, exist_ok=True)
            archive = versions / "download/package.zip"
            archive.parent.mkdir(mode=0o700, exist_ok=True)
            shutil.copyfile(os.environ["SAU_VERIFIED_ARCHIVE"], archive)
            staged = versions / "next"
            if staged.is_dir():
                shutil.rmtree(staged)
            shutil.copytree(image, staged)
            atomic_write(staged / "package.sha256", batch["sha256"])
            write(state / "upgrade.json", {**batch, "step": "validating"})
            write_host(root, windows=os.name == "nt")
            atomic_write(versions / "switch", batch["sha256"])
            # Change the old native registration only after its claiming process has exited.
            native_login(root, remove=True)
            native_login(root, start=True)
        finally:
            stopping.set()
    return 0


def main():
    args = sys.argv[1:]
    if len(args) == 3 and args[0] == "_verify":
        verify_image(Path(sys.prefix).resolve().parent, {"revision": args[1], "target": args[2]})
        return 0
    if len(args) == 5 and args[0] == "install":
        return install(*args[1:])
    root = Path(sys.prefix).resolve().parents[1]
    if not (root / "program/release.json").is_file():
        raise ValueError("Run the installed cli-service launcher")
    apply_settings(root)
    state = root / "state"
    if args == ["_probe-install"]:
        verify_image(root / "program", read(state / "upgrade.json"))
        return 0
    if args in (["_supervise"], ["run"]):
        return supervise(root)
    if len(args) == 2 and args[0] == "_worker":
        return claimed_worker(root, args[1])
    if args == ["status"]:
        print(json.dumps(local_status(root)))
        return 0
    controls = (["start"], ["stop"], ["disable"], ["enable"], ["restart"], ["restart", "--force"], ["uninstall"])
    if args in controls:
        force = args == ["restart", "--force"]
        if force:
            drain(root, force=True)
        with lock(state / "control.lock") as acquired:
            if not acquired:
                raise ValueError("Another desktop maintenance operation is active")
            if args == ["uninstall"]:
                with lock(state / "install.lock") as can_remove:
                    if not can_remove:
                        raise ValueError("Another installer is active")
                    (state / "uninstalled").touch()
                    drain(root)
                    native_login(root, remove=True)
                    for name in ("release-host.sh", "release-host.ps1", "verify-install.py"):
                        (root / name).unlink(missing_ok=True)
                    for name in (".versions", ".retired-release"):
                        if (root / name).is_dir():
                            shutil.rmtree(root / name)
                    for name in ("upgrade.json", "release-check-result.json"):
                        (state / name).unlink(missing_ok=True)
                return 0
            if args == ["disable"]:
                (state / "disabled").touch()
            if args[0] in {"stop", "disable", "restart"}:
                drain(root)
            if args == ["disable"]:
                native_login(root, remove=True)
            if args == ["enable"]:
                (state / "disabled").unlink(missing_ok=True)
            if args[0] in {"start", "enable", "restart"}:
                if args[0] in {"enable", "restart"}:
                    configure(state, os.environ)
                print(json.dumps(start(root)))
            return 0
    result = worker_main()
    if args and args[0] == "check" and result == 0:
        import argparse
        options = argparse.ArgumentParser()
        for option in ("provider", "profile-id", "platform"):
            options.add_argument("--" + option, required=True)
        chosen = options.parse_args(args[1:])
        write(state / "release-check-target.json", {"provider": chosen.provider, "profile": chosen.profile_id,
                                                   "platform": chosen.platform})
    return result


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (EOFError, OSError, ValueError, subprocess.CalledProcessError) as exc:
        raise SystemExit(str(exc))
