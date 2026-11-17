"""Hupu native-window browser evidence, with all requests fulfilled locally."""
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
from uploader.hupu_uploader import main as uploader

HTML = '''<!doctype html><meta charset="utf-8"><style>
body{margin:20px;font:16px sans-serif} button, input, textarea{padding:10px;margin:8px}
[hidden]{display:none!important} .modal{position:fixed;inset:10vh 8vw;background:white;border:2px solid black;padding:20px;z-index:10}
#spacer{height:100vh} textarea{display:block}
</style>
<button onclick="document.querySelector('#video').click()">上传视频</button><input id="video" type="file" hidden>
<input placeholder="请输入标题（最少4个字，最多40个字）" value="filename.mp4">
<textarea placeholder="请输入简介">old description</textarea>
<span onclick="document.querySelector('#cover').click()">更换封面</span><input id="cover" type="file" hidden>
<div role="region" aria-label="发视频">
<button onclick="document.querySelector('#zone').hidden=false">添加专区</button>
<div id="spacer"></div><button onclick="submitFixture()">确定发布</button></div>
<div id="zone" role="dialog" aria-label="添加专区" class="modal" hidden>
<div onclick="window.zone='步行街'">步行街</div><button onclick="window.road='步行街主干道'">步行街主干道</button>
<button onclick="document.querySelector('#zone').hidden=true">确 定</button></div>
<button onclick="window.original=true">原创/二创</button>
<button role="combobox" onclick="document.querySelector('#ai').hidden=false">选择 AI 声明</button>
<button id="ai" hidden onclick="window.ai=true;this.hidden=true">含AI生成内容</button>
<script>
window.clicks=0;
async function submitFixture(){
await fetch('/fixture-published',{method:'POST',body:JSON.stringify({
clicks:++window.clicks,title:document.querySelector('input[placeholder]').value,
desc:document.querySelector('textarea').value,video:document.querySelector('#video').files[0]?.name,
cover:document.querySelector('#cover').files[0]?.name,zone:window.zone,road:window.road,
ai:window.ai,original:window.original,width:innerWidth,height:innerHeight,scroll:scrollY})});
history.pushState({},'', '/123456.html'); }
</script>'''


class HupuNaturalViewportTests(unittest.IsolatedAsyncioTestCase):
    async def test_file_choosers_zone_dialog_and_publish_in_native_viewports(self):
        with tempfile.TemporaryDirectory() as temporary, ExitStack() as stack:
            root = Path(temporary)
            for name, value in {'BASE_DIR':root,'LOCAL_CHROME_PATH':'','LOCAL_CHROME_HEADLESS':False}.items():
                stack.enter_context(patch.object(conf, name, value, create=True))
            stack.enter_context(patch.dict(os.environ, {'HUMANIZE':'1','MLX_API_TOKEN':'','ADSPOWER_API_KEY':''}))
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
                video, cover = root/'video.mp4', root/'cover.png'
                video.touch(); cover.touch()
                for kind, flag in [('chrome','--headed'),('chromium','--headless')]:
                    base = ['--account','Fixture','--local-browser',kind,flag]
                    self.assertEqual(await sau_cli.dispatch(parser.parse_args(['hupu','login',*base])),0)
                    self.assertEqual(await sau_cli.dispatch(parser.parse_args([
                        'hupu','upload-video',*base,'--file',str(video),'--thumbnail',str(cover),
                        '--title','Fixture video title','--desc','Fixture description','--tags','test',
                    ])),0)
                self.assertEqual(len(posts),2)
                for post in posts:
                    self.assertEqual(post['title'],'Fixture video title')
                    self.assertEqual(post['desc'],'Fixture description\n#test#')
                    self.assertEqual((post['video'],post['cover']),('video.mp4','cover.png'))
                    self.assertEqual((post['zone'],post['road']),('步行街','步行街主干道'))
                    self.assertEqual(post['clicks'],1)
                    self.assertTrue(post['ai'] and post['original'])
                    self.assertGreater(post['scroll'],0)
                    self.assertGreater(post['width'],0)
                self.assertEqual(len(launches),4)
                self.assertTrue(all(call['no_viewport'] and 'viewport' not in call for call in launches))
                self.assertTrue(all(not context.browser.is_connected() for context in contexts))
                self.assertFalse((root/'cookies').exists())
