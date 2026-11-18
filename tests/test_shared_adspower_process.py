"""Exercise installed CLI entries against a loopback provider and isolated Chromium."""
import json
import os
import re
import shutil
import site
import ssl
import stat
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
    def __init__(self, root, stack, entries, playwright, *, sites=None):
        self.root = root
        self.stack = stack
        self.entries = entries
        self.playwright = playwright
        self.keys = []
        self.starts = []
        self.stops = []
        self.active = False
        self.observation_fields = {}
        self.profiles = {}
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
        ports = {f'www.{name}.com': site_port for name in self.gates}
        for hostname, handler in (sites or {}).items():
            ports[hostname] = stack.enter_context(serve(handler, tls))
        rules = ', '.join([f'MAP {host} 127.0.0.1:{port}' for host, port in ports.items()]
                          + ['MAP * ~NOTFOUND'])
        # Offline browsers share only their test profile. Keep credentials out of the OS keychain.
        keychain_flags = ['--use-mock-keychain'] if sys.platform == 'darwin' else []
        self.chrome = subprocess.Popen([
            playwright.chromium.executable_path, '--headless', '--remote-debugging-port=0',
            f'--user-data-dir={user_data}', '--no-first-run', '--disable-background-networking',
            '--password-store=basic', *keychain_flags,
            '--no-proxy-server', '--ignore-certificate-errors', f'--host-resolver-rules={rules}',
            'about:blank'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        stack.callback(self.close_browser)
        port_file = user_data / 'DevToolsActivePort'
        deadline = time.monotonic() + 15
        while True:
            exit_code = self.chrome.poll()
            if exit_code is not None:
                pytest.fail(f'Isolated Chromium exited with code {exit_code} before CDP was ready')
            try:
                content = port_file.read_text(encoding='ascii')
            except FileNotFoundError:
                content = ''
            # Chromium creates the file before the port and full browser UUID are visible.
            ready = re.fullmatch(r'([1-9][0-9]{0,4})\n(/devtools/browser/[0-9a-fA-F-]{36})\n?', content)
            if ready and int(ready[1]) <= 65535:
                port, path = ready.groups()
                break
            if time.monotonic() >= deadline:
                pytest.fail(f'Chromium CDP endpoint incomplete after 15s ({len(content)} characters read)')
            time.sleep(.02)
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
                    target = profile.profiles.get(profile_id, profile)
                    data = {'status': 'Active' if target.active else 'Inactive',
                            'ws': {'puppeteer': target.reported_endpoint}, **target.observation_fields}
                self.respond(json.dumps({'code': 0, 'data': data}).encode(), 'application/json')

            def do_POST(self):
                profile.keys.append(self.headers['Authorization'])
                body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                target = profile.profiles.get(body['profile_id'], profile)
                if self.path.endswith('/start'):
                    target.starts.append(body['profile_id'])
                    target.active = True
                else:
                    assert self.path.endswith('/stop')
                    target.stops.append(body['profile_id'])
                    target.close_browser()
                    target.active = False
                self.respond(json.dumps({'code': 0, 'data': {'ws': {'puppeteer': target.endpoint}}}).encode(),
                             'application/json')

        self.api_port = stack.enter_context(serve(Provider))
        self.home = root / 'home'
        self.home.mkdir()

    def close_browser(self):
        if self.chrome.poll() is None:
            self.chrome.terminate()
            self.chrome.wait(timeout=10)

    def command(self, installation, platform, *flags, host='127.0.0.1', profile_id='shared',
                action='check', env=None):
        work = self.root / f'cwd-{installation}'
        work.mkdir(exist_ok=True)
        command_env = {**os.environ, 'HOME': str(self.home), 'ADSPOWER_API_KEY': f'offline-key-{installation}',
               'ADSPOWER_API_BASE': f'http://{host}:{self.api_port}/', 'MLX_API_TOKEN': '',
               'PYTHONPATH': '', 'PYTHONNOUSERSITE': '1', 'NO_PROXY': 'localhost,127.0.0.1',
               **(env or {})}
        child = subprocess.Popen([self.entries[installation], platform, action, '--profile-id', profile_id,
                                  *flags], env=command_env, cwd=work, text=True, stdout=subprocess.PIPE,
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
        assert 'offline-key-' not in output and urlsplit(self.endpoint).netloc not in output
        return output


@pytest.fixture
def profile(tmp_path, installations):
    with ExitStack() as stack:
        playwright = stack.enter_context(sync_playwright())
        yield OfflineProfile(tmp_path, stack, installations, playwright)


@pytest.mark.parametrize('desktop', [False, True], ids=['cold', 'already-open'])
def test_checks_share_profile_until_both_leave(profile, desktop):
    if desktop:
        profile.active = True
        marked = profile.browser.contexts[0].pages[0]
        marked.set_content('<textarea>desktop draft</textarea>')
    first = profile.command(0, 'instagram')
    profile.entered('instagram', first)
    second = profile.command(1, 'tiktok', host='LOCALHOST')
    profile.entered('tiktok', second)
    assert profile.starts == ([] if desktop else ['shared'])
    profile.finish('instagram', first)
    assert profile.stops == []
    if desktop:
        assert marked.locator('textarea').input_value() == 'desktop draft'
        marked.locator('textarea').fill('desktop still editable')
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


def test_simultaneous_checks_have_one_winner_per_platform(profile):
    children = [profile.command(i, 'instagram', '--account', f'alias-{i}') for i in (0, 1)]
    assert profile.arrived['instagram'].wait(12)
    deadline = time.monotonic() + 5
    while all(child.poll() is None for child in children) and time.monotonic() < deadline:
        time.sleep(.02)
    winner, = [child for child in children if child.poll() is None]
    loser, = [child for child in children if child.poll() is not None]
    output = loser.communicate()[0]
    assert loser.returncode == 1 and 'instagram' in output and '占用' in output
    assert profile.starts == ['shared'] and profile.stops == []
    assert profile.pages_requested == ['instagram']
    profile.finish('instagram', winner)
    assert profile.stops == ['shared']


def test_failed_join_leaves_the_peer_and_private_record_intact(profile):
    first = profile.command(0, 'instagram', '--headed')
    profile.entered('instagram', first)
    records = [p for p in profile.home.rglob('*.json') if p.is_file()]
    assert len(records) == 1
    record, = records
    for path in (record, record.parent, record.parent.parent):
        assert path.stat().st_uid == os.getuid()
        assert stat.S_IMODE(path.stat().st_mode) == (0o600 if path.is_file() else 0o700)
    original = record.read_bytes()
    assert b'offline-key-' not in original and b'ws://' not in original
    assert profile.endpoint.encode() not in original

    def rejected(*flags, host='127.0.0.1'):
        child = profile.command(1, 'tiktok', *flags, host=host)
        output = child.communicate(timeout=8)[0]
        assert child.returncode == 1, output
        assert 'offline-key-' not in output and urlsplit(profile.endpoint).netloc not in output
        assert record.read_bytes() == original
        assert first.poll() is None
        assert profile.pages_requested == ['instagram'] and not profile.stops
        return output

    assert 'headless' in rejected('--headless')
    assert '服务' in rejected(host='127.0.0.2')
    profile.observation_fields['profile_id'] = 'wrong-profile'
    assert 'observe' in rejected()
    profile.observation_fields.clear()
    profile.reported_endpoint = ''
    assert 'observe' in rejected()
    profile.reported_endpoint = profile.endpoint + '?cred=offline-key-untrusted'
    assert '连接' in rejected()
    profile.reported_endpoint = profile.endpoint
    record.chmod(0o644)
    try:
        assert '访问' in rejected()
    finally:
        record.chmod(0o600)
    profile.finish('instagram', first)
    assert profile.starts == profile.stops == ['shared']


def test_same_platform_can_check_two_distinct_profiles(profile):
    other_root = profile.root / 'other'
    other_root.mkdir()
    other = OfflineProfile(other_root, profile.stack, profile.entries, profile.playwright)
    other.home = profile.home
    other.api_port = profile.api_port
    profile.profiles['second'] = other
    first = profile.command(0, 'instagram')
    second = other.command(1, 'instagram', profile_id='second')
    profile.entered('instagram', first)
    other.entered('instagram', second)
    profile.finish('instagram', first)
    assert profile.stops == ['shared'] and other.stops == []
    other.finish('instagram', second)
    assert other.starts == other.stops == ['second']


def test_simultaneous_cold_checks_start_once_for_different_platforms(profile):
    instagram = profile.command(0, 'instagram')
    tiktok = profile.command(1, 'tiktok')
    profile.entered('instagram', instagram)
    profile.entered('tiktok', tiktok)
    assert profile.starts == ['shared']
    profile.finish('tiktok', tiktok)
    assert profile.stops == []
    profile.finish('instagram', instagram)
    assert profile.stops == ['shared']
