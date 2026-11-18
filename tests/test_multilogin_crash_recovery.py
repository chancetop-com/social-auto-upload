"""Launcher failure and process-death scenarios through installed commands."""
import json
import sys
import threading
import time
from urllib.parse import urlsplit

import pytest

from tests.test_adspower_crash_recovery import platform_pages
from tests.test_shared_multilogin_process import PROFILE, LauncherProfile, installations, mlx


pytestmark = pytest.mark.skipif(sys.platform == 'win32', reason='POSIX console-script fixture')


def test_terminal_start_rejection_allows_the_next_authorized_cli_to_start(mlx):
    mlx.start_response = lambda request: request.respond_json({}, 403)
    rejected = mlx.command(0, 'instagram')
    output = rejected.communicate(timeout=8)[0]
    assert rejected.returncode == 1 and 'start' in output, output
    assert mlx.starts == [PROFILE] and mlx.stops == [] and mlx.pages_requested == []

    mlx.start_response = None
    successor = mlx.command(1, 'instagram')
    mlx.entered('instagram', successor)
    mlx.finish('instagram', successor)
    assert mlx.starts == [PROFILE, PROFILE] and mlx.stops == [PROFILE]


def test_invalid_stop_acknowledgment_warns_and_keeps_the_old_stop_pending(mlx):
    def incomplete_reply(request):
        request.respond(json.dumps({'status': {'http_code': 500, 'error_code': 'INTERNAL_ERROR'}}).encode(),
                        'application/json')

    mlx.stop_response = incomplete_reply
    first = mlx.command(0, 'instagram')
    mlx.entered('instagram', first)
    output = mlx.finish('instagram', first)
    assert '停止或清理失败' in output
    assert mlx.active and mlx.stops == [PROFILE]

    mlx.gates['tiktok'].set()
    successor = mlx.command(1, 'tiktok')
    output = successor.communicate(timeout=18)[0]
    assert successor.returncode == 1 and '停止' in output and '超时' in output, output
    assert mlx.starts == mlx.stops == [PROFILE] and mlx.pages_requested == ['instagram']


def test_lost_start_rechecks_live_launcher_evidence_before_recovery(mlx):
    mlx.start_response = lambda request: None  # Drop the connection without a reply.
    mlx.observation_fields = {'timestamp': 1750946194258}

    def rejected(reason, *flags):
        child = mlx.command(1, 'tiktok', *flags)
        output = child.communicate(timeout=10)[0]
        assert child.returncode == 1 and reason in output, output
        assert 'offline-key-' not in output and urlsplit(mlx.endpoint).netloc not in output
        assert mlx.starts == [PROFILE] and not mlx.stops and not mlx.pages_requested

    rejected('start')
    mlx.start_response = None
    rejected('尚未确认')
    # Launcher documents a status timestamp, but no request ID or terminal
    # generation. Even a newer stopped snapshot cannot correlate this Start.
    mlx.observation_fields['timestamp'] += 50
    rejected('尚未确认')
    mlx.observation_fields = {'status': 'start_browser'}
    rejected('正在启动')
    mlx.observation_fields = {'status': 'unrecognized-offline-key-secret'}
    rejected('无法确认')
    mlx.active = True
    mlx.observation_fields = {'message': '1'}
    rejected('连接不可用')
    mlx.observation_fields = {}
    recovered = mlx.command(0, 'tiktok')
    mlx.entered('tiktok', recovered)
    mlx.finish('tiktok', recovered)
    assert mlx.starts == mlx.stops == [PROFILE] and not mlx.active


def replacement_browser(mlx):
    root = mlx.root / 'replacement'
    root.mkdir()
    current = LauncherProfile(root, mlx.stack, mlx.entries, mlx.playwright)
    assert current.endpoint != mlx.endpoint
    return current


