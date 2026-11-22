"""Crash, interrupted-start and cleanup recovery across installed BitBrowser CLIs.

Every command is a separately installed ``sau`` console script.  The Local API
is a loopback server with BitBrowser's ``success`` envelope, and the window is a
real loopback Chromium.  A child-only ``sitecustomize`` seam advances the
sharing layer's monotonic clock so the production 5-second close interval is
exercised without real sleeps.
"""
import json
import signal
import sys
import threading
from contextlib import ExitStack
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from patchright.sync_api import sync_playwright

from tests.shared_publish_sites import InstagramSite
from tests.test_adspower_crash_recovery import kill_cli, platform_pages
from tests.test_shared_adspower_process import Handler, installations
from tests.test_shared_bitbrowser_process import BitBrowserProfile, WINDOW
from tests.test_xhs_rednote_sharing import CreatorSite

pytestmark = pytest.mark.skipif(sys.platform == 'win32', reason='POSIX console-script fixture')
HARNESS = Path(__file__).with_name('fixtures') / 'sharing_harness'
FIXTURES = Path(__file__).with_name('fixtures')


def harness_env(clock=None, *, page_close_failure=False, browser_close_failure=False):
    env = {'PYTHONPATH': str(HARNESS)}
    if clock is not None:
        env['SAU_TEST_MANAGED_CLOCK'] = str(clock)
    if page_close_failure:
        env['SAU_TEST_PAGE_CLOSE_FAILURE'] = '1'
    if browser_close_failure:
        env['SAU_TEST_BROWSER_CLOSE_FAILURE'] = '1'
    return env


def controlled(profile, installation, platform, *flags, clock=None, action='check',
               env=None, **session_flags):
    return profile.command(
        installation, platform, *flags, action=action,
        env={**harness_env(clock, **session_flags), **(env or {})},
    )


def wait_for(check, child, timeout=20):
    import time
    deadline = time.monotonic() + timeout
    while not check():
        if child.poll() is not None:
            pytest.fail(child.communicate()[0])
        if time.monotonic() >= deadline:
            child.kill()
            pytest.fail('offline page timeout:\n' + child.communicate(timeout=8)[0])
        time.sleep(.025)


def finish_any(child, timeout=25):
    output = child.communicate(timeout=timeout)[0]
    return child.returncode, output


def read_record(profile):
    record, = [path for path in profile.home.rglob('*.json') if path.is_file()]
    return record, json.loads(record.read_text())


@pytest.fixture
def profile(tmp_path, installations):
    with ExitStack() as stack:
        playwright = stack.enter_context(sync_playwright())
        yield BitBrowserProfile(tmp_path, stack, installations, playwright)


@pytest.fixture
def create_profile(tmp_path, installations):
    with ExitStack() as stack:
        playwright = stack.enter_context(sync_playwright())

        def create(root=None, *, sites=None):
            root = root or tmp_path
            root.mkdir(exist_ok=True)
            return BitBrowserProfile(root, stack, installations, playwright,
                                     sites=sites)

        yield create


@pytest.fixture
def virtual_clock(tmp_path):
    path = tmp_path / 'managed-clock'
    path.write_text('1000.0')
    return path


def advance_clock_to(clock, value):
    clock.write_text(repr(float(value)))


@pytest.mark.parametrize("gateway_status", [None, 502, 504], ids=["dropped", "502", "504"])
def test_lost_open_response_recovers_only_a_connectable_current_instance(profile, gateway_status):
    def lost_without_reply(request, target):
        target.active = True
        if gateway_status is not None:
            request.send_error(gateway_status)

    profile.start_hook = lost_without_reply
    lost = controlled(profile, 0, 'instagram')
    code, output = finish_any(lost)
    assert code == 1 and ('start' in output or '启动' in output), output
    if gateway_status is not None:
        assert str(gateway_status) in output
    assert profile.opens == [{'id': WINDOW}] and profile.closes == []
    assert profile.pages_requested == []
    _, record = read_record(profile)
    assert record['phase'] == 'starting'

    # No running process: the pending Start stays unknown; nothing is retried.
    profile.active = False
    refused = controlled(profile, 1, 'tiktok')
    code, output = finish_any(refused)
    assert code == 1 and '尚未确认' in output, output
    assert profile.opens == [{'id': WINDOW}] and profile.closes == []
    assert profile.pages_requested == []

    # Alive but no debug port yet is also unknown, not "stopped".
    profile.active = True
    profile.ports_hook = lambda request: request.respond_json({})
    refused = controlled(profile, 1, 'tiktok')
    code, output = finish_any(refused)
    assert code == 1 and '端口' in output and '启动' in output, output
    assert profile.opens == [{'id': WINDOW}] and profile.closes == []
    assert profile.pages_requested == []

    # The current instance is now connectable: join it from a new page.
    profile.ports_hook = None
    recovered = controlled(profile, 1, 'tiktok')
    profile.entered('tiktok', recovered)
    assert profile.opens == [{'id': WINDOW}]
    assert profile.pages_requested == ['tiktok']
    profile.finish('tiktok', recovered)
    assert profile.closes == [WINDOW]


