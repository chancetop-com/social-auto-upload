"""Real browser, isolated profiles, and fulfilled fixture pages; no platform traffic."""
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
from uploader.weibo_uploader import main as uploader
from utils.dom import ElementUnusableError
from utils.errors import LoginRequiredError


HOME = '''<!doctype html><meta charset="utf-8"><div class="Nav_avatar">Fixture account</div>
<span style="display:inline-block;padding:30px" onclick="window.open('/publish')">视频</span>'''
PUBLISH = '''<!doctype html><meta charset="utf-8"><style>
body {margin:15px; font:16px sans-serif} button, label, .woo-pop-ctrl {padding:12px; margin:10px}
input:not([type=file]),textarea {display:block; width:85%; padding:14px; margin:10px}
.modal {position:fixed; inset:15vh 12vw; background:white; border:2px solid black; z-index:10; padding:10px}
[hidden] {display:none !important} #spacer {height:110vh} #publish {width:240px; margin:0} ._check_2z30i {width:240px; position:relative}
#mask {position:absolute; width:45%; inset:0 0 0 auto; z-index:2; background:#ddd}
#overlay {position:fixed; inset:0; z-index:20; background:#3336}
</style>
<input id="video" type="file" accept="video/mp4" hidden>
<button onclick="document.querySelector('#video').click()">上传视频</button>
<div><i class="woo-font--check"></i><span>上传完成</span></div>
<label class="woo-radio-main" onclick="this.querySelector('.woo-radio-text').classList.add('woo-radio-checked')">
<span class="woo-radio-text">二创</span></label>
<div class="_gap1_nsgmr"><div class="woo-pop-ctrl" onclick="document.querySelector('#declaration').hidden=false">声明</div></div>
<div id="declaration" class="_panel_nsgmr modal" hidden>
<button onclick="this.querySelector('i').className='_checkActive'"><span>含AI生成内容</span><i></i></button>
<div class="_footer_nsgmr"><button onclick="document.querySelector('#declaration').hidden=true"><span>确定</span></button></div></div>
<div class="wbpro-layer _layer_19x8d">
<input id="title" placeholder="填写标题（0～30个字）" value="filename.mp4">
<a href="#" onclick="document.querySelector('#cover').hidden=false; return false">上传封面</a>
<textarea id="desc" placeholder="有什么新鲜事想分享给大家？"></textarea>
<div id="spacer"></div><div class="_check_2z30i"><button id="publish" onclick="publishFixture()"><span>发布</span></button><div id="mask"></div></div>
</div>
<div id="cover" class="wbpro-layer modal" hidden><div>编辑封面</div>
<input id="image" type="file" accept="image/jpg" hidden><div class="cropper-container"><img src="blob:fixture"></div>
<div class="wbpro-layer-btn"><button onclick="document.querySelector('#cover').hidden=true"><span>完成</span></button></div></div>
<div id="overlay" hidden></div>
<div id="success" class="_layer1_9a8j7" hidden><button><span>再发一条视频</span></button></div>
<script>
window.clicks=0;
// A leftover dropdown overlay appears after description entry. Escape must clear it.
document.querySelector('#desc').oninput=()=>document.querySelector('#overlay').hidden=false;
window.addEventListener('keydown',event=>{if(event.key==='Escape') document.querySelector('#overlay').hidden=true});
async function publishFixture(){
 await fetch('/fixture-published', {method:'POST',body:JSON.stringify({
  clicks:++window.clicks,title:document.querySelector('#title').value,desc:document.querySelector('#desc').value,
  video:document.querySelector('#video').files[0]?.name,cover:document.querySelector('#image').files[0]?.name,
  second:document.querySelector('.woo-radio-checked')!==null,ai:document.querySelector('._checkActive')!==null,
  width:innerWidth,height:innerHeight,scroll:scrollY,overlay:!document.querySelector('#overlay').hidden
 })});
 if(window.failure==='redirect') history.pushState({}, '', '/verify');
 else document.querySelector('#success').hidden=false;
}
</script>'''


