"""Installed Facebook commands sharing an offline Profile and real Chromium pages."""
import json
import sys
import threading
from contextlib import ExitStack, contextmanager
from html import escape
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from uuid import UUID

import pytest
from patchright.sync_api import sync_playwright

from tests.shared_publish_sites import InstagramSite
from tests.test_shared_adspower_process import Handler, OfflineProfile, installations
from tests.test_shared_instagram_tiktok import matching_page
from tests.test_xhs_rednote_sharing import advance, finish, wait_for


pytestmark = pytest.mark.skipif(sys.platform == 'win32', reason='POSIX console-script fixture')
FIXTURES = Path(__file__).parent / 'fixtures' / 'facebook'


class FacebookSite:
    def __init__(self):
        self.posts = []
        self.page_response = threading.Event()
        self.page_response.set()
        self.page_unknown = False
        self.page_expires_on_submit = False
        self.visits = []
        self.personal_posts = []
        self.personal_outcome = "ok"
        self.logged_out = False

    def handler(self):
        site = self

        class Pages(Handler):
            def html(self, html):
                self.respond(html.encode(), 'text/html; charset=utf-8')

            def do_GET(self):
                path = urlsplit(self.path).path
                if path == '/favicon.ico':
                    self.respond(b'', 'image/x-icon')
                    return
                site.visits.append(path)
                if site.logged_out:
                    self.html('<input name="email">')
                elif path == '/':
                    self.html((FIXTURES / 'personal.html').read_text())
                elif path == '/login/':
                    self.html('<input name="email">')
                elif path == '/latest/composer/':
                    composer = (FIXTURES / 'business.html').read_text()
                    if site.page_expires_on_submit:
                        composer += '''<script>
                            document.addEventListener('click', e => {
                                if (e.target.textContent === 'Publish') history.replaceState({}, '', '/login/');
                            }, true);
                        </script>'''
                    self.html(composer)
                elif path == '/latest/posts/published_posts':
                    post = site.posts[-1]
                    link = '/latest/object_insights/?asset_id=' + post['id'] + '&amp;content_id=543'
                    self.html('<div role="row">' + escape(post['actor']) +
                              f'<a role="gridcell" data-surface="post:TITLE" href="{link}">' +
                              escape(post['caption']) + '</a></div>')
                elif path == '/latest/object_insights/':
                    self.html('<div data-surface="BizWebObjectinsightsHeaderActionDropdown">'
                              '<button aria-haspopup="menu">Menu</button></div>')
                else:
                    self.send_error(404)

            def do_POST(self):
                if self.path == '/fixture-published':
                    site.personal_posts.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))))
                    self.respond(site.personal_outcome.encode(), 'text/plain')
                    return
                assert self.path == '/api/graphql'
                data = parse_qs(self.rfile.read(int(self.headers['Content-Length'])).decode())
                site.posts.append({k: v[0] for k, v in data.items() if k != 'fb_api_req_friendly_name'})
                site.page_response.wait(20)
                creation = {} if site.page_unknown else {'items': [{'pending_publish_content_id': '543'}]}
                try:
                    self.respond(json.dumps({'data': {'xfamily_content_create': creation}}).encode(),
                                 'application/json')
                except OSError:
                    pass  # The response may have been deliberately interrupted by closing its tab.

        return Pages


@pytest.fixture
def facebook_profile(tmp_path, installations):
    with ExitStack() as stack:
        site = FacebookSite()
        profile = OfflineProfile(tmp_path, stack, installations, stack.enter_context(sync_playwright()),
                                 sites={'www.facebook.com': site.handler(), 'business.facebook.com': site.handler()})
        yield profile, site


