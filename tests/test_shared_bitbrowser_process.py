"""Two independent installed CLI processes sharing one BitBrowser window.

The Local API is simulated with BitBrowser's own request/response shape and the
window is a real loopback Chromium.  Each command is a separately installed
``sau`` console script, so this exercises the production admission, CDP join,
page ownership and close-by-ID paths across process boundaries.
"""
import json
import sys
import threading
import time
from contextlib import ExitStack
from urllib.parse import urlsplit

import pytest
from patchright.sync_api import sync_playwright

from tests.test_shared_adspower_process import (
    Handler,
    OfflineProfile,
    installations,
    serve,
)

pytestmark = pytest.mark.skipif(sys.platform == 'win32', reason='POSIX console-script fixture')
WINDOW = 'bitbrowser-window'


def _port(endpoint):
    return str(urlsplit(endpoint).port)


def _pages(profile):
    """Flush one CDP protocol turn so page-close events reach sync Playwright."""
    inspector = profile.browser.new_browser_cdp_session()
    inspector.send('Target.getTargets')
    inspector.detach()
    return profile.browser.contexts[0].pages


def _target_page(profile, marker):
    """Return the page whose URL contains ``marker`` after flushing CDP events."""
    pages = _pages(profile)
    matching = [page for page in pages if marker in page.url]
    assert len(matching) == 1, [page.url for page in pages]
    return matching[0]


class BitBrowserProfile(OfflineProfile):
    """AdsPower fixture's Chromium/CLI plumbing with BitBrowser Local API routes."""

    default_profile_id = WINDOW

    def __init__(self, root, stack, entries, playwright, *, sites=None):
        super().__init__(root, stack, entries, playwright, sites=sites)
        # OfflineProfile always starts an AdsPower-shaped provider server first;
        # point CLI processes at this BitBrowser-shaped server instead.
        self.opens = []
        self.closes = []
        self.requests = []
        self.port_override = None
        profile = self

        class Provider(Handler):
            def read(self):
                return json.loads(self.rfile.read(int(self.headers['Content-Length'])))

            def respond_json(self, data):
                body = json.dumps({'success': True, 'data': data}).encode()
                self.respond(body, 'application/json')

            def target_for(self, profile_id):
                return profile.profiles.get(profile_id, profile)

            def do_POST(self):
                profile.keys.append(self.headers.get('x-api-key'))
                if self.path == '/health':
                    profile.requests.append(('health', None))
                    return self.respond_json({})
                body = self.read()
                if self.path == '/browser/pids/alive':
                    ids = [str(item) for item in body.get('ids', [])]
                    profile.requests.append(('alive', ids))
                    return self.respond_json([
                        window_id for window_id in ids
                        if self.target_for(window_id).active])
                if self.path == '/browser/ports':
                    profile.requests.append(('ports', None))
                    data = {}
                    for window_id, candidate in profile.profiles.items():
                        if candidate.active:
                            data[window_id] = _port(candidate.endpoint)
                    if profile.active:
                        data[profile.default_profile_id] = _port(profile.endpoint)
                    if profile.port_override is not None:
                        for window_id in list(data):
                            data[window_id] = str(profile.port_override)
                    return self.respond_json(data)
                if self.path == '/browser/open':
                    window_id = str(body['id'])
                    target = self.target_for(window_id)
                    profile.requests.append(('open', {**body, 'id': window_id}))
                    profile.opens.append(dict(body, id=window_id))
                    target.starts.append(window_id)
                    target.active = True
                    return self.respond_json({'ws': target.endpoint,
                                              'http': f'127.0.0.1:{_port(target.endpoint)}'})
                if self.path == '/browser/close':
                    window_id = str(body['id'])
                    target = self.target_for(window_id)
                    profile.requests.append(('close', window_id))
                    profile.closes.append(window_id)
                    target.stops.append(window_id)
                    target.close_browser()
                    target.active = False
                    return self.respond_json({})
                self.send_error(404)

        self.api_port = stack.enter_context(serve(Provider))

    def command(self, installation, platform, *flags, host='127.0.0.1', profile_id=WINDOW,
                action='check', env=None, base=None):
        base = base or f'http://{host}:{self.api_port}/'
        return super().command(
            installation, platform, *flags, action=action, profile_id=profile_id,
            env={'ADSPOWER_API_KEY': '', 'ADSPOWER_API_BASE': '', 'MLX_API_TOKEN': '',
                 'BITBROWSER_API_KEY': f'offline-key-{installation}',
                 'BITBROWSER_API_BASE': base, **(env or {})})


