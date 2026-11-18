"""Installed MLX commands against a simulated Launcher, profile API, and real local CDP."""
import json
import os
import re
import sys
import threading
from contextlib import ExitStack
from urllib.parse import urlsplit

import pytest
from patchright.sync_api import sync_playwright

from tests.test_shared_adspower_process import Handler, OfflineProfile, installations, serve

pytestmark = pytest.mark.skipif(sys.platform == 'win32', reason='POSIX console-script fixture')
FOLDER = '218545aa-d375-4913-9180-4e570e46bb1d'
PROFILE = '5f25f9eb-2d65-4440-9d66-dcec611b4f29'


class LauncherProfile(OfflineProfile):
    def __init__(self, root, stack, entries, playwright, *, sites=None):
        super().__init__(root, stack, entries, playwright, sites=sites)
        self.folder = FOLDER
        self.start_fields = {}
        self.denied_tokens = set()
        self.status_code = 200
        self.top_status = {'error_code': '', 'http_code': 200, 'message': ''}
        self.requests = []
        profile = self

        class Launcher(Handler):
            def respond_json(self, data, status=200):
                body = json.dumps({'data': data, 'status': profile.top_status}).encode()
                self.send_response(status)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self):
                assert self.path == '/profile/metas'
                token = self.headers['Authorization']
                ids = json.loads(self.rfile.read(int(self.headers['Content-Length'])))['ids']
                profile_id, = ids
                target = profile.profiles.get(profile_id, profile)
                profile.requests.append(('metas', token))
                if token in profile.denied_tokens:
                    return self.respond_json({}, 403)
                self.respond_json({'profiles': [{'id': profile_id, 'folder_id': target.folder}]})

            def do_GET(self):
                path = urlsplit(self.path).path
                if path == '/api/v1/version':
                    return self.respond_json({'version': 'offline'})
                token = self.headers['Authorization']
                profile.keys.append(token)
                operation, profile_id = path.rsplit('/', 1)
                if operation == '/api/v1/profile/status/p':
                    target = profile.profiles.get(profile_id, profile)
                    profile.requests.append(('status', token))
                    return self.respond_json({
                        'profile_id': profile_id, 'folder_id': target.folder, 'is_quick': False,
                        'browser_type': 'mimic', 'status': 'browser_running' if target.active else 'stopped',
                        'message': str(urlsplit(target.endpoint).port) if target.active else '',
                        **target.observation_fields}, profile.status_code)
                if operation == '/api/v1/profile/stop/p':
                    target = profile.profiles.get(profile_id, profile)
                    profile.requests.append(('stop', token))
                    target.stops.append(profile_id)
                    target.close_browser()
                    target.active = False
                    return self.respond_json({})
                match = re.fullmatch(r'/api/v2/profile/f/([^/]+)/p/([^/]+)/start', path)
                assert match
                folder_id, profile_id = match.groups()
                target = profile.profiles.get(profile_id, profile)
                assert folder_id == target.folder
                profile.requests.append(('start', token))
                target.starts.append(profile_id)
                target.active = True
                self.respond_json({'id': profile_id, 'is_quick': False, 'browser_type': 'mimic',
                                   'port': str(urlsplit(target.endpoint).port), **target.start_fields})

        self.launcher_port = stack.enter_context(serve(Launcher))
        self.routing = root / 'test-routing'
        self.routing.mkdir()
        # Route only the external services. Commands execute their installed production entry point.
        (self.routing / 'sitecustomize.py').write_text(
            "import os\nfrom utils import multilogin\n"
            "multilogin.LAUNCHER_BASE_URL = os.environ['OFFLINE_LAUNCHER']\n"
            "multilogin.PROFILE_METAS_URL = os.environ['OFFLINE_LAUNCHER'] + '/profile/metas'\n")

    def command(self, installation, platform, *flags, profile_id=PROFILE, folder_id=FOLDER,
                action='check'):
        env = {**os.environ, 'HOME': str(self.home), 'ADSPOWER_API_KEY': '',
               'MLX_API_TOKEN': f'offline-key-{installation}', 'PYTHONPATH': str(self.routing),
               'PYTHONNOUSERSITE': '1', 'NO_PROXY': 'localhost,127.0.0.1',
               'OFFLINE_LAUNCHER': f'http://127.0.0.1:{self.launcher_port}'}
        return super().command(installation, platform, '--folder-id', folder_id, *flags,
                               action=action, profile_id=profile_id, env=env)