def test_managed_page_note_uses_exact_page_even_when_another_starts_with_its_name(facebook_profile):
    profile, site = facebook_profile
    media = profile.root / 'photo.png'
    media.touch()
    result = profile.root / 'page.json'
    with peer_draft(profile):
        child = profile.command(1, 'facebook-page', '--images', str(media), '--title', 'Page note',
                            '--page', 'Page A', '--result', str(result),
                            action='upload-note', env={'HUMANIZE': '0'})
        finish(child, 0)
    assert site.posts == [{'actor': 'Page A', 'id': '111', 'caption': 'Page note', 'file': 'photo.png'}]
    record = json.loads(result.read_text())
    assert (record['status'], record['page_name'], record['page_id']) == ('published', 'Page A', '111')


@contextmanager
def peer_draft(profile):
    desktop, = profile.browser.contexts[0].pages
    child = profile.command(0, 'instagram')
    profile.entered('instagram', child)
    peer = matching_page(profile, lambda p: 'instagram.com' in p.url, child)
    editor = peer.locator('textarea')
    editor.fill('Instagram peer draft')
    url = peer.url
    yield
    assert profile.starts == ['shared'] and not profile.stops
    assert peer.url == url and editor.input_value() == 'Instagram peer draft'
    editor.fill('Instagram peer can still edit')
    assert editor.input_value() == 'Instagram peer can still edit'
    assert set(profile.browser.contexts[0].pages) == {peer, desktop}
    profile.finish('instagram', child)
    assert profile.stops == ['shared']


@pytest.mark.parametrize(('outcome', 'code'), [('ok', 0), ('login', 10)])
def test_personal_video_reports_its_submission_and_preserves_peer_draft(facebook_profile, outcome, code):
    profile, site = facebook_profile
    site.personal_outcome = outcome
    media = profile.root / 'clip.mp4'
    media.touch()
    with peer_draft(profile):
        child = profile.command(1, 'facebook', '--file', str(media), '--title', 'My video',
                                action='upload-video', env={'HUMANIZE': '0'})
        output = finish(child, code)
        assert ('publish_attempted=true' in output.splitlines()) == (outcome == 'login')
        post, = site.personal_posts
        assert (post['actor'], post['files'], post['clicks']) == ('Personal author', ['clip.mp4'], 1)


@pytest.mark.parametrize(('platform', 'path'), [('facebook', '/'), ('facebook-page', '/latest/composer/')])
@pytest.mark.parametrize('logged_out', [False, True], ids=['valid', 'logged-out'])
def test_facebook_checks_only_close_their_own_probe(facebook_profile, platform, path, logged_out):
    profile, site = facebook_profile
    site.logged_out = logged_out
    with peer_draft(profile):
        output = finish(profile.command(1, platform), 10 if logged_out else 0)
        assert ('valid' in output.splitlines()) == (not logged_out)
        assert site.visits == [path]


def waiting_note(profile, installation, platform, *, when, title, extra=()):
    media = profile.root / (platform + '.png')
    media.touch()
    gate = profile.root / ('waiting-' + platform)
    child = profile.command(
        installation, platform, '--images', str(media), '--title', title,
        '--not-before', f'2030-01-01T00:00:{when:02d}Z', *extra, action='upload-note',
        env={'HUMANIZE': '0', 'PYTHONPATH': str(FIXTURES.parent / 'publish_clock'),
             'SAU_TEST_CLOCK': str(profile.root / 'clock'), 'SAU_TEST_GATE_ENTERED': str(gate)},
    )
    wait_for(gate.exists, child)
    return child


