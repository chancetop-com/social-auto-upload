"""Stage an authenticated, complete desktop image before a native host switches it."""

import hashlib
import os
import platform
import re
import shutil
import ssl
import stat
import subprocess
import sys
import threading
import zipfile
from importlib.metadata import version
from uuid import UUID, uuid4

import httpx

from . import __version__
from .state import atomic_write, held, lock, read, write


class DownloadError(ValueError):
    """Retry transfer without treating missing or changed bytes as a package defect."""


class BatchClosed(ValueError):
    """This desktop lost its serialized grant before the image was committed."""


class PackageDefect(ValueError):
    """A verified archive contains an invalid or unusable paired program."""


def target_python(image):
    return image / "runtime" / ("python.exe" if os.name == "nt" else "bin/python3.11")


def verify_image(image, assignment):

    machine = {"amd64": "x86_64"}.get(platform.machine().lower(), platform.machine().lower())
    target = {"Darwin": "macos", "Windows": "windows"}.get(platform.system(), "") + "-" + machine
    expected = {"schema": 1, "revision": assignment["revision"], "target": target, "version": __version__}
    if (
        read(image / "release.json") != expected
        or target != assignment["target"]
        or version("social-auto-upload") != __version__
        or version("social-media-worker") != __version__
    ):
        raise PackageDefect("Package revision, target or paired CLI version mismatch")
    probe = subprocess.run(
        [sys.executable, "-IB", "-m", "sau_cli", "--version"],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=45,
        check=False,
    )
    if probe.returncode or probe.stdout.strip() != "sau " + __version__:
        raise PackageDefect("Paired CLI failed its version check")


def probe(image, assignment):
    try:
        result = subprocess.run(
            [
                target_python(image),
                "-IB",
                "-m",
                "sau_worker.desktop",
                "_verify",
                assignment["revision"],
                assignment["target"],
            ],
            cwd=image,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=90,
            check=False,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, PermissionError) as exc:
        raise PackageDefect("Verified package cannot start its private runtime") from exc
    if result.returncode:
        raise PackageDefect("Verified package failed its paired worker/CLI check")


def extract(archive, destination):
    files, directories = set(), set()
    for member in archive.infolist():
        name = member.filename
        parts = name.split("/")
        if (
            (name != "release.json" and not name.startswith("runtime/"))
            or stat.S_IFMT(member.external_attr >> 16) != stat.S_IFREG
            or any(
                not part
                or part.endswith((".", " "))
                or re.search(r'[\x00-\x1f\x7f\\:<>"|*?]', part)
                or re.match(r"^(con|prn|aux|nul|com[1-9]|lpt[1-9])(\.|$)", part, re.IGNORECASE)
                for part in parts
            )
        ):
            raise PackageDefect("Unsafe package member")
        parents = ["/".join(parts[:n]).casefold() for n in range(1, len(parts))]
        key = name.casefold()
        if key in files or key in directories or any(parent in files for parent in parents):
            raise PackageDefect("Conflicting package members")
        files.add(key)
        directories.update(parents)
    for member in archive.infolist():
        path = destination / member.filename
        path.parent.mkdir(parents=True, exist_ok=True)
        with archive.open(member) as source, path.open("xb") as dest:
            shutil.copyfileobj(source, dest)
        path.chmod(0o755 if member.external_attr >> 16 & 0o111 else 0o644)


def stage(root, assignment, chunks, check=probe):
    versions = root / ".versions"
    versions.mkdir(mode=0o700, exist_ok=True)
    if (versions / "switch").exists():
        if (versions / "switch").read_text() != assignment["sha256"]:
            raise DownloadError("Finishing a prior release switch")
        return
    scratch = versions / "download"
    if scratch.exists():
        shutil.rmtree(scratch)
    scratch.mkdir()
    package = scratch / "package.zip"
    checksum = hashlib.sha256()
    with package.open("xb") as output:
        for chunk in chunks:
            output.write(chunk)
            checksum.update(chunk)
    if checksum.hexdigest() != assignment["sha256"]:
        raise DownloadError("Package SHA-256 mismatch; retrying download")
    image = scratch / "image"
    image.mkdir()
    try:
        with zipfile.ZipFile(package) as archive:
            extract(archive, image)
    except zipfile.BadZipFile as exc:
        raise PackageDefect("Verified archive is not a complete ZIP") from exc
    check(image, assignment)
    atomic_write(image / "package.sha256", assignment["sha256"])
    ready = versions / "next"
    if ready.is_dir():
        shutil.rmtree(ready)
    image.rename(ready)
    atomic_write(versions / "switch", assignment["sha256"])


def installation(root):

    program = root / "program"
    marker = program / "package.sha256"
    if not marker.exists():
        return None
    state = root / "state"
    identity = state / "machine-id"
    if not identity.exists():
        with lock(state / "machine.lock") as acquired:
            if acquired and not identity.exists():
                atomic_write(identity, str(uuid4()))
        if not identity.exists():
            return None
    manifest = read(program / "release.json")
    observed = {
        "machineId": str(UUID(identity.read_text().strip())),
        "revision": manifest["revision"],
        "target": manifest["target"],
        "sha256": marker.read_text().strip(),
    }
    batch = read(state / "upgrade.json")
    if batch.get("step") == "validating" and all(
        batch.get(k) == observed[k] for k in ("revision", "target", "sha256")
    ):
        observed["batchId"] = batch["batchId"]
    return observed


