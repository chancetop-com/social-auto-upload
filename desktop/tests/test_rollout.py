import hashlib
import io
import json
from pathlib import Path
import stat
import subprocess
import zipfile

import pytest


def test_staging_authenticates_bytes_and_probes_complete_pair_before_switch(tmp_path):
    from sau_worker.rollout import DownloadError, PackageDefect, stage
    image = io.BytesIO()
    with zipfile.ZipFile(image, 'w') as archive:
        for name, data in [('release.json', b'{}'), ('runtime/bin/python3.11', b'fixture')]:
            member = zipfile.ZipInfo(name)
            member.external_attr = (stat.S_IFREG | 0o755) << 16
            archive.writestr(member, data)
    body = image.getvalue()
    assignment = dict(releaseId='r', batchId='b', target='macos-arm64', revision='a'*40,
                      sha256=hashlib.sha256(body).hexdigest())
    (tmp_path / 'program').mkdir()
    def incomplete(p, a):
        assert p.is_relative_to(tmp_path / '.versions') and a == assignment
        assert (p / 'runtime/bin/python3.11').read_bytes() == b'fixture'
        raise PackageDefect('paired CLI failed')
    with pytest.raises(DownloadError):
        stage(tmp_path, assignment, [body[:-1]], incomplete)
    assert not (tmp_path / '.versions/switch').exists()
    with pytest.raises(PackageDefect):
        stage(tmp_path, assignment, [body], incomplete)
    assert not (tmp_path / '.versions/switch').exists()
    stage(tmp_path, assignment, [body], lambda path, a: None)
    assert (tmp_path / '.versions/next/package.sha256').read_text() == assignment['sha256']
    assert (tmp_path / '.versions/switch').exists()
    assert list((tmp_path / 'program').iterdir()) == []


@pytest.mark.parametrize('step', ['staged', 'old-moved', 'committed'])
@pytest.mark.parametrize('windows', [False, True])
def test_login_host_resumes_each_interrupted_rename(tmp_path, step, windows):
    import os
    from sau_worker.host import write_host
    root = tmp_path / 'operator root'
    versions = root / '.versions'
    state = root / 'state'
    versions.mkdir(parents=True)
    state.mkdir()
    new, old = versions / 'next', root / 'program'
    new.mkdir()
    old.mkdir()
    (old / 'package.sha256').write_text('a'*64)
    (new / 'package.sha256').write_text('b'*64)
    (versions / 'switch').write_text('b'*64)
    if step in ('old-moved', 'committed'):
        old.rename(versions / 'previous')
    if step == 'committed':
        new.rename(old)
    path = write_host(root, windows=windows)
    pwsh = os.environ.get('SAU_TEST_PWSH')
    if windows and not pwsh:
        pytest.skip('PowerShell required')
    run = [pwsh, '-NoProfile', '-NonInteractive', '-File', path] if windows else ['/bin/sh', path]
    # Exercise the same native recovery used at login without starting a worker.
    subprocess.run([*run, 'recover'], check=True, env={**os.environ, 'HOME': str(tmp_path)})
    assert (old / 'package.sha256').read_text() == 'b'*64
    assert (versions / 'previous/package.sha256').read_text() == 'a'*64
    (versions / 'rollback').touch()
    subprocess.run([*run, 'recover'], check=True, env={**os.environ, 'HOME': str(tmp_path)})
    assert (old / 'package.sha256').read_text() == 'a'*64


def test_observation_reads_current_image_and_keeps_machine_id_across_sessions(tmp_path):
    from sau_worker.rollout import installation
    state = tmp_path / "state"
    state.mkdir()
    program = tmp_path / "program"
    program.mkdir()
    (program / "release.json").write_text(json.dumps(dict(revision="a"*40, target="macos-arm64")))
    (program / "package.sha256").write_text("c"*64)
    before = installation(tmp_path)
    assert len(before["machineId"]) == 36
    assert before["sha256"] == "c"*64 and before["revision"] == "a"*40
    (state / 'upgrade.json').write_text(json.dumps(dict(batchId="batch", revision="b"*40, sha256="e"*64,
                                                      target="macos-arm64", step="validating")))
    assert installation(tmp_path) == before
    (program / "release.json").write_text(json.dumps(dict(revision="b"*40, target="macos-arm64")))
    (program / "package.sha256").write_text("e"*64)
    assert installation(tmp_path) == {**before, "batchId":"batch", "revision":"b"*40, "sha256":"e"*64}


def test_grant_drains_before_packaging_and_invalid_digest_cannot_switch(tmp_path):
    import httpx
    from sau_worker.rollout import ReleaseAgent
    (tmp_path / 'state').mkdir()
    program = tmp_path / 'program'
    program.mkdir()
    (program / 'release.json').write_text(json.dumps({'revision':'a'*40,'target':'macos-arm64'}))
    (program / 'package.sha256').write_text('b'*64)
    batch = dict(batchId='35bdd7f9-ca24-4c4b-a90e-334be9d69027',releaseId='84e3d341-a494-4dc8-9030-48b061c27ebc',
                 revision='c'*40, target='macos-arm64', sha256='e'*64, url='/session/release/packages/'+'e'*64)
    phases = []
    def send(request):
        assert request.headers['authorization'] == 'Bearer fixture'
        if request.url.path.endswith('/discover'):
            return httpx.Response(200, json={'assignment':batch,'approved':None})
        if request.method == 'GET':
            return httpx.Response(200, content=b'truncated')
        phases.append(json.loads(request.content)['phase'])
        return httpx.Response(200, json={'active':True,'confirmed':False})
    client = httpx.Client(base_url='https://fixture.test', transport=httpx.MockTransport(send))
    agent = ReleaseAgent(tmp_path, client, 'fixture')
    agent.discover()
    assert agent.needs_drain() and phases == ['draining']
    assert not agent.after_drain()
    assert phases == ['draining','draining','staging']
    assert not (tmp_path / '.versions/switch').exists()
    assert (program / 'package.sha256').read_text() == 'b'*64


