"""Result files and real clicks across Stop failure and abrupt process death."""
import json
import sys
import threading
from contextlib import ExitStack

import pytest
from patchright.sync_api import sync_playwright

from tests.shared_publish_sites import InstagramSite
from tests.test_adspower_crash_recovery import ControlledProvider, kill_cli, platform_pages
from tests.test_shared_adspower_process import OfflineProfile, installations, profile


pytestmark = pytest.mark.skipif(sys.platform == 'win32', reason='POSIX console-script fixture')


@pytest.mark.parametrize('expected_code,expected_status', [(0, 'published'), (9, 'submission_unknown')])
def test_recovery_keeps_main_result_and_does_not_replay_interrupted_share(
        tmp_path, installations, expected_code, expected_status):
    clicked, release = threading.Event(), threading.Event()

    class Composer(InstagramSite):
        def configure(self, submission):
            if submission['caption'] == 'first command' and expected_code == 9:
                return {}  # Site received the click but cannot confirm a post.
            if submission['caption'] == 'interrupted':
                clicked.set()
                release.wait(30)
            return super().configure(submission)

    site = Composer()
    with ExitStack() as stack:
        playwright = stack.enter_context(sync_playwright())
        profile = OfflineProfile(tmp_path, stack, installations, playwright,
                                 sites={'www.instagram.com': site.handler()})
        api = ControlledProvider(profile)
        api.stop = lambda request: request.send_error(429)
        photo = tmp_path / 'photo.png'
        photo.touch()

        def publish(title, result):
            return profile.command(0, 'instagram', '--title', title, '--images', str(photo),
                                   '--result', str(result), action='upload-note', env={'HUMANIZE': '0'})

        saved = tmp_path / 'published.json'
        original = publish('first command', saved)
        output = original.communicate(timeout=20)[0]
        assert original.returncode == expected_code and '停止或清理失败' in output, output
        snapshot = saved.read_bytes()
        assert json.loads(snapshot)['status'] == expected_status
        assert api.starts == api.stops == ['shared'] and api.state == 'Active'

        incomplete = tmp_path / 'interrupted.json'
        interrupted = publish('interrupted', incomplete)
        try:
            assert clicked.wait(15)
            kill_cli(interrupted)
            pending = incomplete.read_bytes()
            assert json.loads(pending)['status'] == 'submission_unknown'
        finally:
            release.set()

        # The caller's next task is an independent check. The old composer is
        # still visible until final Stop. Count the submissions at its HTTP API.
        api.stop = api.stop_ok
        recovered = profile.command(1, 'tiktok')
        profile.entered('tiktok', recovered)
        old, = platform_pages(profile, 'instagram')
        assert old.locator('[contenteditable=true]').inner_text() == 'interrupted'
        assert [row['caption'] for row in site.submissions] == ['first command', 'interrupted']
        profile.finish('tiktok', recovered)
        assert saved.read_bytes() == snapshot and incomplete.read_bytes() == pending
        assert len(site.submissions) == 2
        assert api.starts == ['shared'] and api.stops == ['shared', 'shared'] and api.state == 'Inactive'


def test_recovery_never_creates_a_missing_result_for_an_interrupted_upload(profile, tmp_path):
    api = ControlledProvider(profile)
    starting, release = threading.Event(), threading.Event()

    def interrupted_start(request):
        api.state = 'Active'
        starting.set()
        release.wait(20)

    api.start = interrupted_start
    photo = tmp_path / 'photo.png'
    photo.touch()
    missing = tmp_path / 'never-written.json'
    child = profile.command(0, 'instagram', '--title', 'lost', '--images', str(photo),
                            '--result', str(missing), action='upload-note', env={'HUMANIZE': '0'})
    try:
        assert starting.wait(10)
        kill_cli(child)
        assert not missing.exists()
    finally:
        release.set()

    successor = profile.command(1, 'tiktok')
    profile.entered('tiktok', successor)
    profile.finish('tiktok', successor)
    assert not missing.exists() and api.starts == api.stops == ['shared']
