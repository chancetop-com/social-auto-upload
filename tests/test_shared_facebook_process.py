"""Installed Facebook commands sharing an offline Profile and real Chromium pages."""
import json
import sys
from contextlib import ExitStack
from html import escape
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from patchright.sync_api import sync_playwright

from tests.test_shared_adspower_process import Handler, OfflineProfile, installations


pytestmark = pytest.mark.skipif(sys.platform == 'win32', reason='POSIX console-script fixture')
FIXTURES = Path(__file__).parent / 'fixtures' / 'facebook'


class FacebookSite:
    def __init__(self):
        self.posts = []
        self.visits = []

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
                if path == '/latest/composer/':
                    self.html((FIXTURES / 'business.html').read_text())
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
                assert self.path == '/api/graphql'
                data = parse_qs(self.rfile.read(int(self.headers['Content-Length'])).decode())
                site.posts.append({k: v[0] for k, v in data.items() if k != 'fb_api_req_friendly_name'})
                creation = {'items': [{'pending_publish_content_id': '543'}]}
                self.respond(json.dumps({'data': {'xfamily_content_create': creation}}).encode(),
                             'application/json')

        return Pages


@pytest.fixture
def facebook_profile(tmp_path, installations):
    with ExitStack() as stack:
        site = FacebookSite()
        profile = OfflineProfile(tmp_path, stack, installations, stack.enter_context(sync_playwright()),
                                 sites={'business.facebook.com': site.handler()})
        yield profile, site


def test_managed_page_note_uses_exact_page_even_when_another_starts_with_its_name(facebook_profile):
    profile, site = facebook_profile
    media = profile.root / 'photo.png'
    media.touch()
    result = profile.root / 'page.json'
    child = profile.command(0, 'facebook-page', '--images', str(media), '--title', 'Page note',
                            '--page', 'Page A', '--result', str(result),
                            action='upload-note', env={'HUMANIZE': '0'})
    output = child.communicate(timeout=30)[0]
    assert child.returncode == 0, output
    assert site.posts == [{'actor': 'Page A', 'id': '111', 'caption': 'Page note', 'file': 'photo.png'}]
    record = json.loads(result.read_text())
    assert (record['status'], record['page_name'], record['page_id']) == ('published', 'Page A', '111')
