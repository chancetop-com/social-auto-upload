"""Real installed entry points and disposable processes; only login and HTTP peers are fixtures."""
import contextlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time
import venv

import pytest

from desktop.tests.test_supervision import wait_for
from desktop.tests.native_login_fixture import stub_commands


pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="native macOS launcher fixture")


@pytest.fixture
def installation(tmp_path):
    root = tmp_path / "Worker root"
    runtime = root / "program/runtime"
    venv.EnvBuilder(symlinks=True).create(runtime)
    py = runtime / "bin/python3.11"
    site = next((runtime / "lib").glob("python*/site-packages"))
    code = Path(__file__).resolve().parents[2] / "cli-service"
    site.joinpath("worker.pth").write_text(str(code) + "\n" + str(Path(pytest.__file__).resolve().parents[1]) + "\n")
    calls = root / "calls"
    release = root / "finish"
    site.joinpath("sau_cli.py").write_text(
        "import sys,time,os\nfrom pathlib import Path\nif sys.argv[1:] == ['--version']:\n    print('sau 0.1.0')\n"
        "else:\n"
        f"    with Path({str(calls)!r}).open('a') as f: print(str(os.getpid())+' '+sys.argv[2],file=f)\n"
        f"    while not Path({str(release)!r}).exists(): time.sleep(.03)\n"
        "    print('TikTok video upload submitted: fixture.mp4')\n")
    (root / "program/release.json").write_text(json.dumps(dict(revision="b"*40, version="0.1.0", target="macos-arm64")))
    (root / "state").mkdir()
    home = tmp_path / "home"
    home.mkdir()
    bin_dir = tmp_path / "native"
    env = {"HOME": str(home), "PATH": stub_commands(bin_dir)}

    class Gateway(BaseHTTPRequestHandler):
        def do_POST(self):
            data = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            if self.path == "/browser/list":
                reply = {"success": True, "data": {"list": [{"id": "win"}]}} if local.ready else {"success": False}
            elif not local.online:
                self.send_error(503)
                return
            elif self.path == "/session":
                local.reports.append(data)
                reply = {}
            elif self.path == "/publish-task/claim":
                reply = {"task": None}
                with local.mutex:
                    if local.pending:
                        local.pending = False
                        local.claims.append(data["sessionId"])
                        reply = {"task": {"workflowId": "occ", "task": task}}
                        if local.leased:
                            reply["task"].update(leaseGrantId="fixture-grant", renewAfterSeconds=.2)
                if not reply["task"]:
                    local.poll_entered.set()
                    local.allow_poll.wait(6)
                    time.sleep(.15)
            elif self.path == "/publish-task/start":
                local.starts.append(data)
                reply = {"task": task}
            elif self.path in {"/publish-task/profile-lease/renew", "/publish-task/profile-lease/complete"}:
                local.leases.append((self.path, data))
                reply = {"idle": False}
            elif self.path == "/publish-task/result":
                local.results.append(data)
                while not local.ack.wait(.05):
                    pass
                reply = {}
            else:
                self.send_error(404)
                return
            body = json.dumps(reply).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    task = dict(workflowId="occ", postId="p", channelId="c", organizationId="o", bindingId="b",
                provider="bitbrowser", profileId="win", platform="tiktok", action="upload-video", noPublish=False,
                release="0.1.0", contractVersion=1, requiredCapability="tiktok.upload-video", settings={}, earliestPublishAt=None,
                media=[{"url": "https://media.test/demo.mp4", "role": "video"}], caption="fixture")
    from types import SimpleNamespace
    local = SimpleNamespace(ready=False, online=True, pending=False, reports=[], claims=[], starts=[],
                            results=[], leased=False, leases=[], mutex=threading.Lock(), ack=threading.Event(),
                            poll_entered=threading.Event(), allow_poll=threading.Event())
    local.allow_poll.set()
    with ThreadingHTTPServer(("127.0.0.1", 0), Gateway) as http:
        thread = threading.Thread(target=http.serve_forever, daemon=True)
        thread.start()
        url = "http://127.0.0.1:" + str(http.server_port)
        (root / "state/settings.json").write_text(json.dumps({"SAU_GATEWAY_URL": url, "SAU_DESKTOP_TOKEN": "test",
                     "BITBROWSER_API_KEY": "test", "BITBROWSER_API_BASE": url, "SAU_PROVIDERS": "bitbrowser"}))
        def control(*args, wait=True):
            p = subprocess.Popen([py, "-IB", "-m", "sau_worker.desktop", *args], env=env, cwd=root,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            if not wait:
                return p
            try:
                out, err = p.communicate(timeout=18)
            except subprocess.TimeoutExpired:
                p.kill()
                p.wait()
                raise
            assert p.returncode == 0, err
            return json.loads(out) if out.strip() else None
        try:
            yield root, local, control
        finally:
            release.touch()
            local.ack.set()
            local.allow_poll.set()
            with contextlib.suppress(Exception):
                control("stop")
            http.shutdown()


def test_stop_waits_through_authorized_publish_and_result_then_allows_next_login(installation):
    root, api, cli = installation
    assert not cli("status")["running"]
    assert api.reports == []
    first = cli("start")
    assert cli("start") == first
    wait_for(lambda: api.reports)
    native = [json.loads(line) for line in (root.parent / "home/commands").read_text().splitlines()]
    assert ["open", "-g", "-a", "BitBrowser"] in native
    assert sum(cmd[:2] == ["launchctl", "bootstrap"] for cmd in native) == 1
    assert not cli("status")["claimReady"] and api.claims == []
    api.ready = True
    wait_for(lambda: cli("status")["claimReady"])
    api.pending = True
    wait_for(lambda: (root / "calls").exists())
    stopping = cli("stop", wait=False)
    wait_for(lambda: not cli("status")["claimReady"])
    assert cli("status")["activeCount"] == 1
    (root / "finish").touch()
    wait_for(lambda: api.results)
    assert stopping.poll() is None
    api.ack.set()
    assert stopping.wait(6) == 0
    assert api.results == [{"sessionId": api.claims[0], "workflowId": "occ",
                            "receipt": {"outcome": "published", "cliInvoked": True, "exitCode": 0}}]
    stopped = cli("status")
    assert stopped["enabled"] and not stopped["running"] and not stopped["activeCount"]
    assert (Path(root.parent / "home") / "registered").exists()
    login = cli("_supervise", wait=False)
    try:
        wait_for(lambda: len(set(r["sessionId"] for r in api.reports)) == 2)
        assert len(api.starts) == len(api.results) == len((root / "calls").read_text().splitlines()) == 1
    finally:
        cli("stop")
        login.wait(6)


def test_crash_survivor_holds_capacity_and_force_restart_never_replays(installation):
    root, api, cli = installation
    api.ready = True
    api.pending = True
    cli("start")
    wait_for(lambda: (root / "calls").exists())
    before = cli("status")
    assert before["activeCount"] == 1 and not before["claimReady"]
    os.kill(before["workerPid"], signal.SIGKILL)
    wait_for(lambda: any(r["sessionId"] != before["sessionId"] for r in api.reports))
    surviving = cli("status")
    assert surviving["sessionId"] != before["sessionId"] and surviving["activeCount"] == 1
    assert not surviving["claimReady"] and surviving["lastExit"]["reason"] == "unexpected"
    assert all(r["freeSlots"] == 0 for r in api.reports if r["sessionId"] != before["sessionId"])
    cli("restart", "--force")
    wait_for(lambda: cli("status")["claimReady"])
    after = cli("status")
    assert after["sessionId"] not in {before["sessionId"], surviving["sessionId"]}
    assert after["activeCount"] == 0
    assert len(api.claims) == len(api.starts) == len((root / "calls").read_text().splitlines()) == 1
    assert api.results == []


def test_idle_crash_reconnect_disable_reboot_and_enable(installation):
    root, api, cli = installation
    api.ready = True
    cli("start")
    wait_for(lambda: cli("status")["claimReady"])
    initial = cli("status")
    api.online = False
    wait_for(lambda: not cli("status")["claimReady"])
    api.online = True
    wait_for(lambda: cli("status")["claimReady"])
    assert cli("status")["sessionId"] == initial["sessionId"]
    os.kill(initial["workerPid"], signal.SIGKILL)
    wait_for(lambda: cli("status")["claimReady"] and cli("status")["sessionId"] != initial["sessionId"])
    next_pid = cli("status")["workerPid"]
    os.kill(next_pid, signal.SIGKILL)
    wait_for(lambda: cli("status")["nextAttempt"])
    assert 0 < cli("status")["nextAttempt"] - time.time() <= 10
    cli("disable")
    assert not cli("status")["enabled"] and not cli("status")["running"]
    assert not (root.parent / "home/registered").exists()
    cli("_supervise")
    cli("start")
    assert not cli("status")["running"]
    cli("enable")
    wait_for(lambda: cli("status")["claimReady"])
    assert cli("status")["enabled"]
    assert (root.parent / "home/registered").exists()


def test_force_can_recover_a_busy_worker_after_supervisor_itself_dies(installation):
    root, api, cli = installation
    api.ready = api.pending = True
    cli("start")
    wait_for(lambda: (root / "calls").exists())
    before = cli("status")
    os.kill(before["pid"], signal.SIGKILL)
    wait_for(lambda: not cli("status")["running"])
    cli("restart", "--force")
    wait_for(lambda: cli("status")["claimReady"])
    assert before["sessionId"] != cli("status")["sessionId"]
    assert api.results == [] and len(api.starts) == 1


def test_uninstall_waits_for_report_then_removes_owned_program_only(installation):
    from sau_worker.desktop import launcher_script
    root, api, cli = installation
    env = {"HOME": str(root.parent / "home"), "PATH": str(root.parent / "native") + ":/usr/bin:/bin"}
    launcher = root / "cli-service"
    launcher.write_text(launcher_script(windows=False))
    launcher.chmod(0o700)
    api.ready = api.pending = True
    cli("start")
    wait_for(lambda: (root / "calls").exists())
    uninstall = subprocess.Popen([launcher, "uninstall"], env=env)
    (root / "finish").touch()
    wait_for(lambda: api.results)
    assert uninstall.poll() is None and (root / "program").is_dir()
    api.ack.set()
    assert uninstall.wait(6) == 0
    assert not launcher.exists() and not (root / "program").exists()
    assert not (root.parent / "home/registered").exists()
    assert (root / "state/settings.json").is_file() and (root / "finish").exists()


def test_stop_withdraws_slots_while_existing_long_poll_is_still_open(installation):
    root, api, cli = installation
    api.ready = True
    api.allow_poll.clear()
    cli("start")
    assert api.poll_entered.wait(4)
    stopping = cli("stop", wait=False)
    try:
        wait_for(lambda: api.reports[-1]["freeSlots"] == 0, timeout=3)
        assert stopping.poll() is None
    finally:
        api.allow_poll.set()
        stopping.wait(8)


def test_wake_rechecks_profiles_and_capacity_within_the_same_login(installation):
    root, api, cli = installation
    api.ready = True
    cli("start")
    wait_for(lambda: cli("status")["claimReady"])
    before = cli("status")
    # Simulate a paused desktop with this worker only. A screen lock keeps the
    # interactive login and its process alive, while sleep suspends execution.
    os.kill(before["workerPid"], signal.SIGSTOP)
    try:
        api.ready = False
    finally:
        os.kill(before["workerPid"], signal.SIGCONT)
    wait_for(lambda: not cli("status")["claimReady"])
    api.ready = True
    wait_for(lambda: cli("status")["claimReady"])
    assert cli("status")["sessionId"] == before["sessionId"]
    assert cli("status")["activeCount"] == 0 and cli("status")["capacity"] == 1


def test_second_install_root_cannot_claim_in_same_login_session(installation):
    root, api, cli = installation
    api.ready = True
    cli("start")
    wait_for(lambda: cli("status")["claimReady"])
    other = root.parent / "Other install"
    venv.EnvBuilder(symlinks=True).create(other / "program/runtime")
    (other / "state").mkdir()
    (other / "state/settings.json").write_bytes((root / "state/settings.json").read_bytes())
    (other / "program/release.json").write_bytes((root / "program/release.json").read_bytes())
    old_site = next((root / "program/runtime/lib").glob("python*/site-packages"))
    new_site = next((other / "program/runtime/lib").glob("python*/site-packages"))
    (new_site / "worker.pth").write_bytes((old_site / "worker.pth").read_bytes())
    env = {"HOME": str(root.parent / "home"), "PATH": str(root.parent / "native") + ":/usr/bin:/bin"}
    run = subprocess.run([other / "program/runtime/bin/python3.11", "-IB", "-m", "sau_worker.desktop", "start"],
                         env=env, cwd=other, text=True, capture_output=True, timeout=6)
    assert run.returncode != 0 and "another installation" in run.stderr
    assert len({r["sessionId"] for r in api.reports}) == 1 and cli("status")["claimReady"]


def test_draining_worker_keeps_original_lease_until_its_cli_finishes(installation):
    root, api, cli = installation
    api.leased = api.ready = api.pending = True
    cli("start")
    wait_for(lambda: (root / "calls").exists())
    stop = cli("stop", wait=False)
    try:
        wait_for(lambda: api.reports[-1]["freeSlots"] == 0)
        count = len(api.leases)
        wait_for(lambda: len(api.leases) >= count + 2)
        grant = {"workflowId": "occ", "sessionId": api.claims[0], "leaseGrantId": "fixture-grant"}
        assert all(path == "/publish-task/profile-lease/renew" and body == grant for path, body in api.leases)
        (root / "finish").touch()
        wait_for(lambda: api.results)
        assert api.leases[-1] == ("/publish-task/profile-lease/complete", grant) and stop.poll() is None
    finally:
        (root / "finish").touch()
        api.ack.set()
        stop.wait(timeout=8)