class PlatformSites:
    """Gated offline pages for platform-name admission checks."""

    def __init__(self):
        self.keys = ('xiaohongshu', 'rednote', 'facebook', 'facebook-page')
        self.gates = {key: threading.Event() for key in self.keys}
        self.arrived = {key: threading.Event() for key in self.keys}
        self.pages = []

    def handler(self, key, html):
        sites = self

        class Site(Handler):
            def do_GET(self):
                if self.path == '/gate.js':
                    sites.arrived[key].set()
                    sites.gates[key].wait(25)
                    self.respond(b'', 'application/javascript')
                elif self.path == '/favicon.ico':
                    self.respond(b'', 'image/x-icon')
                else:
                    sites.pages.append(key)
                    self.respond(html.encode(), 'text/html; charset=utf-8')

        return Site

    def sites(self):
        upload = '<input class="upload-input"><script defer src="/gate.js"></script>'
        social = ('<input type="file" accept="image/png,video/mp4">'
                  '<a href="/latest/home">Home</a><script defer src="/gate.js"></script>')
        return {
            'creator.xiaohongshu.com': self.handler('xiaohongshu', upload),
            'creator.rednote.com': self.handler('rednote', upload),
            'www.facebook.com': self.handler('facebook', social),
            'business.facebook.com': self.handler('facebook-page', social),
        }


@pytest.fixture
def profile(tmp_path, installations):
    with ExitStack() as stack:
        playwright = stack.enter_context(sync_playwright())
        yield BitBrowserProfile(tmp_path, stack, installations, playwright)


@pytest.fixture
def platform_profile(tmp_path, installations):
    sites = PlatformSites()
    with ExitStack() as stack:
        playwright = stack.enter_context(sync_playwright())
        profile = BitBrowserProfile(tmp_path, stack, installations, playwright,
                                    sites=sites.sites())
        profile.gates.update(sites.gates)
        profile.arrived.update(sites.arrived)
        profile.pages_requested = sites.pages
        yield profile


@pytest.mark.parametrize('desktop', [False, True], ids=['cold', 'already-open'])
def test_checks_share_the_window_until_both_leave(profile, desktop):
    """Cold start opens once; a desktop window is joined with zero opens.

    The final ``/browser/close`` carries the copied window ID.  Closing by ID
    means an old last leaver can close a same-ID window that the desktop
    reopened while that command was still running (ticket 10 owns that rule).
    """
    if desktop:
        profile.active = True
        marked = profile.browser.contexts[0].pages[0]
        marked.set_content('<textarea>desktop draft</textarea>')
    first = profile.command(0, 'instagram')
    profile.entered('instagram', first)
    second = profile.command(1, 'tiktok', host='LOCALHOST')
    profile.entered('tiktok', second)

    assert profile.opens == ([] if desktop else [{'id': WINDOW}])
    assert sorted(profile.pages_requested) == ['instagram', 'tiktok']
    assert {'offline-key-0', 'offline-key-1'} <= set(profile.keys)
    # Joining used the alive-process query and the per-window debug port.  The
    # command's successful CDP connection proves /json/version supplied the
    # same browser endpoint; both commands shared the one existing context.
    assert any(kind == 'alive' and WINDOW in ids for kind, ids in profile.requests)
    assert any(kind == 'ports' for kind, _ in profile.requests)
    assert len(profile.browser.contexts) == 1

    instagram = _target_page(profile, 'instagram.com')
    tiktok = _target_page(profile, 'tiktok.com')
    instagram.locator('textarea').fill('instagram marker')
    tiktok.locator('textarea').fill('tiktok marker')
    assert instagram.locator('textarea').input_value() == 'instagram marker'
    assert tiktok.locator('textarea').input_value() == 'tiktok marker'
    profile.finish('instagram', first)
    assert profile.closes == []
    if desktop:
        assert marked.locator('textarea').input_value() == 'desktop draft'
        marked.locator('textarea').fill('desktop still editable')
    pages = _pages(profile)
    assert not any('instagram.com' in page.url for page in pages), [page.url for page in pages]
    peer = _target_page(profile, 'tiktok.com')
    peer.locator('textarea').fill('tiktok marker continued')
    assert peer.locator('textarea').input_value() == 'tiktok marker continued'

    profile.finish('tiktok', second)
    assert profile.closes == [WINDOW]
    assert profile.opens == ([] if desktop else [{'id': WINDOW}])
    assert not profile.active


