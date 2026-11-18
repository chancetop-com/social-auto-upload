"""Crash and recovery through separate installed commands and a local provider."""
import json
import signal
import subprocess
import sys
import threading
from urllib.parse import parse_qs, urlsplit

import pytest

from tests.test_shared_adspower_process import Handler, OfflineProfile, installations, profile, serve


pytestmark = pytest.mark.skipif(sys.platform == 'win32', reason='POSIX console-script fixture')


class ControlledProvider:
    """Choose when each real HTTP request completes and what the client sees."""

    def __init__(self, browser):
        self.browser = browser
        self.state = 'Inactive'
        self.endpoint = browser.endpoint
        self.starts = []
        self.stops = []
        self.observations = []
        self.observed = threading.Event()
        self.observe = self.current_state
        self.start = self.start_ok
        self.stop = self.stop_ok
        api = self

        class Provider(Handler):
            def do_GET(self):
                url = urlsplit(self.path)
                if url.path == '/status':
                    data = {}
                else:
                    assert url.path == '/api/v2/browser-profile/active'
                    assert parse_qs(url.query) == {'profile_id': ['shared']}
                    data = api.observe()
                    api.observations.append(data['status'])
                    api.observed.set()
                self.reply({'code': 0, 'data': data})

            def do_POST(self):
                request = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                assert request['profile_id'] == 'shared'
                operation = self.path.rsplit('/', 1)[-1]
                assert operation in ('start', 'stop')
                getattr(api, operation + 's').append(request['profile_id'])
                getattr(api, operation)(self)

            def reply(self, data):
                self.respond(json.dumps(data).encode(), 'application/json')

        browser.api_port = browser.stack.enter_context(serve(Provider))

    def current_state(self):
        return {'status': self.state, 'ws': {'puppeteer': self.endpoint}}

    def start_ok(self, request):
        self.state = 'Active'
        request.reply({'code': 0, 'data': {'ws': {'puppeteer': self.endpoint}}})

    def stop_ok(self, request):
        self.state = 'Inactive'
        request.reply({'code': 0})


def test_definitively_rejected_stop_preserves_result_and_next_command_can_join(profile):
    api = ControlledProvider(profile)
    api.stop = lambda request: request.send_error(429)
    first = profile.command(0, 'instagram')
    profile.entered('instagram', first)
    output = profile.finish('instagram', first)
    assert '停止或清理失败' in output
    assert api.starts == api.stops == ['shared'] and api.state == 'Active'

    api.stop = api.stop_ok
    second = profile.command(1, 'tiktok')
    profile.entered('tiktok', second)
    profile.finish('tiktok', second)
    assert api.starts == ['shared'] and api.stops == ['shared', 'shared']
    assert api.state == 'Inactive'


def test_rejected_start_is_terminal_and_next_authorized_command_can_start(profile):
    api = ControlledProvider(profile)
    api.start = lambda request: request.send_error(403)
    refused = profile.command(0, 'instagram')
    output = refused.communicate(timeout=10)[0]
    assert refused.returncode == 1 and 'start' in output
    assert api.stops == [] and profile.pages_requested == []

    api.start = api.start_ok
    legitimate = profile.command(1, 'instagram')
    profile.entered('instagram', legitimate)
    profile.finish('instagram', legitimate)
    assert api.starts == ['shared', 'shared'] and api.stops == ['shared']
    assert api.observations == ['Inactive', 'Inactive']


@pytest.mark.parametrize('finishes', [True, False], ids=['eventually-stopped', 'still-ambiguous'])
def test_join_waits_for_last_stop_after_its_response_is_lost(profile, finishes):
    api = ControlledProvider(profile)
    api.stop = lambda request: None  # Close the HTTP connection without a response.
    first = profile.command(0, 'instagram')
    profile.entered('instagram', first)
    assert '停止或清理失败' in profile.finish('instagram', first)

    api.stop = api.stop_ok
    api.observed.clear()
    successor = profile.command(1, 'tiktok')
    assert api.observed.wait(8)
    assert api.observations[-1] == 'Active'
    if finishes:
        api.state = 'Inactive'
        profile.entered('tiktok', successor)
        profile.finish('tiktok', successor)
        assert api.starts == api.stops == ['shared', 'shared']
        assert api.state == 'Inactive'
    else:
        output = successor.communicate(timeout=16)[0]
        assert successor.returncode == 1 and '停止' in output and '超时' in output
        assert api.starts == api.stops == ['shared']
        assert profile.pages_requested == ['instagram'] and api.state == 'Active'


