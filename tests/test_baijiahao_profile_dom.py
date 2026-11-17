"""Real native-window interactions against locally fulfilled Baijiahao fixture DOM.

No account, external platform requests, or actual posts are involved.
"""
import json
import os
from contextlib import ExitStack
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from patchright.async_api import async_playwright
import conf
import sau_cli
from uploader.baijiahao_uploader import main as uploader


HTML = '''<!doctype html><meta charset="utf-8"><style>
body { margin: 20px; font: 16px sans-serif; }
button, .cheetah-select, .cheetah-select-item { padding: 12px; margin: 10px; }
.contentEditable { border: 1px solid #888; padding: 15px; min-height: 40px; }
#spacer { height: 100vh; }
.modal { position: fixed; inset: 10vh 20vw; background: white; border: 2px solid black; padding: 20px; z-index: 10; }
[hidden] { display:none !important; }
</style>
<a href="/builder/rc/edit">发布视频</a>
<input id="video" type="file" accept="video/mp4">
<div class="contentEditable" contenteditable="true">filename.mp4</div>
<div id="progress">50%</div>
<button data-testid="select-cover" onclick="document.querySelector('#cover').hidden=false">选择封面</button>
<div id="cover" class="modal" hidden>
<input id="image" type="file" accept="image/png" hidden>
<button onclick="document.querySelector('#cover').hidden=true">确定</button></div>
<div class="cheetah-select" onclick="document.querySelector('#declaration').hidden=false">
<input placeholder="请选择创作声明" readonly></div>
<div id="declaration" class="cheetah-modal-wrap modal" hidden>
<button onclick="window.ai=true">含AI生成内容</button>
<button onclick="document.querySelector('#declaration').hidden=true">确定</button></div>
<div class="cheetah-select" onclick="document.querySelector('#options').hidden=false">
<span class="cheetah-select-selection-placeholder">选择同主题的合集</span>
<input class="cheetah-select-selection-search-input"></div>
<div id="options" hidden>
<div class="cheetah-select-item" onclick="window.collection=this.innerText">Exact collection</div>
<div class="cheetah-select-item">Exact collection extended</div></div>
<div id="spacer"></div>
<button data-testid="publish-btn" onclick="publishFixture()">发布</button>
<script>
window.ai=false; window.collection=''; window.clicks=0;
document.querySelector('[contenteditable]').addEventListener('input',()=>{
 setTimeout(()=>document.querySelector('#progress').innerText='100%', 1500);
});
async function publishFixture(){
 await fetch('/fixture-published', {method:'POST', body:JSON.stringify({
  clicks:++window.clicks, title:document.querySelector('[contenteditable]').innerText,
  video:document.querySelector('#video').files[0]?.name,
  cover:document.querySelector('#image').files[0]?.name,
  ai:window.ai, collection:window.collection, width:innerWidth, height:innerHeight,
  scroll:scrollY
 })});
 history.pushState({}, '', '/builder/rc/clue');
}
</script>'''


class BaijiahaoNaturalViewportTests(unittest.IsolatedAsyncioTestCase):
    async def test_cover_declaration_collection_and_submit_in_native_viewports(self):
        with tempfile.TemporaryDirectory() as temporary, ExitStack() as stack:
            root = Path(temporary)
            for name, value in {'BASE_DIR':root, 'LOCAL_CHROME_PATH':'', 'LOCAL_CHROME_HEADLESS':False}.items():
                stack.enter_context(patch.object(conf, name, value))
            stack.enter_context(patch.dict(os.environ, {'HUMANIZE':'1', 'MLX_API_TOKEN':'', 'ADSPOWER_API_KEY':''}))
            posts, launches, contexts = [], [], []
            async with async_playwright() as real:
                async def launch(**kwargs):
                    launches.append(kwargs)
                    context = await real.chromium.launch_persistent_context(**kwargs)
                    contexts.append(context)
                    async def route(request_route):
                        if request_route.request.url.endswith('/fixture-published'):
                            posts.append(json.loads(request_route.request.post_data))
                            await request_route.fulfill(status=200, body='ok')
                        else:
                            await request_route.fulfill(status=200, content_type='text/html', body=HTML)
                    await context.route('**/*', route)
                    return context
                class Factory:
                    async def __aenter__(self):
                        return SimpleNamespace(chromium=SimpleNamespace(launch_persistent_context=launch))
                    async def __aexit__(self, *_): pass
                stack.enter_context(patch.object(uploader, 'async_playwright', Factory))
                parser = sau_cli.build_parser()
                for kind, flag in [('chrome','--headed'), ('chromium','--headless')]:
                    base = ['--account','Fixture', '--local-browser',kind, flag]
                    self.assertEqual(await sau_cli.dispatch(parser.parse_args(['baijiahao','login',*base])), 0)
                    video, cover = root/'video.mp4', root/'cover.png'
                    video.touch(); cover.touch()
                    self.assertEqual(await sau_cli.dispatch(parser.parse_args([
                        'baijiahao','upload-video',*base,'--file',str(video),'--thumbnail',str(cover),
                        '--title','Fixture video title','--collection','Exact collection',
                    ])), 0)
                self.assertEqual(len(posts), 2)
                for post in posts:
                    self.assertEqual(post['title'], 'Fixture video title')
                    self.assertEqual((post['video'],post['cover']), ('video.mp4','cover.png'))
                    self.assertEqual(post['collection'], 'Exact collection')
                    self.assertEqual(post['clicks'], 1)
                    self.assertTrue(post['ai'])
                    self.assertGreater(post['scroll'], 0)
                    self.assertGreater(post['width'], 0)
                self.assertEqual(len(launches), 4)
                self.assertTrue(all(call['no_viewport'] and 'viewport' not in call for call in launches))
                self.assertTrue(all(not context.browser.is_connected() for context in contexts))
                self.assertFalse((root/'cookies').exists())
