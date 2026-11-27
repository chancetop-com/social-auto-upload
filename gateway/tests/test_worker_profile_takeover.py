"""Two local worker sessions, real PostgreSQL and HTTP, controlled browser commands."""
import asyncio
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sys
import threading

import httpx
import pytest

from sau_worker.worker import Settings, Worker
from test_desktop_publish import live_gateway
from test_profile_leases import enqueue_video
from test_publish_api import DESKTOP, INTERNAL, postiz


@contextmanager
def provider_api(refuse):
    opened = []
    windows = set()

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            status = 200
            if self.path == '/browser/list':
                data = {'list': [{'id': 'shared', 'name': 'Fixture'}]}
            elif self.path == '/browser/pids/alive':
                assert body == {'ids': ['shared']}
                data = ['shared'] if windows else []
            elif self.path == '/open':
                opened.append(body['desktop'])
                status = 429 if refuse and windows else 200
                if status == 200:
                    windows.add(body['desktop'])
                data = {}
            elif self.path == '/close':
                windows.discard(body['desktop'])
                data = {}
            else:
                raise ValueError(self.path)
            self.send_response(status)
            self.end_headers()
            self.wfile.write(json.dumps({'success': status == 200, 'data': data}).encode())

        def log_message(self, *_):
            pass

    with ThreadingHTTPServer(('127.0.0.1', 0), Handler) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield f'http://127.0.0.1:{server.server_port}', opened
        finally:
            server.shutdown()
            thread.join()


async def wait_for_file(path):
    async with asyncio.timeout(30):
        while not path.exists():
            await asyncio.sleep(.025)


def paired_cli(root):
    script = root / 'fixture_cli.py'
    script.write_text("""
import json, os, sys, time, urllib.error, urllib.request
from datetime import datetime
from pathlib import Path
desktop = sys.argv[1]
if sys.argv[2:] == ['--version']:
    print('sau 0.1.0')
    sys.exit()
assert sys.argv[2:4] == ['tiktok', 'upload-video']
base = os.environ['BITBROWSER_API_BASE']
def call(path):
    req = urllib.request.Request(base + path, data=json.dumps({'desktop': desktop}).encode())
    with urllib.request.urlopen(req, timeout=2) as response:
        return response.status
try:
    call('/open')
    refused = False
except urllib.error.HTTPError as exc:
    assert exc.code == 429
    refused = True
root = Path(__file__).parent
(root / (desktop + '.waiting')).touch()
deadline = time.monotonic() + 90
not_before = next((arg.split('=', 1)[1] for arg in sys.argv if arg.startswith('--not-before=')), None)
if desktop == 'A':
    assert not_before
target = datetime.fromisoformat(not_before.replace('Z', '+00:00')).timestamp() if not_before else 0
while time.time() < target or not (root / (desktop + '.finish')).exists():
    assert time.monotonic() < deadline
    time.sleep(.025)
if refused:
    sys.exit(11)
call('/close')
print('TikTok video upload submitted: fixture.mp4')
""")
    return script


class MobileNetwork(httpx.AsyncHTTPTransport):
    offline = False

    def __init__(self):
        super().__init__()
        self.renewed = asyncio.Event()

    async def handle_async_request(self, request):
        # FBR dev publishes only these two path prefixes for desktop traffic.
        if (request.headers.get("Authorization") == DESKTOP["Authorization"]
                and request.url.path.split("/")[1] not in ("session", "publish-task")):
            return httpx.Response(404, request=request)
        if self.offline and request.url.path == '/publish-task/profile-lease/renew':
            raise httpx.ConnectError('fixture disconnect', request=request)
        response = await super().handle_async_request(request)
        if request.url.path == '/publish-task/profile-lease/renew' and response.is_success:
            self.renewed.set()
        return response


