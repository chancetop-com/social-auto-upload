"""Isolated native browser fixture; every platform/image request is fulfilled locally."""
import base64
from contextlib import ExitStack
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from patchright.async_api import async_playwright
import conf
import sau_cli
from sau_commands import arguments
from uploader.xueqiu_uploader import article, session

PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aWQAAAABJRU5ErkJggg==')
HTML = '''<!doctype html><meta charset="utf-8"><style>
body{margin:25px;font:16px sans-serif} input,button{padding:8px;margin:8px}
[hidden]{display:none!important} #editor{border:1px solid #888;min-height:120px;padding:10px}
.index_sectionFlex_fixture{display:flex;gap:15px;margin:10px}.index_selectWrap_fixture{cursor:pointer}
.index_optionContainer_fixture{background:#ddd;padding:10px}.index_optionContainer_fixture>div{cursor:pointer;padding:8px}
.modal_modal-content_fixture,.index_preview_fixture{position:fixed;inset:3vh 4vw;overflow:auto;background:white;border:2px solid black;padding:20px;z-index:10}
img{max-width:60px;min-height:12px;min-width:12px}.index_close_fixture{cursor:pointer;width:50px;height:30px}
</style>
<nav><div class="header-user" data-id="456"><span>Current creator</span></div></nav>
<input placeholder="请输入标题">
<div id="snb_toolbar"><button data-tip="上传图片" onmousedown="saveRange(event)" onclick="document.querySelector('#image').click()">图片</button></div>
<input id="image" type="file" hidden>
<div id="editor"><div contenteditable="true"></div></div>
<div class="index_sectionFlex_fixture"><label>封面图片：</label><input id="cover" type="file"><div class="index_input-cover-pic-btn_fixture"></div></div>
<div class="index_sectionFlex_fixture"><label>分享范围：</label><div class="index_selectWrap_fixture" onclick="this.nextElementSibling.hidden=!this.nextElementSibling.hidden">公开</div><div class="index_optionContainer_fixture" hidden><div onclick="choose(this)">公开</div><div onclick="choose(this)">私人</div></div></div>
<div class="index_sectionFlex_fixture"><label>创作声明：</label><div class="index_selectWrap_fixture" onclick="this.nextElementSibling.hidden=!this.nextElementSibling.hidden">不添加创作声明</div><div class="index_optionContainer_fixture" hidden><div onclick="choose(this)">不添加创作声明</div><div onclick="choose(this)">本文包含AI生成内容</div></div></div>
<div class="publish_state_fixture">已经保存至草稿</div><button onclick="preview()">预览</button>
<div class="modal_modal-content_fixture" hidden><div>选择封面图片</div><img alt="Crop" src="https://xqimg.imedao.com/cover.png"><button onclick="confirmCover()">确认裁剪</button></div>
<div class="index_preview_fixture" hidden><div class="index_close_fixture" onclick="this.parentElement.hidden=true">关闭</div><div class="index_preview-content_fixture"><h1></h1><div class="index_content-text_fixture"></div></div></div>
<script>
let range,images=0,cover=false;
const body=document.querySelector('#editor>[contenteditable]');
function saveRange(event){range=getSelection().getRangeAt(0).cloneRange();event.preventDefault()}
document.querySelector('#image').onchange=()=>{range.deleteContents();let img=document.createElement('img');img.src='https://xqimg.imedao.com/image'+(++images)+'.png';range.insertNode(img)};
document.querySelector('#cover').onchange=()=>document.querySelector('.modal_modal-content_fixture').hidden=false;
function confirmCover(){cover=true;document.querySelector('.index_input-cover-pic-btn_fixture').style.backgroundImage='url("https://xqimg.imedao.com/cover.png")';document.querySelector('.modal_modal-content_fixture').remove()}
function choose(option){option.parentElement.previousElementSibling.textContent=option.textContent;option.parentElement.hidden=true}
async function preview(){const p=document.querySelector('.index_preview_fixture');p.querySelector('h1').textContent=document.querySelector('input[placeholder]').value;
p.querySelector('.index_content-text_fixture').innerHTML=(cover?'<img class="index_first-pic_fixture" src="https://xqimg.imedao.com/cover.png">':'')+'<div>'+body.innerHTML+'</div>';p.hidden=false;
await fetch('/fixture-prepared',{method:'POST',body:JSON.stringify({title:p.querySelector('h1').textContent,html:body.innerHTML,images,cover,width:innerWidth,height:innerHeight,choices:[...document.querySelectorAll('.index_selectWrap_fixture')].map(e=>e.textContent)})});}
</script>'''