def assignment_for(value, target):

    if not isinstance(value, dict):
        raise TypeError("Expected release assignment")
    keys = ("releaseId", "batchId", "revision", "target", "sha256", "url")
    result = {key: value[key] for key in keys}
    for key in ("releaseId", "batchId"):
        UUID(result[key])
    if (
        result["target"] != target
        or not re.fullmatch("[a-f0-9]{40}", result["revision"])
        or not re.fullmatch("[a-f0-9]{64}", result["sha256"])
        or result["url"] != "/session/release/packages/" + result["sha256"]
    ):
        raise ValueError("Invalid Gateway release package pin or source")
    return result


def progress_body(root, batch, phase, **extra):
    return {key: batch[key] for key in ("releaseId", "batchId")} | {
        "machineId": installation(root)["machineId"],
        "phase": phase,
        **extra,
    }


class ReleaseAgent:
    def __init__(self, root, client, token):
        self.root = root
        self.client = client
        self.headers = {"Authorization": "Bearer " + token}
        self.state = root / "state"
        self.pending = self.state / "upgrade.json"
        self.versions = root / ".versions"

    def post(self, path, body):
        response = self.client.post("/session/release/" + path, headers=self.headers, json=body)
        response.raise_for_status()
        return response.json()

    def progress(self, batch, phase, **extra):
        return self.post("progress", progress_body(self.root, batch, phase, **extra))

    def clear(self):
        # Only the supervisor clears the previous program and the assignment.
        retired = self.root / ".retired-release"
        if retired.exists():
            shutil.rmtree(retired)
        if self.versions.is_dir():
            self.versions.rename(retired)
            shutil.rmtree(retired)
        (self.state / "release-check-result.json").unlink(missing_ok=True)
        self.pending.unlink(missing_ok=True)

    def discover(self):

        observed = installation(self.root)
        if not observed:
            return
        observed.pop("batchId", None)
        worker = read(self.state / "worker.json")

        if held(self.state / "worker.lock") and worker.get("sessionId"):
            observed["sessionId"] = worker["sessionId"]
        reply = self.post("discover", observed)
        batch = read(self.pending)
        if batch:
            if (self.versions / "revoked").exists() and not (self.versions / "previous").exists():
                self.clear()
            elif (self.versions / "repair").exists():
                write(self.pending, {**batch, "step": "draining"})
                (self.state / "release-check-result.json").unlink(missing_ok=True)
                shutil.rmtree(self.versions)
            elif (self.versions / "rollback").exists():
                self.progress(batch, "defect", reason="Activated private runtime or paired CLI failed startup")
                self.clear()
            elif batch.get("defect"):
                self.progress(batch, "defect", reason=batch["defect"])
                self.clear()
            elif batch.get("step") in ("validating", "returning"):
                receipt = read(self.state / "release-check-result.json")
                if receipt.get("batchId") == batch["batchId"]:
                    response = self.progress(
                        batch,
                        "ready",
                        sessionId=receipt["sessionId"],
                        checkWorkflowId=receipt["checkWorkflowId"],
                    )
                    if response["confirmed"] or not response["active"]:
                        self.clear()
                elif not reply.get("assignment") or reply["assignment"]["batchId"] != batch["batchId"]:
                    # It may have expired while offline. Do not let an obsolete
                    # local assignment prevent this desktop from converging later.
                    response = self.progress(batch, "switched")
                    if not response["active"]:
                        self.clear()
            return
        if reply.get("assignment"):
            batch = assignment_for(reply["assignment"], observed["target"])
            write(self.pending, {**batch, "step": "draining"})
            self.progress(batch, "draining")

    def needs_drain(self):
        return read(self.pending).get("step") in ("draining", "staging")

    def after_drain(self):
        """Called only after the old worker, its reports and every child have exited."""

        batch = read(self.pending)
        if batch.get("defect") or not batch or (self.versions / "repair").exists():
            return False
        try:
            if batch["step"] == "draining":
                # Recovery may resume after either a lost response or the local write.
                if not self.progress(batch, "draining")["active"]:
                    self.clear()
                    return False
                batch["step"] = "staging"
                write(self.pending, batch)
            if not self.progress(batch, "staging")["active"]:
                self.clear()
                return False
            actual = installation(self.root)
            if any(batch[k] != actual[k] for k in ("revision", "target", "sha256")):

                def check_grant(image, pinned):
                    probe(image, pinned)
                    if not self.progress(batch, "staging")["active"]:
                        raise BatchClosed("Release batch expired during download")

                with self.client.stream("GET", batch["url"], headers=self.headers) as response:
                    response.raise_for_status()
                    stage(self.root, batch, response.iter_bytes(chunk_size=512 * 1024), check_grant)
            batch["step"] = "validating"
            write(self.pending, batch)
            return True
        except BatchClosed:
            self.clear()
        except PackageDefect as exc:
            write(self.pending, {**batch, "defect": str(exc)})
        except (DownloadError, httpx.HTTPError, OSError) as exc:
            print(f"Release staging will retry ({type(exc).__name__})", file=sys.stderr, flush=True)
        return False


def start_monitor(root):

    from .worker import Settings

    if not (root / "program/package.sha256").is_file():
        return None
    settings = Settings.from_env(os.environ)
    ca = os.environ.get("SAU_GATEWAY_CA_FILE")
    client = httpx.Client(
        base_url=settings.gateway,
        trust_env=False,
        timeout=20,
        verify=ssl.create_default_context(cafile=ca) if ca else True,
    )
    agent = ReleaseAgent(root, client, settings.token)
    stop = threading.Event()

    def watch():
        try:
            while not stop.is_set():
                try:
                    agent.discover()
                except (httpx.HTTPError, ValueError, TypeError, KeyError, OSError) as exc:
                    print(f"Release discovery will retry ({type(exc).__name__})", file=sys.stderr, flush=True)
                stop.wait(5)
        finally:
            client.close()

    threading.Thread(target=watch, daemon=True).start()
    return agent, stop