@pytest.mark.asyncio
@pytest.mark.parametrize('refuse', [False, True], ids=['provider-opens', 'provider-refuses'])
async def test_worker_renews_while_waiting_then_only_next_merchant_transfers(postiz, gateway_env, tmp_path, monkeypatch, refuse):
    monkeypatch.setenv('GATEWAY_PROFILE_RENEW_SECONDS', '1')
    monkeypatch.setenv('GATEWAY_PROFILE_LEASE_SECONDS', '8')
    script = paired_cli(tmp_path)
    with provider_api(refuse) as (provider, opened), live_gateway() as url, httpx.Client(
        base_url=url, headers=INTERNAL, trust_env=False, timeout=30
    ) as api:
        network = MobileNetwork()
        async with httpx.AsyncClient(transport=network) as client_a, httpx.AsyncClient(trust_env=False) as client_b:
            settings = Settings.from_env({'SAU_GATEWAY_URL': url, 'SAU_DESKTOP_TOKEN': 'fixture-desktop',
                                          'BITBROWSER_API_KEY': 'fixture', 'BITBROWSER_API_BASE': provider})
            a = Worker(replace(settings, cli=(sys.executable, str(script), 'A')), client_a)
            b = Worker(replace(settings, cli=(sys.executable, str(script), 'B')), client_b)
            await asyncio.gather(a.report(), b.report())
            earliest = (datetime.now(timezone.utc) + timedelta(seconds=12)).strftime('%Y-%m-%dT%H:%M:%SZ')
            original = await asyncio.to_thread(enqueue_video, api, 'merchant-A', earliest=earliest)
            postiz[1]['task'] = original
            first = await a.claim(0)
            job_a = asyncio.create_task(a.finish(first))
            job_b = None
            try:
                await wait_for_file(tmp_path / 'A.waiting')
                network.renewed.clear()
                following = await asyncio.to_thread(enqueue_video, api, 'merchant-B')
                await asyncio.wait_for(network.renewed.wait(), timeout=12)
                # This exceeds the initial validity. The child is still waiting for a scheduled click.
                initial_expiry = datetime.fromisoformat(first['leaseExpiresAt'].replace('Z', '+00:00'))
                await asyncio.sleep(max(0, (initial_expiry - datetime.now(timezone.utc)).total_seconds()) + .1)
                assert await b.claim(0) is None
                network.offline = True
                async with asyncio.timeout(25):
                    while not (second := await b.claim(0)):
                        await asyncio.sleep(.05)
                assert second['workflowId'] == following['workflowId']
                assert second['leaseGrantId'] != first['leaseGrantId']
                postiz[1]['task'] = following
                job_b = asyncio.create_task(b.finish(second))
                await wait_for_file(tmp_path / 'B.waiting')
                late = {k: first[k] for k in ('sessionId', 'workflowId', 'leaseGrantId')}
                for method in ('renew', 'complete', 'release'):
                    event = {**late, 'windowClosed': True} if method == 'release' else late
                    stale = await asyncio.to_thread(api.post, '/publish-task/profile-lease/' + method, json=event, headers=DESKTOP)
                    assert stale.status_code == 409
                (tmp_path / 'A.finish').touch()
                old_result = await job_a
                assert old_result['state'] == 'succeeded'
                assert old_result['sessionId'] == a.session_id
                assert first['resultDeadlineAt']
                assert old_result['resultDeadlineAt'] == first['resultDeadlineAt']
                assert await a.claim(0) is None
                (tmp_path / 'B.finish').touch()
                result = await job_b
                assert result['state'] == ('failed' if refuse else 'succeeded')
                assert result['receipt']['exitCode'] == (11 if refuse else 0)
                await asyncio.to_thread(enqueue_video, api, 'merchant-C')
                assert (await a.claim(0))['workflowId'] == 'merchant-C'
                assert opened == ['A', 'B']
                print(f"{refuse=} A={a.session_id}/{first['workflowId']}/{first['leaseGrantId']} "
                      f"B={b.session_id}/{second['workflowId']}/{second['leaseGrantId']} commands={len(opened)}")
            finally:
                for name in ('A.finish', 'B.finish'):
                    (tmp_path / name).touch()
                await asyncio.gather(*(j for j in (job_a, job_b) if j is not None), return_exceptions=True)