@pytest.fixture
def mlx(tmp_path, installations):
    with ExitStack() as stack:
        playwright = stack.enter_context(sync_playwright())
        yield LauncherProfile(tmp_path, stack, installations, playwright)


@pytest.mark.parametrize('desktop', [False, True], ids=['cold', 'desktop'])
def test_cli_members_leave_only_their_own_pages_until_last_stop(mlx, desktop):
    mlx.active = desktop
    marked = mlx.browser.contexts[0].pages[0]
    marked.set_content('<textarea>desktop draft</textarea>')
    first = mlx.command(0, 'instagram')
    mlx.entered('instagram', first)
    second = mlx.command(1, 'tiktok')
    mlx.entered('tiktok', second)
    assert mlx.starts == ([] if desktop else [PROFILE])
    assert sorted(mlx.pages_requested) == ['instagram', 'tiktok']
    mlx.finish('instagram', first)
    assert not mlx.stops and marked.locator('textarea').input_value() == 'desktop draft'
    peer, = [p for p in mlx.browser.contexts[0].pages if 'tiktok.com' in p.url]
    peer.locator('textarea').fill('peer still editable')
    assert peer.locator('textarea').input_value() == 'peer still editable'
    mlx.finish('tiktok', second)
    assert mlx.stops == [PROFILE] and not mlx.active
    assert ('status', 'Bearer offline-key-0') in mlx.requests
    assert ('status', 'Bearer offline-key-1') in mlx.requests
    assert ('stop', 'Bearer offline-key-1') in mlx.requests


def test_cli_revalidates_membership_with_each_callers_credential(mlx):
    first = mlx.command(0, 'instagram', '--headed', '--account', 'first')
    mlx.entered('instagram', first)
    record, = mlx.home.rglob('*.json')
    for path in (record, record.parent, record.parent.parent):
        assert path.stat().st_uid == os.getuid()
        assert path.stat().st_mode & 0o777 == (0o600 if path.is_file() else 0o700)
    original = record.read_bytes()
    assert b'offline-key-' not in original and mlx.endpoint.encode() not in original

    def rejected(platform, *flags, **kwargs):
        child = mlx.command(1, platform, *flags, **kwargs)
        output = child.communicate(timeout=8)[0]
        assert child.returncode == 1, output
        assert 'offline-key-' not in output and urlsplit(mlx.endpoint).netloc not in output
        assert record.read_bytes() == original
        assert mlx.pages_requested == ['instagram'] and mlx.stops == []
        return output

    # Local status only describes Agent history. The active browser still appears even
    # when the profile API denies access with this command's credential.
    mlx.denied_tokens.add('Bearer offline-key-1')
    rejected('tiktok')
    assert ('metas', 'Bearer offline-key-1') in mlx.requests
    mlx.denied_tokens.clear()
    assert 'headless' in rejected('tiktok', '--headless')
    assert '文件夹' in rejected('tiktok', folder_id='different')
    assert 'instagram' in rejected('instagram', '--account', 'alias', folder_id=FOLDER.upper(),
                                   profile_id=PROFILE.upper())
    mlx.finish('instagram', first)
    assert mlx.starts == mlx.stops == [PROFILE]