def test_personal_editor_keeps_its_author_while_page_selects_waits_and_submits(facebook_profile):
    profile, site = facebook_profile
    advance(profile, 0)
    personal = waiting_note(profile, 0, 'facebook', when=20, title='Personal note')
    page = matching_page(profile, lambda p: 'www.facebook.com' in p.url, personal)

    def personal_draft():
        return (page.locator('#actor').inner_text(), page.locator('#actor').get_attribute('href'),
                page.locator('[contenteditable]').inner_text())
    expected = ('Personal author', '/profile.php?id=777', 'Personal note')
    assert personal_draft() == expected

    business = waiting_note(profile, 1, 'facebook-page', when=10, title='Business note',
                            extra=('--page', 'Page A'))
    composer = matching_page(profile, lambda p: 'business.facebook.com' in p.url, business)
    assert personal_draft() == expected
    assert (composer.get_by_role('combobox').inner_text(), urlsplit(composer.url).query,
            composer.locator('[contenteditable]').inner_text()) == ('Page A', 'asset_id=111', 'Business note')
    assert not site.posts and not site.personal_posts

    visits = list(site.visits)
    opened = []
    profile.browser.contexts[0].on('page', lambda new_page: opened.append(new_page))
    other = profile.command(0, 'facebook-page', '--images', str(profile.root / 'facebook-page.png'),
                            '--title', 'Other draft', '--page', 'Page AB', action='upload-note')
    output = finish(other, 1)
    assert 'facebook-page' in output and '占用' in output
    assert personal_draft() == expected
    assert site.visits == visits and opened == []

    advance(profile, 10)
    finish(business, 0)
    assert not profile.stops and not site.personal_posts
    assert site.posts == [{'actor': 'Page A', 'id': '111', 'caption': 'Business note',
                           'file': 'facebook-page.png'}]
    assert personal_draft() == expected
    assert composer.is_closed()
    page.locator('[contenteditable]').fill('Personal note continued')
    advance(profile, 20)
    finish(personal, 0)
    post, = site.personal_posts
    assert (post['actor'], post['id'], post['caption'], post['clicks']) == (
        'Personal author', '777', 'Personal note continued', 1)
    assert profile.starts == profile.stops == ['shared']


@pytest.mark.parametrize(('unknown', 'code', 'status'), [(False, 0, 'processing'), (True, 9, 'submission_unknown')])
def test_page_video_uses_its_own_preview_and_observes_only_its_submission(facebook_profile, unknown, code, status):
    profile, site = facebook_profile
    site.page_unknown = unknown
    media = profile.root / 'reel.mp4'
    media.touch()
    result = profile.root / 'page.json'
    with peer_draft(profile):
        child = profile.command(1, 'facebook-page', '--file', str(media), '--page', 'Page A',
                                '--title', 'My reel', '--result', str(result),
                                action='upload-video', env={'HUMANIZE': '0'})
        finish(child, code)
        assert site.visits == ['/latest/composer/', '/latest/composer/']
        assert site.posts == [{'actor': 'Page A', 'id': '111', 'caption': 'My reel', 'file': 'reel.mp4'}]
        assert json.loads(result.read_text())['status'] == status


def test_personal_submission_losing_its_page_is_unknown_and_never_retried(facebook_profile):
    profile, site = facebook_profile
    site.personal_outcome = 'unconfirmed'
    media = profile.root / 'photo.png'
    media.touch()
    with peer_draft(profile):
        child = profile.command(1, 'facebook', '--images', str(media), '--title', 'My photo',
                                action='upload-note', env={'HUMANIZE': '0'})
        wait_for(lambda: bool(site.personal_posts), child)
        editor = matching_page(profile, lambda p: 'www.facebook.com' in p.url, child)
        editor.close()
        finish(child, 9)
        assert [post['clicks'] for post in site.personal_posts] == [1]