def test_killed_after_complete_start_before_attach_can_restart_a_now_idle_profile(profile):
    api = ControlledProvider(profile)
    attaching = threading.Event()

    class DepartedBrowser(Handler):
        def do_GET(self):
            attaching.set()
            self.send_error(410)

    port = profile.stack.enter_context(serve(DepartedBrowser))
    api.endpoint = f'ws://127.0.0.1:{port}/devtools/browser/previous'
    interrupted = profile.command(0, 'instagram')
    assert attaching.wait(10)
    interrupted.kill()
    interrupted.communicate(timeout=8)
    assert api.starts == ['shared'] and api.stops == [] and not profile.pages_requested

    # AdsPower acknowledged the last Start with its CDP endpoint. The desktop
    # has since closed that browser, before the killed client could open a tab.
    api.state = 'Inactive'
    api.endpoint = profile.endpoint
    next_command = profile.command(1, 'instagram')
    profile.entered('instagram', next_command)
    profile.finish('instagram', next_command)
    assert api.starts == ['shared', 'shared'] and api.stops == ['shared']


@pytest.mark.parametrize('reply', ['lost', 'missing-ws', 'malformed-ws'])
def test_uncertain_start_preserves_browser_until_current_connection_is_available(profile, reply):
    api = ControlledProvider(profile)
    if reply == 'lost':
        api.start = lambda request: None
    else:
        ws = {'puppeteer': 'invalid-cdp-endpoint'} if reply == 'malformed-ws' else {}
        api.start = lambda request: request.reply({'code': 0, 'data': {'ws': ws}})

    def refused():
        child = profile.command(1, 'tiktok')
        output = child.communicate(timeout=18)[0]
        assert child.returncode == 1, output
        assert 'offline-key-' not in output and profile.endpoint not in output
        assert profile.pages_requested == [] and api.stops == []
        return output

    assert 'start' in refused()
    for state, endpoint in [('Inactive', ''), ('Starting', ''), ('Unknown', ''), ('Active', '')]:
        api.state, api.endpoint = state, endpoint
        reason = '尚未确认' if state == 'Inactive' else 'observe'
        assert reason in refused()
        assert api.starts == ['shared']

    api.state, api.endpoint = 'Active', profile.endpoint
    recovered = profile.command(0, 'tiktok')
    profile.entered('tiktok', recovered)
    profile.finish('tiktok', recovered)
    assert api.starts == api.stops == ['shared']

def platform_pages(profile, platform):
    inspector = profile.browser.new_browser_cdp_session()
    inspector.send('Target.getTargets')
    inspector.detach()
    return [page for page in profile.browser.contexts[0].pages
            if urlsplit(page.url).hostname == f'www.{platform}.com']


def kill_cli(child):
    child.kill()
    child.communicate(timeout=8)
    assert child.returncode == -signal.SIGKILL


