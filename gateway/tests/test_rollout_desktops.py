"""Two temporary macOS installations, PostgreSQL and the operator CLI, with a no-browser check fixture."""

import hashlib
import json
import os
import platform
import subprocess
import time
import zipfile
from contextlib import ExitStack
from pathlib import Path

import httpx
import pytest

from desktop.build import member
from desktop.tests.native_login_fixture import stub_commands
from gateway.tests.test_release_command import ROOT, run, serving


def fixture_bundle(directory, source, revision, *, defective=False, worker_tree=None):
    """Keep native CPython and HTTP dependencies; replace the account probe with a controlled process."""
    target = "macos-arm64"
    filename = directory / f"sau-desktop-{revision}-{target}.zip"
    site = "runtime/lib/python3.11/site-packages/"
    dependencies = {
        "anyio",
        "certifi",
        "h11",
        "httpcore",
        "httpx",
        "idna",
        "sniffio",
        "typing_extensions.py",
        "exceptiongroup",
    }
    with zipfile.ZipFile(source) as base, zipfile.ZipFile(filename, "w") as package:
        for entry in base.infolist():
            name = entry.filename
            if name.startswith(site):
                library = name.removeprefix(site).split("/")[0]
                if library not in dependencies and not library.startswith(
                    ("social_auto_upload-", "social_media_worker-")
                ):
                    continue
            elif not (name == "runtime/bin/python3.11" or name.startswith("runtime/lib/")):
                continue
            if "/test/" in name or name.endswith(".a"):
                continue
            package.writestr(entry, base.read(entry))
        with member(package, "release.json", 0o644) as f:
            f.write(
                json.dumps({"schema": 1, "revision": revision, "target": target, "version": "0.1.0"}).encode()
            )
        for code in (worker_tree or ROOT / "cli-service/sau_worker").iterdir():
            if code.is_file() and code.suffix in {".py", ".sh", ".ps1"}:
                with member(package, site + "sau_worker/" + code.name, 0o644) as f:
                    f.write(code.read_bytes())
        with member(package, site + "sau_cli.py", 0o644) as f:
            f.write(
                b"raise SystemExit(1)"
                if defective
                else b"""
import os, sys, time
from pathlib import Path
if sys.argv[1:] == ['--version']:
    print('sau 0.1.0')
elif sys.argv[1:3] == ['tiktok','check']:
    root = Path(os.environ['SAU_INSTALL_ROOT']) / 'state'
    (root / 'fixture-check').touch()
    while (root / 'hold').exists(): time.sleep(.05)
    if 'SAU_WINDOW_CLOSED_FILE' in os.environ: Path(os.environ['SAU_WINDOW_CLOSED_FILE']).touch()
    print('valid')
else: raise SystemExit(2)
"""
            )
    with filename.open("rb") as f:
        digest = hashlib.file_digest(f, "sha256").hexdigest()
    filename.with_suffix(".sha256").write_text(digest + "  " + filename.name + "\n")
    return digest


def until(check, timeout=90):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = check()
        if value:
            return value
        time.sleep(0.25)
    raise AssertionError(f"timed out waiting for {check.__name__}")