def test_worker_waits_for_batch_bound_gateway_check_receipt(tmp_path, monkeypatch):
    import asyncio
    from uuid import uuid4
    import httpx
    from sau_worker.worker import Settings, Worker
    (tmp_path / 'program').mkdir()
    (tmp_path / 'state').mkdir()
    batch = dict(revision="d"*40,target="macos-arm64",sha256="c"*64,batchId=str(uuid4()),releaseId=str(uuid4()),step="validating")
    (tmp_path / 'program/release.json').write_text(json.dumps(batch))
    (tmp_path / 'program/package.sha256').write_text(batch["sha256"])
    (tmp_path / 'state/upgrade.json').write_text(json.dumps(batch))
    monkeypatch.setenv("SAU_INSTALL_ROOT", str(tmp_path))
    monkeypatch.setenv("SAU_RELEASE_CHECK_PROVIDER", "local-chrome")
    monkeypatch.setenv("SAU_RELEASE_CHECK_PROFILE", "fixture")
    monkeypatch.setenv("SAU_RELEASE_CHECK_PLATFORM", "tiktok")
    seen = []
    async def post(request):
        body = json.loads(request.content)
        seen.append((request.url.path, body))
        return httpx.Response(200, json={"confirmed":False,"active":True})
    async def check(self, provider, profile, platform):
        await self.report(discover=False)
        assert (provider,profile,platform) == ("local-chrome","fixture","tiktok")
        return {"state":"succeeded","workflowId":"check.test"}
    monkeypatch.setattr(Worker, "check", check)
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(post)) as client:
            worker = Worker(Settings.from_env({"SAU_DESKTOP_TOKEN":"test"}), client)
            worker.cli_release = '0.1.0'
            await worker.report(discover=False)
            assert seen[-1][1]['installation']['batchId'] == batch['batchId']
            assert worker.free_slots == 0
            assert await worker.validate_release()
            receipt = json.loads((tmp_path/'state/release-check-result.json').read_text())
            assert receipt == dict(batchId=batch["batchId"],sessionId=worker.session_id,checkWorkflowId="check.test")
            assert seen[-1][1]['mode'] == 'self-check'
            assert seen[-1][1]['sessionId'] != worker.session_id
            assert seen[-1][1]['installation'] == seen[0][1]['installation']
    asyncio.run(scenario())


@pytest.mark.parametrize('windows',[False,True])
def test_approved_bootstrap_rejects_cross_origin_package_before_execution(tmp_path, windows):
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from threading import Thread
    import os, platform
    from uuid import uuid4
    from desktop.tests.test_bootstrap import DESKTOP
    requests = []
    class Peer(BaseHTTPRequestHandler):
        def log_message(self,*args): pass
        def do_POST(self):
            request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            requests.append((self.path, self.headers['Authorization'], request))
            target = 'windows-x86_64' if windows else 'macos-' + platform.machine()
            body = json.dumps({'approved':dict(releaseId=str(uuid4()),revision='b'*40,
                        sha256='c'*64,target=target,url='https://untrusted.invalid/package'),'assignment':None}).encode()
            self.send_response(200)
            self.send_header('Content-Length',str(len(body)))
            self.end_headers()
            self.wfile.write(body)
    if windows and not os.environ.get("SAU_TEST_PWSH"):
        pytest.skip("PowerShell required")
    if not windows and platform.system() != 'Darwin':
        pytest.skip("macOS bootstrap required")
    root = tmp_path / "Worker root"
    args = ([os.environ["SAU_TEST_PWSH"],'-NoProfile','-File',DESKTOP/'bootstrap.ps1','-Approved','-InstallRoot',root]
            if windows else ['/bin/sh',DESKTOP/'bootstrap.sh','--approved',root])
    with ThreadingHTTPServer(('127.0.0.1',0),Peer) as peer:
        thread = Thread(target=peer.serve_forever,daemon=True)
        thread.start()
        env = {**os.environ,'HOME':str(tmp_path),'SAU_DESKTOP_TOKEN':'fixture',
               'SAU_GATEWAY_URL':f'http://127.0.0.1:{peer.server_port}',
               'LOCALAPPDATA':str(tmp_path),'PROCESSOR_ARCHITECTURE':'AMD64'}
        try:
            run = subprocess.run(args,env=env,text=True,capture_output=True,timeout=20)
        finally:
            peer.shutdown()
    assert run.returncode and 'package source' in run.stderr.lower()
    assert len(requests) == 1 and requests[0][0:2] == ('/session/release/discover','Bearer fixture')
    assert requests[0][2]['machineId'] == (root/'state/machine-id').read_text().strip()
    assert not (root/'program').exists()
