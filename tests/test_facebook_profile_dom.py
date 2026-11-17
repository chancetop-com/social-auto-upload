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


COMPOSER_HTML = '''<!doctype html><meta charset="utf-8">
<style>
body { margin: 0; font: 16px sans-serif; min-height: 180vh; }
#shade { position: fixed; inset: 0; background: #3338; z-index: 10; }
#composer { position: fixed; top: 12vh; left: 10vw; width: 70vw;
 max-height: 75vh; overflow: auto; background: white; padding: 20px; z-index: 11; }
[contenteditable] { min-height: 90px; border: 1px solid #888; padding: 10px; }
button { padding: 14px; margin: 12px; }
[hidden] { display: none !important; }
</style>
<main><input type="file" accept="image/*,video/*" multiple hidden
 onchange="document.querySelector('#shade').hidden=false;document.querySelector('#composer').hidden=false"></main>
<div id="shade" hidden></div>
<div id="composer" role="dialog" aria-modal="true" hidden><form>
<button type="button">Close</button>
<div role="textbox" contenteditable="true">Existing draft</div>
<button type="button" onclick="submitFixture()">Post</button></form></div>
<p id="success"></p>
<script>
let submitted = 0;
async function submitFixture() {
 await fetch('/fixture-published', {method:'POST', body:JSON.stringify({
   caption:document.querySelector('[contenteditable]').innerText,
   clicks:++submitted, files:[...document.querySelector('input').files].map(f=>f.name),
   width:innerWidth, height:innerHeight
 })});
 document.querySelector('#composer').hidden=true;
 document.querySelector('#shade').hidden=true;
 document.querySelector('#success').innerText='Your post has been published.';
}
</script>'''


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