def test_lost_start_can_restart_once_after_running_instance_seen_then_stopped(mlx):
    mlx.start_response = lambda request: None
    lost = mlx.command(0, 'instagram')
    assert 'start' in lost.communicate(timeout=8)[0] and lost.returncode == 1

    # A current, authenticated browser and its CDP identity establish that the
    # pending Start finished, even if the CLI cannot join with its requested settings.
    mlx.active = True
    observer = mlx.command(1, 'instagram', '--headless')
    assert 'headless' in observer.communicate(timeout=8)[0] and observer.returncode == 1
    assert mlx.starts == [PROFILE] and not mlx.stops and not mlx.pages_requested
    mlx.close_browser()
    current = replacement_browser(mlx)
    mlx.profiles[PROFILE] = current
    recovered = mlx.command(0, 'instagram')
    current.entered('instagram', recovered)
    current.finish('instagram', recovered)
    assert current.starts == current.stops == [PROFILE] and not current.active


@pytest.mark.parametrize('outcome', ['stopped', 'desktop-reopened', 'still-in-flight'])
def test_free_platform_waits_for_pending_stop_and_uses_the_current_browser(mlx, outcome):
    current = replacement_browser(mlx)
    desktop = current.browser.contexts[0].pages[0]
    desktop.set_content('<textarea>replacement browser</textarea>')
    stopping, release = threading.Event(), threading.Event()

    def delayed_stop(request):
        stopping.set()
        release.wait(25)
        mlx.close_browser()
        mlx.active = False
        current.active = outcome == 'desktop-reopened'
        mlx.profiles[PROFILE] = current
        request.respond_json({})

    mlx.stop_response = delayed_stop
    original = mlx.command(0, 'instagram')
    mlx.entered('instagram', original)
    mlx.gates['instagram'].set()
    assert stopping.wait(8)
    try:
        # One contender holds the released platform reservation while waiting
        # for Stop. Its peer immediately reports busy, before either opens a tab.
        candidates = [mlx.command(i, 'instagram') for i in (0, 1)]
        deadline = time.monotonic() + 7
        while all(p.poll() is None for p in candidates) and time.monotonic() < deadline:
            time.sleep(.05)
        waiting, = [p for p in candidates if p.poll() is None]
        busy, = [p for p in candidates if p.poll() is not None]
        assert busy.returncode == 1 and '占用' in busy.communicate()[0]
        assert mlx.starts == mlx.stops == [PROFILE] and not current.pages_requested
        if outcome == 'still-in-flight':
            output = waiting.communicate(timeout=13)[0]
            assert waiting.returncode == 1 and '停止' in output and '超时' in output
            assert not current.starts and not current.stops and not current.pages_requested
    finally:
        release.set()
    mlx.finish('instagram', original)
    if outcome != 'still-in-flight':
        current.entered('instagram', waiting)
        page, = platform_pages(current, 'instagram')
        assert page.locator('textarea').input_value() == 'draft'
        assert desktop.locator('textarea').input_value() == 'replacement browser'
        current.finish('instagram', waiting)
        assert current.starts == ([] if outcome == 'desktop-reopened' else [PROFILE])
        assert current.stops == [PROFILE] and current.chrome.poll() is not None


def test_stop_success_response_precedes_browser_exit_and_desktop_reopen(mlx):
    current = replacement_browser(mlx)
    mlx.stop_response = lambda request: request.respond_json({})
    original = mlx.command(0, 'instagram')
    mlx.entered('instagram', original)
    mlx.finish('instagram', original)
    assert mlx.active and mlx.starts == mlx.stops == [PROFILE]
    prior_reads = len([op for op, _ in mlx.requests if op == 'status'])
    successor = mlx.command(1, 'tiktok')
    # Two reads of the original browser establish that the joining CLI is
    # polling. An immediate attach instead reaches the old TikTok page.
    deadline = time.monotonic() + 8
    while sum(op == 'status' for op, _ in mlx.requests) < prior_reads + 2:
        assert mlx.pages_requested == ['instagram']
        assert time.monotonic() < deadline
        time.sleep(.05)
    assert mlx.pages_requested == ['instagram']
    mlx.close_browser()
    current.active = True
    mlx.profiles[PROFILE] = current
    current.entered('tiktok', successor)
    current.finish('tiktok', successor)
    assert not current.starts and current.stops == [PROFILE]
