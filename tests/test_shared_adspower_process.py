"""Exercise installed CLI entries against a loopback provider and isolated Chromium."""
import json
import os
import shutil
import site
import ssl
import subprocess
import sys
import threading
import time
import venv
from contextlib import ExitStack, contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from patchright.sync_api import sync_playwright


SOURCE = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(sys.platform == 'win32', reason='POSIX console-script fixture')


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def respond(self, data, content_type):
        self.send_response(200)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)


@contextmanager
def serve(handler, tls=None):
    with ThreadingHTTPServer(('127.0.0.1', 0), handler) as server:
        if tls:
            server.socket = tls.wrap_socket(server.socket, server_side=True)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            yield server.server_port
        finally:
            server.shutdown()
            worker.join()


@pytest.fixture(scope='module')
def installations(tmp_path_factory):
    """Independent environments + code installations, sharing only third-party deps."""
    root = tmp_path_factory.mktemp('installations')
    entries = []
    for name in ('a', 'b'):
        prefix = root / name
        venv.EnvBuilder(with_pip=False).create(prefix)
        packages = next(prefix.glob('lib/python*/site-packages'))
        for directory in ('sau_commands', 'utils', 'uploader'):
            shutil.copytree(SOURCE / directory, packages / directory,
                            ignore=shutil.ignore_patterns('__pycache__', 'node_modules'))
        shutil.copyfile(SOURCE / 'sau_cli.py', packages / 'sau_cli.py')
        shutil.copyfile(SOURCE / 'conf.example.py', packages / 'conf.py')
        (packages / 'dependencies.pth').write_text('\n'.join(site.getsitepackages()) + '\n')
        entry = prefix / 'bin/sau'
        entry.write_text(f'#!{prefix}/bin/python\nfrom sau_cli import main\nraise SystemExit(main())\n')
        entry.chmod(0o700)
        entries.append(entry)
    return entries


