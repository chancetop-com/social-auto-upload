"""Register or inspect a desktop release through the selected environment's internal Gateway."""
import argparse
from hashlib import sha256
import http.client
import json
import os
from pathlib import Path
import re
import ssl
import subprocess
import sys
import time
from urllib.parse import urlsplit
from uuid import UUID
import zipfile

ROOT = Path(__file__).resolve().parents[1]
TARGETS = ("macos-arm64", "macos-x86_64", "windows-x86_64")
ORIGINS = {"git@github.com:chancetop-com/social-auto-upload", "ssh://git@github.com/chancetop-com/social-auto-upload",
           "https://github.com/chancetop-com/social-auto-upload"}


def commit(ref):
    def git(*args):
        return subprocess.check_output(["git", "-C", ROOT, *args], text=True, stderr=subprocess.DEVNULL).strip()

    if git("remote", "get-url", "origin").removesuffix(".git") not in ORIGINS:
        raise ValueError("Expected the chancetop-com/social-auto-upload repository origin")
    if not ref or ref.startswith("-") or not re.fullmatch(r"[A-Za-z0-9._/-]+", ref):
        raise ValueError("Specify a local Git branch or commit")
    revision = git("rev-parse", "--verify", "--end-of-options", ref + "^{commit}")
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("Could not resolve a complete repository SHA")
    return revision


def packages(directory, revision):
    checked = {}
    versions = set()
    for target in TARGETS:
        path = directory / f"sau-desktop-{revision}-{target}.zip"
        if not path.is_file():
            continue
        fields = path.with_suffix(".sha256").read_text(encoding="ascii").split()
        checksum = sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(512 * 1024), b""):
                checksum.update(chunk)
        digest = checksum.hexdigest()
        if fields != [digest, path.name]:
            raise ValueError(f"Package SHA-256 mismatch: {path.name}")
        with zipfile.ZipFile(path) as archive:
            members = set(archive.namelist())
            site = ("runtime/Lib" if target.startswith("windows") else "runtime/lib/python3.11") + "/site-packages/"
            python = "runtime/python.exe" if target.startswith("windows") else "runtime/bin/python3.11"
            if (not {"release.json", python, site + "sau_cli.py", site + "sau_worker/__init__.py"} <= members
                    or archive.getinfo("release.json").file_size > 4096):
                raise ValueError("Incomplete private runtime, CLI, worker or release manifest")
            manifest = json.loads(archive.read("release.json"))
            version = manifest.get("version")
            if (not isinstance(version, str) or not version.strip() or manifest !=
                    dict(schema=1, revision=revision, target=target, version=version)):
                raise ValueError("Package manifest does not match its selected commit and native target")
            versions.add(version)
        checked[target] = (path, digest)
    if not checked or len(versions) != 1:
        raise ValueError("Provide matched desktop/build.py packages for the selected repository commit")
    return versions.pop(), checked


class Gateway:
    def __init__(self):
        address = urlsplit(os.environ.get("SAU_RELEASE_GATEWAY_URL", ""))
        if (not address.hostname or address.username or address.password or address.query or address.fragment
                or address.path not in ("", "/") or (address.scheme != "https"
                and not (address.scheme == "http" and address.hostname in ("localhost", "127.0.0.1", "::1")))):
            raise ValueError("Set SAU_RELEASE_GATEWAY_URL to the internal HTTPS Gateway or a loopback port-forward")
        self.address = address
        self.token = os.environ.get("GATEWAY_INTERNAL_TOKEN", "")
        if not self.token.strip():
            raise ValueError("Set GATEWAY_INTERNAL_TOKEN for the release operator")

    def request(self, method, path, *, body=None, length=None, content_type="application/json"):
        address = self.address
        if address.scheme == "https":
            context = ssl.create_default_context(cafile=os.environ.get("SAU_GATEWAY_CA_FILE"))
            client = http.client.HTTPSConnection(address.hostname, address.port, context=context, timeout=120)
        else:
            client = http.client.HTTPConnection(address.hostname, address.port, timeout=120)
        try:
            headers = {"Authorization": "Bearer " + self.token, "Content-Type": content_type}
            if length is not None:
                headers["Content-Length"] = str(length)
            client.request(method, path, body=body, headers=headers)
            response = client.getresponse()
            if not 200 <= response.status < 300:
                raise ValueError(f"Gateway {method} {path} returned HTTP {response.status}")
            return json.load(response)
        finally:
            client.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    worker = commands.add_parser("worker")
    status = commands.add_parser("status")
    for command in (worker, status):
        command.add_argument("--env", choices=["dev", "uat", "prod"], required=True)
        command.add_argument("--watch", action="store_true", help="print changed progress until validated or paused")
    worker.add_argument("--ref", default="main")
    worker.add_argument("--artifacts", type=Path, default=Path(os.environ.get("SAU_RELEASE_ARTIFACT_DIR", "desktop/dist")))
    status.add_argument("--release-id", type=UUID, required=True)
    args = parser.parse_args()
    if args.env != "dev":
        parser.error(f"The {args.env} desktop release environment is disabled")
    try:
        gateway = Gateway()
        if args.command == "worker":
            revision = commit(args.ref)
            version, checked = packages(args.artifacts, revision)
            for path, digest in checked.values():
                with path.open("rb") as stream:
                    gateway.request("PUT", "/internal/releases/packages/" + digest, body=stream,
                                    length=os.fstat(stream.fileno()).st_size, content_type="application/zip")
            manifest = {"environment": args.env, "revision": revision, "version": version, "contractVersion": 1,
                        "packages": {target: digest for target, (_, digest) in checked.items()}}
            info = gateway.request("POST", "/internal/releases", body=json.dumps(manifest).encode())
            release_id = info["releaseId"]
        else:
            release_id = str(args.release_id)
            info = gateway.request("GET", "/internal/releases/" + release_id)
        last = None
        while True:
            if info != last:
                print(json.dumps(info, ensure_ascii=False), flush=True)
                last = info
            if not args.watch or info["onlineReady"] or info["pauseReason"] or info["superseded"]:
                return
            time.sleep(3)
            info = gateway.request("GET", "/internal/releases/" + release_id)
    except (OSError, ValueError, subprocess.CalledProcessError, http.client.HTTPException, zipfile.BadZipFile) as exc:
        parser.exit(1, str(exc) + "\n")


if __name__ == "__main__":
    main()