@pytest.mark.parametrize('paths', ['defaults', 'explicit', 'same'])
def test_instagram_and_page_results_follow_each_independent_command(tmp_path, installations, paths):
    with ExitStack() as stack:
        instagram, facebook = InstagramSite(), FacebookSite()
        profile = OfflineProfile(tmp_path, stack, installations, stack.enter_context(sync_playwright()), sites={
            'www.instagram.com': instagram.handler(), 'business.facebook.com': facebook.handler(),
        })
        advance(profile, 0)
        ig_path = tmp_path / 'ig.json'
        page_path = ig_path if paths == 'same' else tmp_path / 'business.json'
        ig_flags = () if paths == 'defaults' else ('--result', str(ig_path))
        page_flags = () if paths == 'defaults' else ('--result', str(page_path))
        ig = waiting_note(profile, 0, 'instagram', when=10, title='Instagram photo', extra=ig_flags)
        page = waiting_note(profile, 0, 'facebook-page', when=20, title='Page photo',
                            extra=('--page', 'Page A', *page_flags))
        assert not instagram.submissions and not facebook.posts

        advance(profile, 10)
        finish(ig, 0)
        assert not profile.stops and page.poll() is None
        assert not facebook.posts
        if paths == 'defaults':
            ig_path, = (tmp_path / 'cwd-0/.local/instagram-results').glob('*.json')
            assert UUID(ig_path.stem).version == 4
        ig_record = json.loads(ig_path.read_text())
        assert (ig_record['platform'], ig_record['status'], ig_record['title']) == (
            'instagram', 'published', 'Instagram photo')

        advance(profile, 20)
        finish(page, 0)
        if paths == 'defaults':
            page_path, = (tmp_path / 'cwd-0/.local/meta-results').glob('*.json')
            assert UUID(page_path.stem).version == 4 and page_path.stem != ig_path.stem
        page_record = json.loads(page_path.read_text())
        assert (page_record['platform'], page_record['status'], page_record['title'], page_record['page_id']) == (
            'facebook-page', 'published', 'Page photo', '111')
        assert json.loads(ig_path.read_text()) == (page_record if paths == 'same' else ig_record)
        assert instagram.submissions == [{'caption': 'Instagram photo', 'files': ['instagram.png']}]
        assert [post['caption'] for post in facebook.posts] == ['Page photo']
        assert profile.starts == profile.stops == ['shared']


def test_page_target_change_during_wait_stops_before_submit(facebook_profile):
    profile, site = facebook_profile
    advance(profile, 0)
    result = profile.root / 'page.json'
    with peer_draft(profile):
        business = waiting_note(profile, 1, 'facebook-page', when=10, title='For Page A',
                                extra=('--page', 'Page A', '--result', str(result)))
        page = matching_page(profile, lambda p: 'business.facebook.com' in p.url, business)
        page.get_by_role('combobox').click()
        page.get_by_role('option', name='Page AB', exact=True).click()
        assert urlsplit(page.url).query == 'asset_id=222'
        advance(profile, 10)
        finish(business, 1)
        assert not site.posts
        assert json.loads(result.read_text())['status'] == 'not_submitted'


def test_page_submission_detects_login_redirect_and_keeps_attempt_marker(facebook_profile):
    profile, site = facebook_profile
    site.page_unknown = site.page_expires_on_submit = True
    photo = profile.root / 'photo.png'
    photo.touch()
    with peer_draft(profile):
        child = profile.command(1, 'facebook-page', '--images', str(photo), '--title', 'Expiring Page',
                                action='upload-note', env={'HUMANIZE': '0'})
        output = finish(child, 10)
        assert 'publish_attempted=true' in output.splitlines()
        assert [post['caption'] for post in site.posts] == ['Expiring Page']


@pytest.mark.parametrize('login, code', [(False, 9), (True, 10)])
def test_page_target_lost_while_waiting_for_creation_response(facebook_profile, login, code):
    profile, site = facebook_profile
    site.page_expires_on_submit = login
    site.page_response.clear()
    photo = profile.root / 'photo.png'
    photo.touch()
    result = profile.root / 'page.json'
    with peer_draft(profile):
        child = profile.command(1, 'facebook-page', '--images', str(photo), '--title', 'Page note',
                                '--result', str(result), action='upload-note', env={'HUMANIZE': '0'})
        try:
            wait_for(lambda: bool(site.posts), child)
            page = matching_page(profile, lambda p: 'business.facebook.com' in p.url, child)
            page.close()
            output = finish(child, code)
        finally:
            site.page_response.set()
        assert ('publish_attempted=true' in output.splitlines()) == login
        assert json.loads(result.read_text())['status'] == 'submission_unknown'
        assert [post['caption'] for post in site.posts] == ['Page note']
