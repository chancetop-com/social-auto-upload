"""Installed Gateway, installed worker and CLI, PostgreSQL, offline Local API and platform page."""
import json
import os
from pathlib import Path
import socket
import ssl
import subprocess
import sys
import time
import venv

import httpx
import pytest

if sys.platform == "win32" or os.environ.get("SAU_TEST_PAIRED_CHECK") != "1":
    pytest.skip("set SAU_TEST_PAIRED_CHECK=1 to run the installed desktop/browser fixture", allow_module_level=True)

from tests.cli_distribution import install_cli
from tests.test_bitbrowser_platform_checks import KEY, WINDOW_ID, browser_harness, harness
from tests.test_shared_adspower_process import installations


ROOT = Path(__file__).resolve().parents[2]


def install_service(name, python, destination):
    subprocess.run(["uv", "build", "--wheel", "--out-dir", destination, ROOT / name], check=True,
                   stdout=subprocess.DEVNULL)
    wheel, = destination.glob("*.whl")
    subprocess.run(["uv", "pip", "install", "--no-deps", "--python", python, wheel], check=True)


@pytest.fixture(scope="module")
def installed_services(tmp_path_factory, installations):
    build = tmp_path_factory.mktemp("independent-packages")
    private_bin = installations[0].parent
    install_service("cli-service", private_bin / "python", build / "worker-wheel")
    cloud = build / "Gateway installation"
    venv.EnvBuilder(with_pip=False).create(cloud)
    cloud_python = cloud / "bin/python"
    cloud_packages = Path(subprocess.check_output(
        [cloud_python, "-I", "-c", "import sysconfig; print(sysconfig.get_path('purelib'))"], text=True).strip())
    dependencies = [p for p in sys.path if Path(p).name in {"site-packages", "dist-packages"}]
    (cloud_packages / "fixture_dependencies.pth").write_text("\n".join(dependencies) + "\n")
    install_service("gateway", cloud_python, build / "gateway-wheel")
    artifact = os.environ.get("SAU_TEST_DESKTOP_ARTIFACT")
    if artifact:
        from desktop_fixture import bootstrapped_worker
        with bootstrapped_worker(ROOT, build, Path(artifact)) as launcher:
            yield launcher, cloud_python
    else:
        yield private_bin / "cli-service", cloud_python


@pytest.fixture
def installed_gateway(gateway_env, installed_services, tmp_path):
    _, python = installed_services
    cert, key = tmp_path / "fixture.pem", tmp_path / "fixture-key.pem"
    subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
                    "-subj", "/CN=localhost", "-addext", "subjectAltName=IP:127.0.0.1",
                    "-keyout", key, "-out", cert], check=True, capture_output=True)
    env = {k: os.environ[k] for k in ("PATH", "GATEWAY_INTERNAL_TOKEN", "GATEWAY_DESKTOP_TOKEN", "GATEWAY_DATABASE_URL")}
    subprocess.run([python.parent / "social-media-web-api", "migrate"], env=env, cwd=tmp_path, check=True)
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        url = "https://127.0.0.1:" + str(sock.getsockname()[1])
        proc = subprocess.Popen([python, "-I", "-m", "uvicorn", "sau_gateway.app:create_app", "--factory",
                                 "--fd", str(sock.fileno()), "--ssl-keyfile", key, "--ssl-certfile", cert],
                                env=env, cwd=tmp_path, pass_fds=(sock.fileno(),))
        try:
            with httpx.Client(base_url=url, verify=ssl.create_default_context(cafile=cert), trust_env=False,
                              headers={"Authorization": "Bearer fixture-internal"}) as client:
                deadline = time.monotonic() + 10
                while True:
                    try:
                        if client.get("/health-check").json()["status"] == "ready":
                            break
                    except httpx.TransportError:
                        pass
                    assert proc.poll() is None and time.monotonic() < deadline
                    time.sleep(0.05)
                yield url, cert, client
        finally:
            proc.terminate()
            proc.wait(timeout=10)


@pytest.mark.parametrize(("outcome", "state", "login"), [
    ("valid", "succeeded", "valid"), ("login", "failed", "login-required"), ("missing", "failed", "unknown"),
    ("offline", "failed", "unknown")])
def test_installed_self_check_reports_only_offline_login_evidence(
        installed_gateway, installed_services, harness, tmp_path, outcome, state, login):
    url, cert, client = installed_gateway
    worker, _ = installed_services
    profile_id = WINDOW_ID if outcome != "missing" else "absent"
    harness.site.outcome["tiktok"] = outcome
    harness.api.queue("/browser/list", status=503 if outcome == "offline" else 200, payload={"success": True, "data": {"list": [{"id": WINDOW_ID, "name": "Shop"}]}})
    env = {"PATH": os.environ["PATH"], "HOME": str(harness.profile.home), "OFFLINE_OS_PROFILE": str(harness.profile.home),
           "SAU_HOME": str(tmp_path / "private CLI data"), "SAU_GATEWAY_URL": url, "SAU_GATEWAY_CA_FILE": str(cert),
           "SAU_DESKTOP_TOKEN": "fixture-desktop", "BITBROWSER_API_BASE": f"http://127.0.0.1:{harness.api_port}",
           "BITBROWSER_API_KEY": KEY}
    result = subprocess.run([worker, "check", "--provider", "bitbrowser", "--platform", "tiktok", "--profile-id", profile_id],
                            cwd=tmp_path, env=env, capture_output=True, text=True, timeout=45)
    assert result.returncode == (0 if state == "succeeded" else 1), (result.stdout, result.stderr)
    if outcome == "offline":
        assert "Provider unavailable: bitbrowser" in result.stderr
    record = json.loads(result.stdout)
    assert KEY not in result.stdout
    assert record["task"]["action"] == "check"
    assert record["state"] == state
    receipt = record["receipt"]
    assert receipt["cloudConnected"]
    assert receipt["profileVisible"] == receipt["cliInvoked"] == (outcome not in ("missing", "offline"))
    assert receipt["platformLogin"] == login
    assert client.get("/internal/occurrences/" + record["workflowId"]).json() == record
    report = client.get("/internal/sessions/" + record["sessionId"]).json()
    assert report["release"] == report["cliRelease"] == "0.1.0"
    expected = 3 if os.environ.get("SAU_TEST_DESKTOP_ARTIFACT") else 1
    assert (report["capacity"], report["freeSlots"]) == (expected, expected)
    assert {"platform": "tiktok", "action": "check"} in report["capabilities"]
    assert harness.site.documents == ([] if outcome in ("missing", "offline") else [("tiktok", "/tiktokstudio/upload")])