def test_peer_join_rejects_a_changed_digest_or_unusable_debug_port(create_profile, tmp_path):
    profile = create_profile()
    first = profile.command(0, 'instagram')
    profile.entered('instagram', first)
    page, = platform_pages(profile, 'instagram')
    page.locator('textarea').fill('peer marker')

    other_root = tmp_path / 'other-browser'
    other = create_profile(other_root)
    profile.port_override = urlsplit(other.endpoint).port
    marker = 'peer marker'

    def rejected(fragment):
        nonlocal marker
        child = profile.command(1, 'tiktok')
        code, output = finish_any(child)
        assert code == 1 and fragment in output, output
        assert first.poll() is None
        assert profile.pages_requested == ['instagram']
        assert profile.opens == [{'id': WINDOW}] and profile.closes == []
        assert page.locator('textarea').input_value() == marker
        marker = f'peer marker after {fragment}'
        page.locator('textarea').fill(marker)

    # The process and port exist, but the port reports a different browser
    # instance than the shared record and the live peer.
    rejected('连接')
    profile.port_override = None

    # Alive process, but the port query omits this window.
    profile.ports_hook = lambda request: request.respond_json({})
    rejected('端口')

    # The port query itself fails (404); the later command exits before a page.
    profile.ports_hook = lambda request: request.send_error(404)
    rejected('404')
    profile.ports_hook = None

    assert page.locator('textarea').input_value() == 'peer marker after 404'
    peer = profile.command(1, 'tiktok')
    profile.entered('tiktok', peer)
    assert page.locator('textarea').input_value() == 'peer marker after 404'
    profile.finish('instagram', first)
    assert profile.closes == []
    profile.finish('tiktok', peer)
    assert profile.closes == [WINDOW]


class GatedInstagramSite(InstagramSite):
    """Instagram composer whose first page load waits for the test."""

    def __init__(self):
        super().__init__()
        self.arrived = threading.Event()
        self.release = threading.Event()

    def handler(self, *, block_share=False):
        html = (FIXTURES / 'instagram_composer.html').read_text(encoding='utf-8')
        html = html.replace('CONFIG', json.dumps({'blockedShare': block_share})) + """
        <script>
          document.cookie = 'ds_user_id=42;path=/';
          document.addEventListener('click', event => {
            const action = event.target.closest('[data-action=advance]');
            if (action?.textContent !== 'Share') return;
            const caption = document.querySelector('[contenteditable]').innerText;
            fetch('/api/v1/media/configure/', {method: 'POST', body: JSON.stringify({caption, files})});
          });
        </script>
        <script defer src="/gate.js"></script>"""
        site = self

        class Instagram(Handler):
            def do_GET(self):
                if self.path == '/gate.js':
                    site.arrived.set()
                    site.release.wait(30)
                    self.respond(b'', 'application/javascript')
                elif self.path == '/':
                    self.respond(html.encode(), 'text/html; charset=utf-8')
                else:
                    self.send_error(404)

            def do_POST(self):
                if self.path != '/api/v1/media/configure/':
                    return self.send_error(404)
                submission = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                site.submissions.append(submission)
                self.respond(json.dumps(site.configure(submission)).encode(), 'application/json')

        return Instagram