def test_first_leaver_closes_its_own_page_and_attributable_child(tmp_path, installations):
    """The peer page and child stay usable; the first leaver sends no close."""
    release = threading.Event()

    class SlowInstagram(Handler):
        def do_GET(self):
            if self.path == '/gate.js':
                profile.arrived['instagram'].set()
                release.wait(25)
                self.respond(b'', 'application/javascript')
            elif self.path == '/favicon.ico':
                self.respond(b'', 'image/x-icon')
            else:
                # The opener page itself spawns the child, as a platform editor
                # would; a popup opened by another CDP client is not attributable.
                self.respond(b'<textarea>instagram draft</textarea>'
                             b'<script defer src="/gate.js"></script>'
                             b'<script>addEventListener("load", () => setTimeout('
                             b'() => window.open("about:blank"), 200))</script>', 'text/html')

    with ExitStack() as stack:
        playwright = stack.enter_context(sync_playwright())
        profile = BitBrowserProfile(tmp_path, stack, installations, playwright,
                                    sites={'www.instagram.com': SlowInstagram})
        first = profile.command(0, 'instagram')
        assert profile.arrived['instagram'].wait(12)
        second = profile.command(1, 'tiktok')
        profile.entered('tiktok', second)
        desktop = profile.browser.contexts[0].pages[0]
        expected_pages = len(_pages(profile)) + 1
        release.set()
        instagram = _target_page(profile, 'instagram.com')
        instagram.wait_for_load_state('load')
        deadline = time.monotonic() + 12
        while len(_pages(profile)) < expected_pages:
            assert time.monotonic() < deadline, [page.url for page in _pages(profile)]
            time.sleep(.05)
        own_child, = [page for page in _pages(profile)
                      if page not in (desktop, instagram) and page.url == 'about:blank']
        own_child.set_content('<textarea>own child draft</textarea>')
        tiktok = _target_page(profile, 'tiktok.com')
        with tiktok.expect_popup() as popup:
            tiktok.evaluate("window.open('about:blank')")
        peer_child = popup.value
        peer_child.set_content('<textarea>peer child draft</textarea>')
        # The probe's own positive marker only appears after navigation, so the
        # popup is attributable while the command's page is still open.
        instagram.evaluate("document.body.insertAdjacentHTML('beforeend',"
                           " '<a href=\"/direct/inbox/\">Inbox</a>')")

        output = profile.finish('instagram', first)
        assert profile.closes == []
        _pages(profile)
        assert own_child.is_closed(), output
        assert not peer_child.is_closed()
        assert peer_child.locator('textarea').input_value() == 'peer child draft'
        tiktok.locator('textarea').fill('tiktok still editable')
        assert tiktok.locator('textarea').input_value() == 'tiktok still editable'
        profile.finish('tiktok', second)
        assert profile.closes == [WINDOW]


