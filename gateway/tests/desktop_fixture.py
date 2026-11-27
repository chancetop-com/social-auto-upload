"""Exercise the released bootstrap using fake user homes, then isolate the OS account lookup."""
from contextlib import contextmanager, ExitStack
import json
import os
from pathlib import Path
import shutil
import subprocess

from desktop.tests.native_login_fixture import stub_commands


@contextmanager
def bootstrapped_worker(root, build, artifact):
    revision = artifact.name.split("-")[2]
    digest = artifact.with_suffix(".sha256").read_text().split()[0]
    with ExitStack() as cleanup:
        for custom_root in (False, True):
            home = build / ("Custom home" if custom_root else "Default home")
            home.mkdir()
            selected = build / "Installed worker" if custom_root else home / "Library/Application Support/social-auto-upload"
            command = [root / "desktop/bootstrap.sh", revision, digest, artifact.parent]
            if custom_root:
                command.append(selected)
            env = {"HOME": str(home), "PATH": stub_commands(home / "native"),
                   "SAU_GATEWAY_URL": "http://127.0.0.1:1", "BITBROWSER_API_BASE": "http://127.0.0.1:1",
                   "SAU_DESKTOP_TOKEN": "fixture-only", "BITBROWSER_API_KEY": "fixture-only",
                   "WORKER_MAX_CONCURRENCY": "3", "SAU_CLI_PATH": "/unrelated/sau"}
            def bootstrap(environment):
                completed = subprocess.run(command, env=environment, cwd=build, text=True,
                                           capture_output=True, timeout=180)
                assert completed.returncode == 0, completed.stderr
                return json.loads(completed.stdout)
            first = bootstrap(env)
            cleanup.callback(subprocess.run, [selected / "cli-service", "stop"], env=env,
                             check=True, timeout=60, stdout=subprocess.DEVNULL)
            assert Path(first["root"]).samefile(selected)
            assert bootstrap({"HOME": str(home), "PATH": env["PATH"]}) == first
            assert not list(selected.glob(".bootstrap.*"))
            assert json.loads((selected / "program/release.json").read_text())["revision"] == revision
            assert (selected / "program/package.sha256").read_text() == digest
            python = selected / "program/runtime/bin/python3.11"
            probe = subprocess.check_output([python, "-IB", "-c",
                  "import sys, cv2, patchright, sau_cli, sau_worker; "
                  "print(sys.prefix, cv2.__file__, patchright.__file__, sau_cli.__file__, sau_worker.__file__, sep='\\n')"],
                  env={"HOME": str(home), "PATH": "/usr/bin:/bin", "SAU_HOME": str(selected / "state/cli")},
                  cwd=build, text=True)
            assert all(Path(p).resolve().is_relative_to(selected.resolve()) for p in probe.splitlines())
        # The CLI's OS-account lock lives in the real account home by design. This test-only
        # hook maps pwd.getpwuid to the synthetic user's fixture, as in the wheel smoke.
        packages = selected / "program/runtime/lib/python3.11/site-packages"
        shutil.copyfile(root / "tests/fixtures/offline_account.py", packages / "offline_account.py")
        (packages / "offline_account.pth").write_text(
            "import os; os.environ.get('OFFLINE_OS_PROFILE') and __import__('offline_account')\n")
        yield selected / "cli-service"