def test_killing_one_cli_releases_only_its_platform_and_preserves_both_drafts(profile):
    first = profile.command(0, 'instagram')
    profile.entered('instagram', first)
    peer = profile.command(1, 'tiktok')
    profile.entered('tiktok', peer)
    old, = platform_pages(profile, 'instagram')
    peer_page, = platform_pages(profile, 'tiktok')
    old.locator('textarea').fill('killed command draft')
    peer_page.locator('textarea').fill('surviving command draft')
    kill_cli(first)
    # The interrupted navigation can now finish. Chromium coalesces identical
    # pending script requests from different tabs on this origin.
    profile.gates['instagram'].set()
    old.wait_for_load_state('load', timeout=5000)
    profile.gates['instagram'].clear()

    blocked = profile.command(0, 'tiktok')
    output = blocked.communicate(timeout=8)[0]
    assert blocked.returncode == 1 and 'tiktok' in output and '占用' in output
    assert profile.stops == []
    assert peer_page.locator('textarea').input_value() == 'surviving command draft'
    peer_page.locator('textarea').fill('edited after crash')
    profile.arrived['instagram'].clear()
    next_command = profile.command(1, 'instagram')
    profile.entered('instagram', next_command)
    new, = [p for p in platform_pages(profile, 'instagram') if p != old]
    assert new.locator('textarea').input_value() == 'draft'
    assert old.locator('textarea').input_value() == 'killed command draft'
    profile.finish('instagram', next_command)
    assert profile.starts == ['shared'] and profile.stops == []
    assert peer_page.locator('textarea').input_value() == 'edited after crash'
    assert old.locator('textarea').input_value() == 'killed command draft'
    profile.finish('tiktok', peer)
    assert profile.stops == ['shared'] and not profile.active


@pytest.mark.parametrize('reopened', [False, True], ids=['original-browser', 'desktop-reopened'])
def test_all_killed_commands_recover_from_the_current_profile(profile, reopened):
    first = profile.command(0, 'instagram')
    profile.entered('instagram', first)
    peer = profile.command(1, 'tiktok')
    profile.entered('tiktok', peer)
    old, = platform_pages(profile, 'instagram')
    old.locator('textarea').fill('original browser draft')
    kill_cli(first)
    kill_cli(peer)
    for gate in profile.gates.values():
        gate.set()
    assert profile.active and profile.stops == []

    if reopened:
        profile.close_browser()
        root = profile.root / 'manually-reopened'
        root.mkdir()
        current = OfflineProfile(root, profile.stack, profile.entries, profile.playwright)
        current.home = profile.home
        current.api_port = profile.api_port
        current.active = True
        assert current.endpoint != profile.endpoint
        profile.profiles['shared'] = current
        marked = current.browser.contexts[0].pages[0]
        marked.set_content('<textarea>desktop draft</textarea>')
    else:
        current = profile
        old.wait_for_load_state('load', timeout=5000)
        current.arrived['instagram'].clear()
        current.gates['instagram'].clear()
        marked = old

    recovered = current.command(1, 'instagram')
    current.entered('instagram', recovered)
    editor, = [p for p in platform_pages(current, 'instagram') if p != marked]
    assert editor.locator('textarea').input_value() == 'draft'
    assert marked.locator('textarea').input_value() == ('desktop draft' if reopened else 'original browser draft')
    current.finish('instagram', recovered)
    assert profile.starts == ['shared'] and current.stops == ['shared']
    if reopened:
        assert not current.starts and not profile.stops
    assert not current.active and current.chrome.poll() is not None

def test_slow_failing_join_cannot_strand_the_last_admitted_commands_profile(profile):
    api = ControlledProvider(profile)
    departing = profile.command(0, 'tiktok')
    profile.entered('tiktok', departing)
    editor, = platform_pages(profile, 'tiktok')
    observing, release = threading.Event(), threading.Event()

    def slow_unknown():
        observing.set()
        release.wait(25)
        return {'status': 'Unknown'}

    api.observe = slow_unknown
    contender = profile.command(1, 'instagram')
    assert observing.wait(8)
    try:
        profile.gates['tiktok'].set()
        if not editor.is_closed():
            editor.wait_for_event('close', timeout=8000)
        # A provider call is allowed to outlast a new admission's 10s lock
        # budget. The departing CLI still owns its last-member obligation.
        with pytest.raises(subprocess.TimeoutExpired):
            departing.wait(timeout=11)
    finally:
        release.set()
    output = contender.communicate(timeout=8)[0]
    assert contender.returncode == 1 and 'observe' in output
    profile.finish('tiktok', departing)
    assert api.starts == api.stops == ['shared'] and api.state == 'Inactive'