def test_join_binds_the_shared_record_to_resource_and_live_instance(profile):
    first = profile.command(0, 'instagram')
    profile.entered('instagram', first)
    record, = [path for path in profile.home.rglob('*.json') if path.is_file()]
    original = record.read_bytes()
    assert b'offline-key-' not in original and profile.endpoint.encode() not in original
    instagram = _target_page(profile, 'instagram.com')
    instagram.locator('textarea').fill('first command still editable')

    def rejected(*flags, **kwargs):
        child = profile.command(1, 'tiktok', *flags, **kwargs)
        output = child.communicate(timeout=8)[0]
        assert child.returncode == 1, output
        assert 'offline-key-' not in output and urlsplit(profile.endpoint).netloc not in output
        assert record.read_bytes() == original
        assert first.poll() is None
        assert profile.pages_requested == ['instagram'] and not profile.closes
        return output

    # A different Local API base is a different resource, even for the same window ID.
    assert '服务' in rejected(base=f'http://127.0.0.2:{profile.api_port}')
    # A live process whose debug port reports a different browser is not the
    # instance the shared record belongs to.
    other_root = profile.root / 'other'
    other_root.mkdir()
    other = OfflineProfile(other_root, profile.stack, profile.entries, profile.playwright)
    profile.port_override = urlsplit(other.endpoint).port
    assert '连接' in rejected()
    profile.port_override = None
    # The later command joins only after both checks pass; LOCALHOST is the
    # same canonical Local API resource as 127.0.0.1.
    peer = profile.command(1, 'tiktok', host='LOCALHOST')
    profile.entered('tiktok', peer)
    assert instagram.locator('textarea').input_value() == 'first command still editable'
    assert profile.opens == [{'id': WINDOW}]
    profile.finish('instagram', first)
    assert profile.closes == []
    profile.finish('tiktok', peer)
    assert profile.closes == [WINDOW]


def test_explicit_mode_uses_the_shared_record_for_the_same_connection(profile):
    first = profile.command(0, 'instagram', '--headless')
    profile.entered('instagram', first)
    assert profile.opens == [{'id': WINDOW, 'args': ['--headless'], 'ignoreDefaultUrls': True}]

    peer = profile.command(1, 'tiktok', '--headless')
    profile.entered('tiktok', peer)
    assert profile.opens == [{'id': WINDOW, 'args': ['--headless'], 'ignoreDefaultUrls': True}]

    # The Local API does not report a window's display mode, so only the shared
    # record for this exact connection can satisfy an explicit switch.
    conflict = profile.command(1, 'youtube', '--headed')
    output = conflict.communicate(timeout=8)[0]
    assert conflict.returncode == 1 and 'headless' in output, output
    assert 'youtube' not in profile.pages_requested
    assert first.poll() is None and peer.poll() is None

    profile.finish('instagram', first)
    assert profile.closes == []
    profile.finish('tiktok', peer)
    assert profile.closes == [WINDOW]


@pytest.mark.parametrize('flag', ['--headed', '--headless'])
def test_explicit_mode_rejects_a_desktop_window_without_a_record(profile, flag):
    profile.active = True
    marked = profile.browser.contexts[0].pages[0]
    marked.set_content('<textarea>desktop draft</textarea>')
    child = profile.command(0, 'tiktok', flag)
    output = child.communicate(timeout=8)[0]
    assert child.returncode == 1 and 'headless' in output, output
    assert not profile.opens and not profile.pages_requested and not profile.closes
    assert marked.locator('textarea').input_value() == 'desktop draft'
    marked.locator('textarea').fill('desktop still editable')
    assert marked.locator('textarea').input_value() == 'desktop still editable'


