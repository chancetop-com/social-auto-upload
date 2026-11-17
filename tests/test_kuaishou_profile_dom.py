"""Controlled DOM in a real persistent browser; no Kuaishou account/network actions."""
import os
import asyncio
from types import SimpleNamespace
from pathlib import Path
import tempfile
from datetime import datetime, timedelta, timezone
import unittest
from unittest.mock import patch

from patchright.async_api import async_playwright
from uploader.ks_uploader.main import KSVideo, KSNote
from uploader.ks_uploader import main as uploader
from utils.local_browser import LocalBrowserConfig
from utils.local_browser_session import local_browser_session


HTML = '''<!doctype html><meta charset="utf-8"><style>
body {margin:16px; font:16px sans-serif} button {padding:12px} [contenteditable] {min-height:80px;border:1px solid}
.block {margin-top:500px} .ant-select-selector,.ant-select-item-option,#coverentry {padding:15px;border:1px solid;cursor:pointer}
.ant-modal {position:fixed;top:10px;left:10px;background:white;border:1px solid;padding:20px;z-index:20}
</style>
<div role="tablist"><div role="tab" onclick="document.body.dataset.noteTab='true'">图文</div></div>
<button class="_upload-btn-fixture" onclick="document.querySelector('#media').click()">上传图片</button>
<input hidden type="file" id="media" multiple>
<section class="block"><label>描述</label><div contenteditable="true" id="editor">old</div></section>
<section class="block"><div><span>封面设置</span></div><div><div id="coverentry" onclick="document.querySelector('.ant-modal').hidden=false">编辑封面</div></div></section>
<div role="document" class="ant-modal" hidden><input hidden type="file" id="cover"><button onclick="this.parentElement.hidden=true">确认</button></div>
<section class="block"><label>加入合集</label><div class="ant-select"><div class="ant-select-selector" onclick="document.body.dataset.collectionOpened='true'">选择合集</div></div>
<div class="ant-select-item-option" label="Series" onclick="document.body.dataset.collection='Series'">Series</div></section>
<section class="block"><label class="ant-radio-wrapper" onclick="document.body.dataset.scheduled='true'">定时发布</label><input placeholder="选择日期时间"></section>
<section class="block"><button onclick="document.body.dataset.submits=String(Number(document.body.dataset.submits||0)+1);history.pushState({},'', '/article/manage/video?status=2&from=publish')">发布</button></section>
'''


class KuaishouProfileDomTests(unittest.IsolatedAsyncioTestCase):
    async def test_both_media_controls_scroll_in_small_window_without_fixed_viewport(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'HUMANIZE': '1'}):
            media = Path(directory) / 'fixture.png'
            media.write_bytes(b'controlled upload fixture')
            video = Path(directory) / 'fixture.mp4'
            video.write_bytes(b'controlled video fixture')
            async with async_playwright() as playwright:
                async with local_browser_session(playwright, platform='kuaishou', account='Controlled',
                    create=True, profile_root=Path(directory) / 'profiles',
                    configuration=LocalBrowserConfig('chrome', True, 'channel=chrome')) as session:
                    async def route(request):
                        page = request.request.frame.page
                        cdp = await session.context.new_cdp_session(page)
                        window = await cdp.send('Browser.getWindowForTarget')
                        await cdp.send('Browser.setWindowBounds', {'windowId': window['windowId'], 'bounds': {'width': 560, 'height': 420}})
                        await request.fulfill(status=200, content_type='text/html', body=HTML)
                    await session.context.route('**/*', route)
                    schedule = (datetime.now(timezone.utc) + timedelta(days=2)).replace(second=0, microsecond=0)
                    for kind in ('video', 'note'):
                        with self.subTest(kind=kind):
                            common = dict(tags=[], publish_date=schedule, account_file=None, account_name='Controlled')
                            app = (KSVideo('Title', video, desc='Description', thumbnail_path=media, collection_name='Series', **common)
                                   if kind == 'video' else KSNote([media], note='Description', title='Title', **common))
                            async def short_sleep(seconds):
                                await asyncio.sleep(min(seconds, 0.005))
                            with patch.object(uploader, "asyncio", SimpleNamespace(sleep=short_sleep)):
                                await app.main(session=session)
                            page = session.context.pages[-1]
                            self.assertIsNone(page.viewport_size)
                            self.assertLessEqual(await page.evaluate('window.innerWidth'), 560)
                            self.assertEqual(await page.locator('body').get_attribute('data-submits'), '1')
                            self.assertEqual(await page.locator('#media').evaluate('x=>x.files.length'), 1)
                            self.assertTrue(await page.locator('body').get_attribute('data-scheduled'))
                            self.assertTrue(await page.locator('input[placeholder="选择日期时间"]').input_value())
                            self.assertIn('Description', await page.locator('#editor').inner_text())
                            if kind == 'video':
                                self.assertEqual(await page.locator('#cover').evaluate('x=>x.files.length'), 1)
                                self.assertEqual(await page.locator('body').get_attribute('data-collection'), 'Series')
                            else:
                                self.assertTrue(await page.locator('body').get_attribute('data-note-tab'))
                            await page.close()