@pytest.mark.parametrize('reopened', [False, True], ids=['original-window', 'desktop-reopened'])
def test_all_killed_commands_recover_current_window_without_replaying_drafts(
        create_profile, tmp_path, virtual_clock, reopened):
    site = GatedInstagramSite()
    profile = create_profile(sites={'www.instagram.com': site.handler()})
    photo = tmp_path / 'photo.png'
    photo.touch()
    saved = tmp_path / 'prepared.json'

    # A prior command leaves a durable prepared result for later verification.
    site.release.set()
    prepared = controlled(
        profile, 0, 'instagram', '--title', 'prepared draft',
        '--images', str(photo), '--no-publish', '--result', str(saved),
        action='upload-note', clock=virtual_clock, env={'HUMANIZE': '0'})
    code, output = finish_any(prepared)
    assert code == 0 and 'prepared' in saved.read_text(), output
    snapshot = saved.read_bytes()
    _, record = read_record(profile)
    advance_clock_to(virtual_clock, float(record['cooldown_since']) + 6)

    # The stopped profile is replaced by a fresh local Chromium, as the desktop
    # would after a close/open cycle.  Both profiles share the same window ID,
    # Local API and private records.
    current = create_profile(tmp_path / 'current-window')
    current.home, current.api_port = profile.home, profile.api_port
    profile.profiles[WINDOW] = current

    # Two independent checks own drafts when every CLI is killed.
    site.release.clear()
    first = controlled(current, 0, 'instagram', clock=virtual_clock)
    current.entered('instagram', first)
    peer = controlled(current, 1, 'tiktok', clock=virtual_clock)
    current.entered('tiktok', peer)
    old, = platform_pages(current, 'instagram')
    old.locator('textarea').fill('killed draft')
    peer_page, = platform_pages(current, 'tiktok')
    peer_page.locator('textarea').fill('surviving draft')
    kill_cli(first)
    kill_cli(peer)
    current.gates['instagram'].set()
    current.gates['tiktok'].set()
    assert current.active and profile.closes == [WINDOW]
    assert site.submissions == []

    if reopened:
        current.close_browser()
        current.active = False
        reopened_profile = create_profile(tmp_path / 'reopened')
        reopened_profile.home, reopened_profile.api_port = profile.home, profile.api_port
        reopened_profile.active = True
        profile.profiles[WINDOW] = reopened_profile
        marked = reopened_profile.browser.contexts[0].pages[0]
        marked.set_content('<textarea>desktop draft</textarea>')
        recovered = controlled(reopened_profile, 1, 'tiktok', clock=virtual_clock)
        reopened_profile.entered('tiktok', recovered)
        restored, = [page for page in platform_pages(reopened_profile, 'tiktok')
                     if page != marked]
        assert profile.opens == [{'id': WINDOW}, {'id': WINDOW}]
        assert current.starts == [WINDOW] and not reopened_profile.starts
    else:
        old.wait_for_load_state('load', timeout=5000)
        marked = old
        current.arrived['tiktok'].clear()
        recovered = controlled(current, 1, 'tiktok', clock=virtual_clock)
        current.entered('tiktok', recovered)
        restored, = [page for page in platform_pages(current, 'tiktok') if page != peer_page]
        assert profile.opens == [{'id': WINDOW}, {'id': WINDOW}]
        assert profile.starts == [WINDOW] and current.starts == [WINDOW]

    assert restored.locator('textarea').input_value() == 'draft'
    assert site.submissions == []
    if reopened:
        assert marked.locator('textarea').input_value() == 'desktop draft'
        reopened_profile.finish('tiktok', recovered)
        assert not reopened_profile.active and reopened_profile.chrome.poll() is not None
    else:
        assert marked.locator('textarea').input_value() == 'killed draft'
        current.finish('tiktok', recovered)
    assert profile.closes == [WINDOW, WINDOW]
    assert saved.read_bytes() == snapshot
    assert json.loads(saved.read_text())['status'] == 'prepared'
    assert float(virtual_clock.read_text()) >= float(record['cooldown_since']) + 5


@pytest.mark.parametrize("reboot", [False, True], ids=["same-boot", "after-reboot"])
def test_close_ack_requires_the_settle_interval_and_confirmed_process_exit(
        create_profile, tmp_path, virtual_clock, reboot):
    profile = create_profile()
    profile.stop_hook = lambda request, target: request.respond_json({})
    first = controlled(profile, 0, 'instagram', clock=virtual_clock)
    profile.entered('instagram', first)
    profile.finish('instagram', first)
    _, record = read_record(profile)
    assert record['phase'] == 'stop_acknowledged'
    ack = float(record['stop_acknowledged_at'])
    assert record['endpoint'] and profile.active

    # Old process exits, and the successor arrives only one virtual second
    # later.  It may start only at ack + 5, not immediately.
    profile.close_browser()
    profile.active = False
    current = create_profile(tmp_path / 'next-window')
    current.home, current.api_port = profile.home, profile.api_port
    profile.profiles[WINDOW] = current
    clock = virtual_clock
    clock.write_text(repr(1.0 if reboot else ack + 1))
    if reboot:
        # An interrupted recovery must not reset the five-second wait on every retry.
        profile.alive_hook = lambda request, ids: request.send_error(503)
        code, output = finish_any(controlled(current, 1, 'tiktok', clock=clock))
        assert code == 1 and '503' in output
        profile.alive_hook = None
        advance_clock_to(clock, 3.0)
    successor = controlled(current, 1, 'tiktok', clock=clock)
    current.entered('tiktok', successor)
    if reboot:
        assert float(clock.read_text()) == 6.0
    else:
        assert float(clock.read_text()) >= ack + 5
    assert profile.opens == [{'id': WINDOW}, {'id': WINDOW}]
    assert profile.closes == [WINDOW]
    current.finish('tiktok', successor)
    assert profile.closes == [WINDOW, WINDOW]