class XueqiuNativeBrowserTests(unittest.IsolatedAsyncioTestCase):
    async def test_complete_article_clipboard_images_cover_preview_and_profile_reopen(self):
        with tempfile.TemporaryDirectory() as temp, ExitStack() as stack:
            root = Path(temp)
            for key, value in dict(BASE_DIR=root, LOCAL_CHROME_PATH='', LOCAL_BROWSER='chrome', LOCAL_CHROME_HEADLESS=False).items():
                stack.enter_context(patch.object(conf, key, value, create=True))
            stack.enter_context(patch.object(arguments, 'BASE_DIR', root))
            stack.enter_context(patch.dict(os.environ, {'HUMANIZE':'0', 'MLX_API_TOKEN':'', 'ADSPOWER_API_KEY':''}))
            (root/'one.png').write_bytes(PNG); (root/'two.png').write_bytes(PNG); (root/'cover.png').write_bytes(PNG)
            source = root/'article.html'
            source.write_text('<h2>小标题</h2><p><strong>前文</strong><a href="https://xueqiu.com/">链接</a></p><img src="one.png"><p>中间</p><img src="two.png"><p><em>后文</em></p>')
            posts, launches, contexts = [], [], []
            async with async_playwright() as real:
                async def launch(**kwargs):
                    launches.append(kwargs)
                    context = await real.chromium.launch_persistent_context(**kwargs)
                    contexts.append(context)
                    async def route(route):
                        if route.request.url.endswith('/fixture-prepared'):
                            posts.append(json.loads(route.request.post_data))
                            await route.fulfill(status=200, body='ok')
                        elif route.request.url.startswith('https://xqimg.imedao.com/'):
                            await route.fulfill(status=200, content_type='image/png', body=PNG)
                        else:
                            await route.fulfill(status=200, content_type='text/html', body=HTML)
                    await context.route('**/*', route)
                    return context
                class Factory:
                    async def __aenter__(self): return SimpleNamespace(chromium=SimpleNamespace(launch_persistent_context=launch))
                    async def __aexit__(self, *_): pass
                for module in (session, article): stack.enter_context(patch.object(module, 'async_playwright', Factory))
                parser = sau_cli.build_parser()
                for kind, flag in [('chrome','--headed'), ('chromium','--headless')]:
                    base = ['--account','Fixture','--local-browser',kind,flag]
                    self.assertEqual(await sau_cli.dispatch(parser.parse_args(['xueqiu','login',*base,'--expected-name','Current creator'])),0)
                    self.assertEqual(await sau_cli.dispatch(parser.parse_args(['xueqiu','check',*base])),0)
                    self.assertEqual(await sau_cli.dispatch(parser.parse_args(['xueqiu','upload-article',*base,'--title','Fixture article','--content-file',str(source),'--cover',str(root/'cover.png'),'--visibility','私人','--declaration','本文包含AI生成内容','--prepare-only'])),0)
                self.assertEqual(len(posts),2)
                for post in posts:
                    self.assertEqual(post['title'],'Fixture article')
                    self.assertEqual(post['images'],2)
                    self.assertTrue(post['cover'])
                    self.assertEqual(post['choices'],['私人','本文包含AI生成内容'])
                    self.assertGreater(post['width'],0)
                    self.assertNotIn('SAU_IMAGE_',post['html'])
                self.assertEqual(len(launches),6)
                self.assertTrue(all(c['no_viewport'] and 'viewport' not in c for c in launches))
                self.assertTrue(all(not c.browser.is_connected() for c in contexts))
                results = list((root/'cookies/xueqiu_results').glob('*.json'))
                self.assertEqual(len(results),2)
                self.assertTrue(all(json.loads(p.read_text())['status']=='prepared' for p in results))
                self.assertFalse((root/'cookies/xueqiu_Fixture.json').exists())
                self.assertFalse((root/'cookies/xueqiu_Fixture.identity.json').exists())
