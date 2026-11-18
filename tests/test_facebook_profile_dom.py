"""Controlled Facebook DOM through the formal CLI and real persistent browser.

Every browser request is fulfilled locally. No Facebook account, remote upload,
or real publication is used; the fixture reports an in-page submit event.
"""
import json
import os
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from patchright.async_api import async_playwright
import conf
import sau_cli
from uploader.meta_uploader.facebook_uploader import main


COMPOSER_HTML = (Path(__file__).parent / 'fixtures' / 'facebook' / 'personal.html').read_text()


class FacebookNaturalViewportTests(unittest.IsolatedAsyncioTestCase):
    async def test_video_and_note_use_natural_viewport_composer_with_overlay(self):
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            root = Path(directory)
            stack.enter_context(patch.object(conf, 'BASE_DIR', root))
            stack.enter_context(patch.object(conf, 'LOCAL_CHROME_PATH', ''))
            stack.enter_context(patch.dict(os.environ, {'MLX_API_TOKEN':'', 'ADSPOWER_API_KEY':'', 'HUMANIZE':'1'}))
            submitted, launches, contexts = [], [], []
            async with async_playwright() as real:
                async def launch(**kwargs):
                    launches.append(kwargs)
                    context = await real.chromium.launch_persistent_context(**kwargs)
                    contexts.append(context)
                    async def route(request_route):
                        if request_route.request.url.endswith('/fixture-published'):
                            submitted.append(json.loads(request_route.request.post_data))
                            await request_route.fulfill(status=200, body='ok')
                        else:
                            await request_route.fulfill(status=200, content_type='text/html', body=COMPOSER_HTML)
                    await context.route('**/*', route)
                    return context
                class Factory:
                    async def __aenter__(self):
                        return SimpleNamespace(chromium=SimpleNamespace(launch_persistent_context=launch))
                    async def __aexit__(self, *args): pass
                stack.enter_context(patch.object(main, 'async_playwright', Factory))
                for browser_kind in ('chrome', 'chromium'):
                    with self.subTest(browser=browser_kind):
                        base = ['--account','fixture','--local-browser',browser_kind,'--headless']
                        parser = sau_cli.build_parser()
                        self.assertEqual(await sau_cli.dispatch(parser.parse_args(['facebook','login',*base])), 0)
                        for action, option, filename in [('upload-video','--file','video.mp4'), ('upload-note','--images','photo.png')]:
                            path = root / filename; path.touch()
                            self.assertEqual(await sau_cli.dispatch(parser.parse_args([
                                'facebook', action, *base, option, str(path), '--title','标题',
                            ])), 0)
                self.assertEqual(len(submitted), 4)
                self.assertEqual([entry['files'] for entry in submitted], [['video.mp4'],['photo.png']]*2)
                self.assertTrue(all(entry['caption']=='标题' and entry['clicks']==1 for entry in submitted))
                self.assertTrue(all(entry['width']>0 and entry['height']>0 for entry in submitted))
                self.assertEqual(len(launches), 6)
                self.assertTrue(all(call['no_viewport'] and 'viewport' not in call for call in launches))
                self.assertTrue(all(not context.browser.is_connected() for context in contexts))
                self.assertFalse((root/'cookies').exists())