@pytest.mark.skipif(
    platform.system() != "Darwin"
    or platform.machine() != "arm64"
    or not os.environ.get("SAU_TEST_DESKTOP_ARTIFACT"),
    reason="requires the native 36 fixture archive",
)
def test_two_installed_workers_drain_report_validate_and_pause(tmp_path, gateway_env):
    source = os.environ["SAU_TEST_DESKTOP_ARTIFACT"]
    revisions = subprocess.check_output(
        ["git", "-C", ROOT, "rev-list", "--first-parent", "-3", "HEAD"], text=True
    ).splitlines()[::-1]
    for revision in revisions:
        fixture_bundle(tmp_path, source, revision, defective=revision == revisions[-1])
    with serving() as url, ExitStack() as cleanup:
        internal = {"Authorization": "Bearer fixture-internal"}
        operator = {
            "PATH": os.environ["PATH"],
            "SAU_RELEASE_GATEWAY_URL": url,
            "GATEWAY_INTERNAL_TOKEN": "fixture-internal",
        }

        def release(revision):
            result = run(operator, "worker", "--env", "dev", "--artifacts", str(tmp_path), "--ref", revision)
            assert result.returncode == 0, result.stderr
            return json.loads(result.stdout)["releaseId"]

        def status(release_id):
            return httpx.get(url + "/internal/releases/" + release_id, headers=internal, trust_env=False).json()

        first = release(revisions[0])
        roots = []
        machine_roots = {}
        for name in ("A", "B"):
            home = tmp_path / ("User " + name)
            root = tmp_path / ("Worker " + name)
            home.mkdir()
            env = {
                "HOME": str(home),
                "PATH": stub_commands(home / "commands-bin"),
                "SAU_GATEWAY_URL": url,
                "SAU_DESKTOP_TOKEN": "fixture-desktop",
                "SAU_DEV_CHROME_ALIASES": name,
                "SAU_RELEASE_CHECK_PROVIDER": "local-chrome",
                "SAU_RELEASE_CHECK_PROFILE": name,
                "SAU_RELEASE_CHECK_PLATFORM": "tiktok",
            }
            result = subprocess.run(
                [ROOT / "desktop/bootstrap.sh", "--approved", root],
                capture_output=True,
                timeout=90,
                check=False,
                text=True,
                env=env,
            )
            if (root / "cli-service").exists():
                cleanup.callback(subprocess.run, [root / "cli-service", "stop"], env=env, timeout=35)
            assert result.returncode == 0, result.stderr
            cleanup.callback((root / "state/hold").unlink, missing_ok=True)
            roots.append(root)
            machine_roots[(root / "state/machine-id").read_text().strip()] = root

            def validated(root=root):
                current = status(first)
                return (
                    len(current["nodes"]) == len(roots)
                    and current["onlineReady"]
                    and not (root / "state/upgrade.json").exists()
                )

            until(validated)
            (root / "state/fixture-check").unlink()
        for name, root in zip(("A", "B"), roots):
            (root / "state/hold").touch()
            record = {
                "workflowId": "fixture-old-" + name,
                "provider": "local-chrome",
                "profileId": name,
                "platform": "tiktok",
                "action": "check",
                "release": "0.1.0",
                "contractVersion": 1,
                "requiredCapability": "tiktok.check",
            }
            response = httpx.post(url + "/internal/occurrences", headers=internal, json=record, trust_env=False)
            response.raise_for_status()
            until((root / "state/fixture-check").exists)
        second = release(revisions[1])
        for index in range(2):

            def draining(index=index):
                history = status(second)["batches"]
                return len(history) == index + 1 and history[-1]["phase"] == "draining" and history[-1]

            batch = until(draining)
            root = machine_roots[batch["machineId"]]
            assert json.loads((root / "program/release.json").read_text())["revision"] == revisions[0]
            old_session = json.loads((root / "state/worker.json").read_text())["sessionId"]
            (root / "state/hold").unlink()

            def complete(index=index, root=root):
                history = status(second)["batches"]
                return history[index]["phase"] == "ready" and not (root / ".versions").exists()

            until(complete)
            assert json.loads((root / "state/worker.json").read_text())["sessionId"] != old_session
            assert json.loads((root / "program/release.json").read_text())["revision"] == revisions[1]
            assert (
                httpx.get(
                    url + "/internal/occurrences/fixture-old-" + root.name[-1],
                    headers=internal,
                    trust_env=False,
                ).json()["state"]
                == "succeeded"
            )
        status_cli = run(operator, "status", "--env", "dev", "--release-id", second)
        completed = json.loads(status_cli.stdout)
        assert completed["onlineReady"] and all(b["checkWorkflowId"] for b in completed["batches"])
        defective = release(revisions[-1])
        until(lambda: status(defective)["pauseReason"])
        assert len(status(defective)["batches"]) == 1
        for root in roots:
            assert json.loads((root / "program/release.json").read_text())["revision"] == revisions[1]


@pytest.mark.skipif(
    platform.system() != "Darwin"
    or platform.machine() != "arm64"
    or not os.environ.get("SAU_TEST_DESKTOP_ARTIFACT"),
    reason="requires the native 36 fixture archive",
)
def test_existing_supervisor_adopts_first_gateway_batch(tmp_path, gateway_env):
    # Install the predecessor whose native login target still points inside program.
    legacy = "5f7c864e7f37adcf20dabd235bb51841eb188cfa"
    current = subprocess.check_output(["git", "-C", ROOT, "rev-parse", "HEAD"], text=True).strip()
    tree = tmp_path / "legacy-worker"
    tree.mkdir()
    old_worker = "cli-service/sau_worker/"
    for path in subprocess.check_output(
        ["git", "-C", ROOT, "ls-tree", "-r", "--name-only", legacy, old_worker], text=True
    ).splitlines():
        if path.endswith(".py"):
            (tree / Path(path).name).write_bytes(
                subprocess.check_output(["git", "-C", ROOT, "show", legacy + ":" + path])
            )
    source = os.environ["SAU_TEST_DESKTOP_ARTIFACT"]
    old_digest = fixture_bundle(tmp_path, source, legacy, worker_tree=tree)
    fixture_bundle(tmp_path, source, current)
    home = tmp_path / "Old home"
    home.mkdir()
    root = tmp_path / "Old install"
    with serving() as url, ExitStack() as cleanup:
        env = {
            "HOME": str(home),
            "PATH": stub_commands(home / "commands-bin"),
            "SAU_GATEWAY_URL": url,
            "SAU_DESKTOP_TOKEN": "fixture-desktop",
            "SAU_DEV_CHROME_ALIASES": "old",
            "SAU_RELEASE_CHECK_PROVIDER": "local-chrome",
            "SAU_RELEASE_CHECK_PROFILE": "old",
            "SAU_RELEASE_CHECK_PLATFORM": "tiktok",
        }
        bootstrap = ROOT / "desktop/bootstrap.sh"
        subprocess.run([bootstrap, legacy, old_digest, tmp_path, root], env=env, timeout=40, check=True)
        cleanup.callback(subprocess.run, [root / "cli-service", "stop"], env=env, timeout=35)
        assert not (root / "release-host.sh").exists()
        operator = {
            "PATH": os.environ["PATH"],
            "SAU_RELEASE_GATEWAY_URL": url,
            "GATEWAY_INTERNAL_TOKEN": "fixture-internal",
        }
        record = run(operator, "worker", "--env", "dev", "--artifacts", str(tmp_path), "--ref", current)
        release_id = json.loads(record.stdout)["releaseId"]
        subprocess.run([bootstrap, "--approved", root], env=env, timeout=65, check=True)
        until(lambda: (root / "state/fixture-check").exists() and not (root / ".versions").exists())
        assert json.loads(run(operator, "status", "--env", "dev", "--release-id", release_id).stdout)[
            "onlineReady"
        ]
        assert (root / "release-host.sh").exists()