class WeiboNativeWindowTests(unittest.IsolatedAsyncioTestCase):
    async def test_small_native_window_scroll_overlay_and_submit_boundaries(self):
        with tempfile.TemporaryDirectory() as temporary, ExitStack() as stack:
            root = Path(temporary)
            for key,value in {'BASE_DIR':root,'LOCAL_CHROME_PATH':'','LOCAL_CHROME_HEADLESS':False}.items():
                stack.enter_context(patch.object(conf,key,value))
            stack.enter_context(patch.dict(os.environ, {'HUMANIZE':'1','MLX_API_TOKEN':'','ADSPOWER_API_KEY':''}))
            posts, launches, contexts = [], [], []
            scenario = {'failure':''}
            async with async_playwright() as real:
                async def launch(**kwargs):
                    launches.append(kwargs)
                    context = await real.chromium.launch_persistent_context(**kwargs)
                    contexts.append(context)
                    async def route(request_route):
                        url = request_route.request.url
                        if url.endswith('/fixture-published'):
                            posts.append(json.loads(request_route.request.post_data))
                            await request_route.fulfill(status=200,body='ok')
                        elif url.endswith('/publish'):
                            content = PUBLISH + '<script>window.failure=' + json.dumps(scenario['failure']) + ';</script>'
                            if scenario['failure']=='blocked':
                                content += '<style>#mask {width:100%}</style>'
                            await request_route.fulfill(status=200,content_type='text/html',body=content)
                        else:
                            await request_route.fulfill(status=200,content_type='text/html',body=HOME)
                    await context.route('**/*', route)
                    if not kwargs['headless']:
                        # Test driver models a user-resized window; production has no window override.
                        page = context.pages[0]
                        cdp = await context.new_cdp_session(page)
                        window = await cdp.send('Browser.getWindowForTarget')
                        await cdp.send('Browser.setWindowBounds', {'windowId':window['windowId'],
                                                                 'bounds':{'width':800,'height':650}})
                        await cdp.detach()
                    return context
                class Factory:
                    async def __aenter__(self): return SimpleNamespace(chromium=SimpleNamespace(launch_persistent_context=launch))
                    async def __aexit__(self,*_): pass
                stack.enter_context(patch.object(uploader,'async_playwright',Factory))
                parser = sau_cli.build_parser()
                video,cover = root/'video.mp4',root/'cover.jpg';video.touch();cover.touch()
                for kind,flag in [('chrome','--headed'),('chromium','--headless')]:
                    base=['--account','Fixture','--local-browser',kind,flag]
                    self.assertEqual(await sau_cli.dispatch(parser.parse_args(['weibo','login',*base])),0)
                    for failure in ('','blocked','redirect'):
                        scenario['failure']=failure
                        args=parser.parse_args(['weibo','upload-video',*base,'--file',str(video),'--thumbnail',str(cover),
                                                '--title','Fixture','--desc','Body','--tags','topic'])
                        before=len(posts)
                        if failure=='blocked':
                            with self.assertRaises(ElementUnusableError): await sau_cli.dispatch(args)
                            self.assertEqual(len(posts),before)
                        elif failure=='redirect':
                            with self.assertRaises(LoginRequiredError) as caught: await sau_cli.dispatch(args)
                            self.assertTrue(caught.exception.publish_attempted)
                            self.assertEqual(caught.exception.reason,'verification')
                            self.assertEqual(len(posts),before+1)
                        else:
                            self.assertEqual(await sau_cli.dispatch(args),0)
                            self.assertEqual(len(posts),before+1)
                self.assertEqual(len(posts),4)
                for post in posts:
                    self.assertEqual(post['clicks'],1)
                    self.assertEqual(post['title'],'Fixture')
                    self.assertEqual(post['desc'],'Body\n#topic#')
                    self.assertEqual((post['video'],post['cover']),('video.mp4','cover.jpg'))
                    self.assertTrue(post['ai'] and post['second'])
                    self.assertGreater(post['scroll'],0)
                    self.assertLess(post['height'],1000)
                    self.assertFalse(post['overlay'])
                self.assertEqual(len(launches),8)
                self.assertTrue(all(call['no_viewport'] and 'viewport' not in call and 'args' not in call for call in launches))
                self.assertTrue(all(not context.browser.is_connected() for context in contexts))
                self.assertFalse((root/'cookies').exists())