@pytest.mark.parametrize("reboot", [False, True], ids=["confirmed-exit", "prior-boot-ack"])
def test_desktop_reopen_after_confirmed_exit_joins_existing_window(create_profile, tmp_path, virtual_clock, reboot):
    old = create_profile()
    if reboot:
        old.stop_hook = lambda request, target: request.respond_json({})
    first = controlled(old, 0, 'instagram', clock=virtual_clock)
    old.entered('instagram', first)
    old.finish('instagram', first)
    if reboot:
        assert old.active and read_record(old)[1]['phase'] == 'stop_acknowledged'
        old.close_browser()
        old.active = False
        advance_clock_to(virtual_clock, 1.0)
    assert not old.active

    current = create_profile(tmp_path / 'desktop')
    current.home, current.api_port = old.home, old.api_port
    current.active = True
    old.profiles[WINDOW] = current
    old.ports_hook = lambda request: request.respond_json({})
    code, output = finish_any(controlled(current, 1, 'tiktok', clock=virtual_clock))
    assert code == 1 and '未包含该窗口的调试端口' in output and '旧窗口' not in output
    old.ports_hook = None
    joined = controlled(current, 1, 'tiktok', clock=virtual_clock)
    current.entered('tiktok', joined)
    assert old.opens == [{'id': WINDOW}] and old.closes == [WINDOW]
    current.finish('tiktok', joined)
    assert old.closes == [WINDOW, WINDOW]


def test_uncertain_close_preserves_main_result_and_exposes_port_error(profile, virtual_clock):
    profile.stop_hook = lambda request, target: request.send_error(504)
    first = controlled(profile, 0, 'instagram', clock=virtual_clock)
    profile.entered('instagram', first)
    assert '停止或清理失败' in profile.finish('instagram', first)
    _, record = read_record(profile)
    assert record['phase'] == 'stopping'

    code, output = finish_any(controlled(profile, 1, 'tiktok', clock=virtual_clock))
    assert code == 1 and '旧窗口进程' in output and '已获回应' not in output
    profile.ports_hook = lambda request: request.send_error(404)
    profile.requests.clear()
    code, output = finish_any(controlled(profile, 1, 'tiktok', clock=virtual_clock))
    assert code == 1 and '调试端口' in output and 'HTTP 404' in output, output
    assert profile.requests.count(('ports', None)) == 1
    assert profile.opens == [{'id': WINDOW}] and profile.closes == [WINDOW]

    # The admission deadline expires before the HTTP client's read timeout.
    # stderr should still identify the precise pending operation.
    release = threading.Event()
    profile.ports_hook = lambda request: release.wait(20)
    try:
        code, output = finish_any(controlled(profile, 1, 'tiktok', clock=virtual_clock))
        assert code == 1 and '查询比特浏览器窗口调试端口超时' in output
    finally:
        release.set()


def test_close_ack_without_process_exit_reports_and_sends_no_open(profile, virtual_clock):
    profile.stop_hook = lambda request, target: request.respond_json({})
    first = controlled(profile, 0, 'instagram', clock=virtual_clock)
    profile.entered('instagram', first)
    profile.finish('instagram', first)
    _, record = read_record(profile)
    ack = float(record['stop_acknowledged_at'])
    assert profile.active

    virtual_clock.write_text(repr(ack + 1))
    successor = controlled(profile, 1, 'tiktok', clock=virtual_clock)
    code, output = finish_any(successor)
    assert code == 1 and '旧窗口进程' in output and '超时' in output, output
    assert '请先在比特浏览器桌面端关闭该窗口后重试。' in output, output
    assert 'offline-key-' not in output
    assert urlsplit(profile.endpoint).netloc not in output
    assert profile.opens == [{'id': WINDOW}]
    assert profile.closes == [WINDOW]
    assert profile.pages_requested == ['instagram']
    _, still = read_record(profile)
    assert still['phase'] == 'stop_acknowledged'
    marked = profile.browser.contexts[0].pages[0]
    marked.set_content('<textarea>desktop draft</textarea>')
    assert marked.locator('textarea').input_value() == 'desktop draft'


