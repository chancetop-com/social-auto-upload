"""Crash and recovery through separate installed commands and a local provider."""
import json
import sys
import threading
from urllib.parse import parse_qs, urlsplit

import pytest

from tests.test_shared_adspower_process import Handler, installations, profile, serve


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
                    api.observations.append(api.state)
                    data = {'status': api.state, 'ws': {'puppeteer': api.endpoint}}
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