def test_omitted_mode_joins_desktop_window_but_unknown_record_cannot_satisfy_it(profile):
    # The desktop process is actually headless while the local CLI default is
    # headed; omitted flags may still join because the join does not guess.
    profile.active = True
    marked = profile.browser.contexts[0].pages[0]
    marked.set_content('<textarea>desktop draft</textarea>')
    first = profile.command(0, 'instagram')
    profile.entered('instagram', first)
    assert not profile.opens

    second = profile.command(1, 'tiktok', host='LOCALHOST')
    profile.entered('tiktok', second)
    assert not profile.opens

    # Joining this desktop window recorded an unknown mode.  An explicit switch
    # cannot use that record because there is no confirmed setting.
    for flag in ('--headed', '--headless'):
        conflict = profile.command(1, 'youtube', flag)
        output = conflict.communicate(timeout=8)[0]
        assert conflict.returncode == 1 and 'headless' in output, output
        assert 'youtube' not in profile.pages_requested
        assert first.poll() is None and second.poll() is None

    assert marked.locator('textarea').input_value() == 'desktop draft'
    marked.locator('textarea').fill('desktop still editable')
    profile.finish('instagram', first)
    assert profile.closes == []
    profile.finish('tiktok', second)
    assert profile.closes == [WINDOW]


def test_simultaneous_cold_checks_open_once_for_different_platforms(profile):
    instagram = profile.command(0, 'instagram')
    tiktok = profile.command(1, 'tiktok')
    profile.entered('instagram', instagram)
    profile.entered('tiktok', tiktok)
    assert profile.opens == [{'id': WINDOW}]
    assert sorted(profile.pages_requested) == ['instagram', 'tiktok']
    profile.finish('tiktok', tiktok)
    assert profile.closes == []
    profile.finish('instagram', instagram)
    assert profile.closes == [WINDOW]


def test_check_and_publish_share_one_platform_slot(profile):
    media = profile.root / 'owned.png'
    media.touch()
    first = profile.command(0, 'tiktok')
    profile.entered('tiktok', first)
    for action, flags in (('check', ()), ('upload-note', ('--images', str(media), '--no-publish'))):
        contender = profile.command(1, 'tiktok', *flags, action=action)
        output = contender.communicate(timeout=8)[0]
        assert contender.returncode == 1, output
        assert 'tiktok' in output and '占用' in output, output
    assert profile.pages_requested == ['tiktok']
    assert profile.opens == [{'id': WINDOW}] and profile.closes == []
    profile.finish('tiktok', first)
    assert profile.closes == [WINDOW]


def test_same_platform_can_check_two_distinct_profiles(profile):
    other_root = profile.root / 'other-window'
    other_root.mkdir()
    other = BitBrowserProfile(other_root, profile.stack, profile.entries, profile.playwright)
    other_id = 'bitbrowser-window-2'
    other.home, other.api_port = profile.home, profile.api_port
    profile.profiles[other_id] = other
    first = profile.command(0, 'instagram')
    second = other.command(1, 'instagram', profile_id=other_id)
    profile.entered('instagram', first)
    other.entered('instagram', second)
    assert sorted(open_request['id'] for open_request in profile.opens) == sorted([WINDOW, other_id])
    profile.finish('instagram', first)
    assert profile.closes == [WINDOW]
    other.finish('instagram', second)
    assert profile.closes == [WINDOW, other_id]


@pytest.mark.parametrize(('left', 'right'), [
    ('xiaohongshu', 'rednote'),
    ('facebook', 'facebook-page'),
])
def test_sibling_platform_names_have_separate_slots(platform_profile, left, right):
    """Filing names xiaohongshu/rednote and facebook/facebook-page are distinct."""
    first = platform_profile.command(0, left)
    platform_profile.entered(left, first)
    second = platform_profile.command(1, right)
    platform_profile.entered(right, second)
    assert sorted(platform_profile.pages_requested) == sorted([left, right])
    assert platform_profile.opens == [{'id': WINDOW}]
    platform_profile.finish(left, first)
    assert platform_profile.closes == []
    platform_profile.finish(right, second)
    assert platform_profile.closes == [WINDOW]