def test_corrupt_stop_timestamps_are_rejected_before_provider_access(profile, virtual_clock):
    profile.stop_hook = lambda request, target: request.respond_json({})
    first = controlled(profile, 0, 'instagram', clock=virtual_clock)
    profile.entered('instagram', first)
    profile.finish('instagram', first)
    record_path, saved = read_record(profile)
    assert saved['phase'] == 'stop_acknowledged'
    requests = list(profile.keys)

    for changes in ({'stop_acknowledged_at': 'soon'},
                    {'stop_acknowledged_at': -1},
                    {'stop_requested_at': None},
                    {'stop_requested_at': 'earlier'}):
        record_path.write_text(json.dumps({**saved, **changes}))
        child = controlled(profile, 1, 'tiktok', clock=virtual_clock)
        code, output = finish_any(child)
        assert code == 1 and '记录' in output, output
        assert profile.keys == requests
        assert profile.opens == [{'id': WINDOW}]
        assert profile.pages_requested == ['instagram']
        assert profile.closes == [WINDOW]


@pytest.mark.parametrize(
    'failure,warning',
    [('page', '无法关闭本命令的托管标签页'),
     ('browser', '无法断开本命令的托管浏览器连接')],
    ids=['page-cleanup', 'cdp-disconnect'],
)
def test_cleanup_failures_are_warnings_only(create_profile, failure, warning):
    profile = create_profile()
    profile.gates['tiktok'].set()
    child = controlled(profile, 0, 'tiktok',
                       page_close_failure=failure == 'page',
                       browser_close_failure=failure == 'browser')
    code, output = finish_any(child)
    assert code == 0 and 'valid' in output.splitlines(), output
    assert warning in output, output
    assert profile.closes == [WINDOW] and not profile.active


def test_close_429_preserves_success(create_profile):
    profile = create_profile()
    profile.stop_hook = lambda request, target: request.send_error(429)
    profile.gates['tiktok'].set()
    checked = controlled(profile, 0, 'tiktok')
    code, output = finish_any(checked)
    assert code == 0 and 'valid' in output.splitlines(), output
    assert '停止或清理失败' in output and profile.active


@pytest.mark.parametrize(
    'failure,warning',
    [('page', '无法关闭本命令的托管标签页'),
     ('browser', '无法断开本命令的托管浏览器连接'),
     ('close', '停止或清理失败')],
    ids=['page-cleanup', 'cdp-disconnect', 'close-429'],
)
def test_publish_attempted_survives_cleanup_failures(create_profile, tmp_path, failure, warning):
    site = CreatorSite()
    site.outcome = 'login-after'
    profile = create_profile(tmp_path / failure,
                             sites={'creator.xiaohongshu.com': site.handler()})
    if failure == 'close':
        profile.stop_hook = lambda request, target: request.send_error(429)
    media = tmp_path / 'xhs.png'
    media.touch()
    child = profile.command(
        1, 'xiaohongshu', '--title', 'draft', '--note', 'body', '--images', str(media),
        action='upload-note',
        env={**harness_env(page_close_failure=failure == 'page',
                           browser_close_failure=failure == 'browser'),
             'HUMANIZE': '0'})
    code, output = finish_any(child)
    assert code == 10, output
    assert 'publish_attempted=true' in output.splitlines(), output
    assert warning in output, output


def test_ctrl_c_exits_130_releases_the_platform_and_keeps_the_peer(create_profile, tmp_path):
    site = CreatorSite()
    profile = create_profile(sites={'creator.xiaohongshu.com': site.handler()})
    peer = profile.command(0, 'tiktok')
    profile.entered('tiktok', peer)
    peer_page, = platform_pages(profile, 'tiktok')
    peer_page.locator('textarea').fill('peer draft')

    media = tmp_path / 'xhs.png'
    media.touch()
    interrupted = profile.command(
        1, 'xiaohongshu', '--title', 'draft', '--note', 'body', '--images', str(media),
        action='upload-note', env={'HUMANIZE': '0'})
    assert site.arrived.wait(15)
    interrupted.send_signal(signal.SIGINT)
    code, output = finish_any(interrupted)
    assert code == 130, output
    assert peer.poll() is None
    assert peer_page.locator('textarea').input_value() == 'peer draft'
    assert profile.closes == []

    # The platform reservation is free while the peer continues.
    site.release.set()
    contender = profile.command(1, 'xiaohongshu')
    code, output = finish_any(contender, timeout=30)
    assert code == 0 and 'valid' in output.splitlines(), output
    assert '占用' not in output
    assert peer_page.locator('textarea').input_value() == 'peer draft'
    profile.gates['tiktok'].set()
    assert profile.finish('tiktok', peer)
    assert profile.closes == [WINDOW]
