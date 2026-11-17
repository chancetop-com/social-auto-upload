"""Real Alipay interactions on intercepted fixture pages; no platform traffic."""
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
from uploader.alipay_uploader import main as uploader


HTML = '''<!doctype html><meta charset="utf-8"><style>
body { margin:20px; font:16px sans-serif; }
button, a, input, textarea, label, [role=option] { margin:12px; padding:12px; display:block; }
#spacer { height:100vh; }
.modal { position:fixed; inset:10vh 12vw; background:white; border:2px solid black; padding:20px; z-index:10; }
[hidden] { display:none !important; }
</style>
<a onclick="history.pushState({},'', '/page/content-creation/publish/short-video')">发布视频推荐分辨率720p及以上，建议1080p</a>
<input id="video" type="file" accept="video/mp4">
<input id="title" placeholder="一个好的标题，能获得更多人的喜欢哦">
<textarea id="desc" placeholder="填写作品描述，让你的作品更容易被看到"></textarea>
<button onclick="document.querySelector('#cover').hidden=false">上传封面</button>
<div id="cover" class="antd5-modal-body modal" hidden>
<input id="image" type="file" accept="image/png" hidden>
<button onclick="document.querySelector('#cover').hidden=true">完 成</button></div>
<div class="antd5-select" onclick="document.querySelector('#options').hidden=false">
<span class="antd5-select-selection-placeholder">选择合集</span><div><div><input id="fixture_compilationInfo" readonly></div></div></div>
<div id="options" hidden><div role="option" onclick="window.collection=this.innerText;document.querySelector('#options').hidden=true">Fixture collection</div></div>
<label class="antd5-radio-wrapper">内容由AI生成<input type="radio" name="ai"></label>
<div id="spacer"></div>
<button onclick="++window.clicks;document.querySelector('#quality').hidden=false">确认发布</button>
<div id="quality" class="antd5-modal-wrap modal" hidden><div>发现优化项</div><button onclick="publishFixture()">继续发布</button></div>
<script>
window.collection=''; window.clicks=0;
async function publishFixture(){
 await fetch('/fixture-published', {method:'POST', body:JSON.stringify({
  clicks:window.clicks, title:document.querySelector('#title').value,
  description:document.querySelector('#desc').value,
  video:document.querySelector('#video').files[0]?.name,
  cover:document.querySelector('#image').files[0]?.name,
  ai:document.querySelector('[type=radio]').checked,
  collection:window.collection, width:innerWidth, height:innerHeight, scroll:scrollY
 })});
 document.querySelector('#quality').hidden=true;
 history.pushState({}, '', '/page/content-creation/posts');
}
</script>'''


class AlipayNaturalViewportTests(unittest.IsolatedAsyncioTestCase):
    async def test_native_window_cover_collection_quality_overlay_and_publish(self):
        with tempfile.TemporaryDirectory() as temporary, ExitStack() as stack:
            root = Path(temporary)
            for name, value in {'BASE_DIR':root, 'LOCAL_CHROME_PATH':'', 'LOCAL_CHROME_HEADLESS':False}.items():
                stack.enter_context(patch.object(conf, name, value, create=True))
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
                    self.assertEqual(await sau_cli.dispatch(parser.parse_args(['alipay','login',*base])), 0)
                    video, cover = root/'video.mp4', root/'cover.png'
                    video.touch(); cover.touch()
                    self.assertEqual(await sau_cli.dispatch(parser.parse_args([
                        'alipay','upload-video',*base,'--file',str(video),'--thumbnail',str(cover),
                        '--title','Fixture title','--desc','Fixture description','--collection','Fixture collection',
                    ])), 0)
                self.assertEqual(len(posts), 2)
                for post in posts:
                    self.assertEqual(post['title'], 'Fixture title')
                    self.assertEqual(post['description'], 'Fixture description')
                    self.assertEqual((post['video'],post['cover']), ('video.mp4','cover.png'))
                    self.assertEqual(post['collection'], 'Fixture collection')
                    self.assertEqual(post['clicks'], 1)
                    self.assertTrue(post['ai'])
                    self.assertGreater(post['scroll'], 0)
                    self.assertGreater(post['width'], 0)
                self.assertEqual(len(launches), 4)
                self.assertTrue(all(call['no_viewport'] and 'viewport' not in call for call in launches))
                self.assertTrue(all(not context.browser.is_connected() for context in contexts))
                self.assertFalse((root/'cookies').exists())
