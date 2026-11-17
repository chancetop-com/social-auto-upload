"""Controlled Douyin DOM in persistent Chrome; all requests are intercepted."""
import os
import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from patchright.async_api import async_playwright
from uploader.douyin_uploader.main import DouYinVideo, is_logged_in
from utils.local_browser import LocalBrowserConfig
from utils.local_browser_session import local_browser_session
from utils.errors import LoginRequiredError


class DouyinProfileDomTests(unittest.IsolatedAsyncioTestCase):
    async def test_native_window_video_flow_scrolls_and_clears_overlay_without_identity_overrides(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'HUMANIZE':'0'}):
            media = Path(directory)/'clip.mp4'; media.write_bytes(b'controlled fixture')
            html = '''<meta charset="utf-8"><button>发布视频</button><div class="container-fixture">
            <input type="file" class="upload-btn-input" onchange="history.replaceState({},'', '/creator-micro/content/publish?enter_from=publish_page')"></div>
            <div class="long-card-fixture"><div>重新上传</div></div>
            <input placeholder="填写作品标题"><div class="zone-container" contenteditable="true"></div>
            <div style="height:1400px"></div>
            <button onclick="document.querySelector('.semi-modal-content').style.display='block'">请选择自主声明</button>
            <div class="semi-modal-content" style="display:none"><h2>请选择声明类型（单选）</h2>
            <label class="semi-radio"><input type="radio"><span class="semi-radio-addon">内容由AI生成</span></label>
            <button class="semi-button-primary" onclick="this.parentNode.style.display='none'">确定</button></div>
            <button onclick="document.body.dataset.submissions=String(Number(document.body.dataset.submissions||0)+1);history.replaceState({},'', '/creator-micro/content/manage')">发布</button>
            <script>document.querySelector('.zone-container').addEventListener('blur',()=>{let overlay=document.createElement('div');overlay.className='shepherd-modal-overlay-container';overlay.style='position:fixed;inset:0;z-index:9999;background:#555';document.body.append(overlay)})</script>'''
            async with async_playwright() as playwright:
                async with local_browser_session(playwright,platform='douyin',account='Controlled',create=True,
                    profile_root=Path(directory)/'profiles',configuration=LocalBrowserConfig('chrome',True,'channel=chrome')) as session:
                    await session.context.route('**/*',lambda route: route.fulfill(status=200,content_type='text/html; charset=utf-8',body=html))
                    self.assertTrue(await is_logged_in(session.context,managed=False))
                    app = DouYinVideo('Fixture',str(media),[],0,None,desc='Description')
                    await asyncio.wait_for(app.douyin_upload_video(session=session),timeout=40)
                    page = session.context.pages[-1]
                    self.assertIsNone(page.viewport_size)
                    self.assertEqual(await page.locator('body').get_attribute('data-submissions'),'1')
                    self.assertEqual(await page.locator('input[placeholder="填写作品标题"]').input_value(),'Fixture')
                    self.assertEqual(await page.locator('.zone-container').inner_text(),'Description')
                    self.assertEqual(await page.locator('.shepherd-modal-overlay-container').count(),0)

    async def test_probe_requires_positive_entry_and_classifies_visible_verification(self):
        with tempfile.TemporaryDirectory() as directory:
            async with async_playwright() as playwright:
                async with local_browser_session(playwright,platform='douyin',account='Controlled',create=True,
                    profile_root=Path(directory),configuration=LocalBrowserConfig('chrome',True,'channel=chrome')) as session:
                    state = {'html':'<main>Unavailable</main>'}
                    await session.context.route('**/*',lambda route: route.fulfill(status=200,content_type='text/html; charset=utf-8',body=state['html']))
                    with self.assertRaisesRegex(RuntimeError,'入口'): await is_logged_in(session.context,managed=False)
                    state['html'] = '<input placeholder="短信验证码">'
                    with self.assertRaises(LoginRequiredError) as caught: await is_logged_in(session.context,managed=False)
                    self.assertEqual(caught.exception.reason,'verification')
                    self.assertFalse(caught.exception.publish_attempted)