def test_launcher_cannot_attach_an_unverified_or_unsupported_resource(mlx):
    mlx.active = True
    for fields in (
        {'profile_id': 'other'}, {'folder_id': 'other'}, {'is_quick': True},
        {'browser_type': 'stealthfox'}, {'status': 'download_finished'},
        {'message': ''}, {'message': '６５'}, {'message': '0'}, {'message': '65536'},
        {'message': '1'}, {'message': 'token@localhost:9222'},
    ):
        mlx.observation_fields = fields
        # A status-level message cannot furnish the automation port.
        mlx.top_status['message'] = str(urlsplit(mlx.endpoint).port)
        child = mlx.command(0, 'instagram')
        output = child.communicate(timeout=6)[0]
        assert child.returncode == 1, (fields, output)
        assert not mlx.pages_requested and not mlx.starts and not mlx.stops
        assert 'offline-key-' not in output and urlsplit(mlx.endpoint).netloc not in output
    mlx.observation_fields.clear()
    mlx.top_status['error_code'] = 'FAILED'
    child = mlx.command(0, 'instagram')
    output = child.communicate(timeout=6)[0]
    assert child.returncode == 1, output
    assert not mlx.pages_requested and not mlx.starts and not mlx.stops


def test_simultaneous_cold_requests_start_once(mlx):
    one = mlx.command(0, 'instagram')
    two = mlx.command(1, 'tiktok')
    mlx.entered('instagram', one)
    mlx.entered('tiktok', two)
    assert mlx.starts == [PROFILE]
    mlx.finish('tiktok', two)
    assert not mlx.stops
    mlx.finish('instagram', one)
    assert mlx.stops == [PROFILE]


def test_distinct_profiles_can_use_the_same_platform(mlx):
    other_root = mlx.root / 'second'
    other_root.mkdir()
    other = LauncherProfile(other_root, mlx.stack, mlx.entries, mlx.playwright)
    other_id = '6e8e77e0-a211-4067-82c8-e57eff61a5fe'
    other.home, other.launcher_port = mlx.home, mlx.launcher_port
    mlx.profiles[other_id] = other
    first = mlx.command(0, 'instagram')
    second = other.command(1, 'instagram', profile_id=other_id)
    mlx.entered('instagram', first)
    other.entered('instagram', second)
    mlx.finish('instagram', first)
    assert mlx.stops == [PROFILE] and not other.stops
    other.finish('instagram', second)
    assert mlx.starts == [PROFILE] and other.starts == other.stops == [other_id]


@pytest.mark.parametrize('action', ['check', 'upload-note'])
def test_check_and_upload_hold_same_platform_until_login_failure(tmp_path, installations, action):
    entered, release = threading.Event(), threading.Event()

    class Login(Handler):
        def do_GET(self):
            entered.set()
            release.wait(20)
            self.respond(b'<form action="/login"><input name="username"></form>', 'text/html')

    with ExitStack() as stack:
        playwright = stack.enter_context(sync_playwright())
        profile = LauncherProfile(tmp_path, stack, installations, playwright,
                                  sites={'www.tiktok.com': Login})
        image = tmp_path / 'owned.png'
        image.touch()
        # Every upload observes a local login page before it can reach an editor.
        def run(install, action):
            flags = ['--images', str(image), '--no-publish'] if action == 'upload-note' else []
            return profile.command(install, 'tiktok', *flags, action=action)

        first = run(0, action)
        assert entered.wait(12)
        for contender in ('check', 'upload-note'):
            second = run(1, contender)
            output = second.communicate(timeout=5)[0]
            assert second.returncode == 1 and 'tiktok' in output and '占用' in output, output
        assert profile.starts == [PROFILE] and not profile.stops
        release.set()
        output = first.communicate(timeout=12)[0]
        assert first.returncode == 10 and 'publish_attempted=true' not in output, output
        assert profile.stops == [PROFILE]


def test_launcher_status_rate_limit_keeps_cli_code(mlx):
    mlx.status_code = 429
    child = mlx.command(0, 'instagram')
    output = child.communicate(timeout=5)[0]
    assert child.returncode == 11 and '429' in output, output
    assert not mlx.pages_requested and not mlx.starts and not mlx.stops