class OfflineProfile:
    def __init__(self, root, stack, entries, playwright):
        self.root = root
        self.stack = stack
        self.entries = entries
        self.keys = []
        self.starts = []
        self.stops = []
        self.active = False
        self.pages_requested = []
        self.gates = {name: threading.Event() for name in ('instagram', 'tiktok')}
        self.arrived = {name: threading.Event() for name in self.gates}
        profile = self

        class Site(Handler):
            def do_GET(self):
                platform = self.headers['Host'].split('.')[1]
                if self.path == '/gate.js':
                    profile.arrived[platform].set()
                    profile.gates[platform].wait(25)
                    self.respond(b'', 'application/javascript')
                elif self.path == '/favicon.ico':
                    self.respond(b'', 'image/x-icon')
                else:
                    profile.pages_requested.append(platform)
                    self.respond(b'<textarea>draft</textarea><a href="/direct/inbox/">Inbox</a>'
                                 b'<button data-e2e="select_video_button">Select video</button>'
                                 b'<script defer src="/gate.js"></script>', 'text/html')

        cert, key = root / 'cert.pem', root / 'key.pem'
        subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '1',
                        '-subj', '/CN=offline.invalid', '-keyout', key, '-out', cert],
                       capture_output=True, check=True)
        tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        tls.load_cert_chain(cert, key)
        site_port = stack.enter_context(serve(Site, tls))
        user_data = root / 'chromium'
        rules = ', '.join([f'MAP www.{name}.com 127.0.0.1:{site_port}' for name in self.gates]
                          + ['MAP * ~NOTFOUND'])
        self.chrome = subprocess.Popen([
            playwright.chromium.executable_path, '--headless', '--remote-debugging-port=0',
            f'--user-data-dir={user_data}', '--no-first-run', '--disable-background-networking',
            '--no-proxy-server', '--ignore-certificate-errors', f'--host-resolver-rules={rules}',
            'about:blank'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        stack.callback(self.close_browser)
        deadline = time.monotonic() + 15
        while not (user_data / 'DevToolsActivePort').exists():
            if self.chrome.poll() is not None or time.monotonic() >= deadline:
                pytest.fail('Isolated Chromium did not start')
            time.sleep(.02)
        port, path = (user_data / 'DevToolsActivePort').read_text().splitlines()
        self.endpoint = f'ws://127.0.0.1:{port}{path}'
        self.reported_endpoint = self.endpoint
        self.browser = playwright.chromium.connect_over_cdp(self.endpoint, no_defaults=True)

        class Provider(Handler):
            def do_GET(self):
                profile.keys.append(self.headers['Authorization'])
                if self.path == '/status':
                    data = {}
                else:
                    url = urlsplit(self.path)
                    assert url.path == '/api/v2/browser-profile/active'
                    profile_id, = parse_qs(url.query)['profile_id']
                    data = {'profile_id': profile_id, 'status': 'Active' if profile.active else 'Inactive',
                            'ws': {'puppeteer': profile.reported_endpoint}}
                self.respond(json.dumps({'code': 0, 'data': data}).encode(), 'application/json')

            def do_POST(self):
                profile.keys.append(self.headers['Authorization'])
                body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                if self.path.endswith('/start'):
                    profile.starts.append(body['profile_id'])
                    profile.active = True
                else:
                    assert self.path.endswith('/stop')
                    profile.stops.append(body['profile_id'])
                    profile.close_browser()
                    profile.active = False
                self.respond(json.dumps({'code': 0, 'data': {'ws': {'puppeteer': profile.endpoint}}}).encode(),
                             'application/json')

        self.api_port = stack.enter_context(serve(Provider))
        self.home = root / 'home'
        self.home.mkdir()

    def close_browser(self):
        if self.chrome.poll() is None:
            self.chrome.terminate()
            self.chrome.wait(timeout=10)

    def command(self, installation, platform, *flags, host='127.0.0.1', profile_id='shared'):
        work = self.root / f'cwd-{installation}'
        work.mkdir(exist_ok=True)
        env = {**os.environ, 'HOME': str(self.home), 'ADSPOWER_API_KEY': f'offline-key-{installation}',
               'ADSPOWER_API_BASE': f'http://{host}:{self.api_port}/', 'MLX_API_TOKEN': '',
               'PYTHONPATH': '', 'PYTHONNOUSERSITE': '1', 'NO_PROXY': 'localhost,127.0.0.1'}
        child = subprocess.Popen([self.entries[installation], platform, 'check', '--profile-id', profile_id,
                                  *flags], env=env, cwd=work, text=True, stdout=subprocess.PIPE,
                                 stderr=subprocess.STDOUT)
        self.stack.callback(self.reap, child)
        return child

    @staticmethod
    def reap(child):
        if child.poll() is None:
            child.kill()
        child.communicate(timeout=10)

    def entered(self, platform, child):
        deadline = time.monotonic() + 12
        while not self.arrived[platform].wait(.05):
            if child.poll() is not None:
                pytest.fail(child.communicate()[0])
            if time.monotonic() > deadline:
                pytest.fail(f'{platform} did not reach its offline page')

    def finish(self, platform, child):
        self.gates[platform].set()
        output = child.communicate(timeout=12)[0]
        assert (child.returncode, 'valid' in output.splitlines()) == (0, True), output
        assert 'offline-key-' not in output and self.endpoint not in output
        return output


@pytest.fixture
def profile(tmp_path, installations):
    with ExitStack() as stack:
        playwright = stack.enter_context(sync_playwright())
        yield OfflineProfile(tmp_path, stack, installations, playwright)


def test_checks_share_cold_profile_until_both_leave(profile):
    first = profile.command(0, 'instagram')
    profile.entered('instagram', first)
    second = profile.command(1, 'tiktok', host='LOCALHOST')
    profile.entered('tiktok', second)
    assert profile.starts == ['shared']
    profile.finish('instagram', first)
    assert profile.stops == []
    # Sync Playwright only dispatches incoming page events during a protocol turn.
    inspector = profile.browser.new_browser_cdp_session()
    inspector.send("Target.getTargets")
    inspector.detach()
    pages = profile.browser.contexts[0].pages
    assert not any('instagram.com' in page.url for page in pages)
    assert any('tiktok.com' in page.url for page in pages), [page.url for page in pages]
    peer, = [page for page in pages if 'tiktok.com' in page.url]
    peer.locator('textarea').fill('peer still editable')
    assert peer.locator('textarea').input_value() == 'peer still editable'
    profile.finish('tiktok', second)
    assert profile.stops == ['shared'] and not profile.active
    assert set(profile.keys) == {'Bearer offline-key-0', 'Bearer offline-key-1'}
