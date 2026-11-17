"""Real persistent browser on controlled Channels DOM; all requests are fulfilled locally."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from patchright.async_api import async_playwright
from uploader.tencent_uploader.main import TencentVideo, is_logged_in
from utils.errors import LoginRequiredError
from utils.local_browser import LocalBrowserConfig
from utils.local_browser_session import local_browser_session


class TencentProfileDomTests(unittest.IsolatedAsyncioTestCase):
    async def test_positive_anchor_qr_iframe_blank_and_verification_are_distinct(self):
        with tempfile.TemporaryDirectory() as directory:
            async with async_playwright() as playwright:
                async with local_browser_session(playwright, platform='tencent', account='Controlled', create=True,
                    profile_root=Path(directory), configuration=LocalBrowserConfig('chrome', True, 'channel=chrome')) as session:
                    state = {'html': '<button>发表视频</button>'}
                    async def route(request):
                        html = '<main>QR fixture</main>' if 'open.weixin.qq.com' in request.request.url else state['html']
                        await request.fulfill(status=200, content_type='text/html; charset=utf-8', body=html)
                    await session.context.route('**/*', route)
                    self.assertTrue(await is_logged_in(session.context, managed=False))
                    state['html'] = '<iframe src="https://open.weixin.qq.com/connect/qrconnect"></iframe>'
                    self.assertFalse(await is_logged_in(session.context, managed=False))
                    state['html'] = '<main>Unavailable</main>'
                    with self.assertRaisesRegex(RuntimeError, '已登录标记'):
                        await is_logged_in(session.context, managed=False)
                    state['html'] = '<div class="weui-desktop-dialog__wrp">实名验证</div>'
                    with self.assertRaises(LoginRequiredError) as error:
                        await is_logged_in(session.context, managed=False)
                    self.assertEqual(error.exception.reason, 'verification')

    async def test_video_reaches_iframe_file_and_scrolls_to_submit_without_viewport_override(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'HUMANIZE': '0'}):
            video = Path(directory) / 'fixture.mp4'
            video.write_bytes(b'offline fixture')
            async with async_playwright() as playwright:
                async with local_browser_session(playwright, platform='tencent', account='Controlled', create=True,
                    profile_root=Path(directory) / 'profiles', configuration=LocalBrowserConfig('chrome', True, 'channel=chrome')) as session:
                    html = '''<button class="weui-desktop-btn" onclick="history.pushState({}, '', '/platform/post/create')">发表视频</button>
                        <iframe src="/micro/content/post/create"></iframe>
                        <div class="input-editor" contenteditable="true"></div>
                        <input placeholder="填写短标题有机会获得更多流量">
                        <div style="height:1500px"></div>
                        <div class="form-btns"><button onclick="document.documentElement.dataset.submits=String(Number(document.documentElement.dataset.submits||0)+1);history.replaceState({}, '', '/platform/post/list')">发表</button></div>'''
                    async def route(request):
                        body = '<input type="file">' if '/micro/' in request.request.url else html
                        await request.fulfill(status=200, content_type='text/html; charset=utf-8', body=body)
                    await session.context.route('**/*', route)
                    self.assertTrue(await is_logged_in(session.context, managed=False))
                    app = TencentVideo('Offline title', video, ['fixture'], 0, account_name='Controlled', desc='Offline description')
                    await app.tencent_upload_video(session=session)
                    page = next((p for p in session.context.pages if '/post/list' in p.url), session.context.pages[-1])
                    self.assertIsNone(page.viewport_size)
                    self.assertEqual(await page.locator('html').get_attribute('data-submits'), '1')
                    self.assertGreater(await page.evaluate('window.scrollY'), 0)
                    file_input = page.frame_locator('iframe').locator('input[type="file"]')
                    self.assertEqual(await file_input.evaluate('el => el.files[0].name'), 'fixture.mp4')
                    self.assertIn('Offline description', await page.locator('.input-editor').inner_text())
