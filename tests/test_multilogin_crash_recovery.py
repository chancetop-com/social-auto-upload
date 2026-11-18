"""Launcher failure and process-death scenarios through installed commands."""
import json
import sys

import pytest

from tests.test_shared_multilogin_process import PROFILE, installations, mlx


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
