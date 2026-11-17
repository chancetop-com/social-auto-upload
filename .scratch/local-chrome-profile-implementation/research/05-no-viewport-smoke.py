"""Controlled local DOM exercise; no platform account, upload service or publish."""
import asyncio
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import conf
from patchright.async_api import async_playwright
from uploader.xiaohongshu_uploader.main import XiaoHongShuVideo, XiaoHongShuNote
from utils.local_browser_session import local_browser_session

HTML = '''<!doctype html><html><head><style>
body {margin:20px;font:16px sans-serif} .spacer {height:900px}
xhs-publish-btn {display:block;width:150px;height:45px;background:#eee}
.feature-guide__btn {position:fixed;inset:0;z-index:999;background:white}
input {min-height:35px} .tiptap {height:150px;border:1px solid black}
</style></head><body data-submits="0" data-uploaded="0">
<button class="feature-guide__btn" onclick="this.remove()">Close guide</button>
<div class="upload-content"><input class="upload-input" type="file"
onchange="document.querySelector('.img-preview-area').innerHTML='<div class=pr>Preview</div>';document.body.dataset.uploaded=this.files.length"></div>
<div class="img-preview-area"></div><div class="spacer"></div>
<div class="d-input"><input></div><div class="tiptap" role="textbox" contenteditable="true"></div>
<xhs-publish-btn is-publish="true" submit-disabled="false" onclick="document.body.dataset.submits=Number(document.body.dataset.submits)+1">Publish</xhs-publish-btn>
</body></html>'''

async def main():
    with tempfile.TemporaryDirectory(prefix='sau-xhs-viewport-') as directory, patch.object(conf, 'BASE_DIR', Path(directory)), patch.object(conf, 'LOCAL_CHROME_PATH', ''), patch.dict(os.environ, {'SAU_XHS_CREATOR_BASE_URL': 'http://127.0.0.1:8765', 'HUMANIZE': '0'}):
        for kind, headless in [('chrome', False), ('chromium', True)]:
            async with async_playwright() as playwright:
                async with local_browser_session(playwright, platform='xiaohongshu', account='fixture', local_browser=kind, headless=headless, create=True) as session:
                    await session.context.route('http://127.0.0.1:8765/**', lambda route: route.fulfill(status=200, content_type='text/html', body=HTML))
                    for mode in ('video', 'note'):
                        media = Path(directory) / ('video.mp4' if mode == 'video' else 'image.png')
                        media.write_bytes(b'fixture')
                        if mode == 'video':
                            app = XiaoHongShuVideo('Smoke title', media, [], 0, no_publish=True, desc='Smoke body')
                            await app.xiaohongshu_upload_video(session=session)
                        else:
                            app = XiaoHongShuNote([media], 'Smoke body', [], 0, title='Smoke title', no_publish=True)
                            await app.xiaohongshu_upload_note(session=session)
                        page = session.context.pages[-1]
                        assert page.viewport_size is None
                        assert await page.locator('body').get_attribute('data-uploaded') == '1'
                        assert await page.locator('.d-input input').input_value() == 'Smoke title'
                        assert (await page.locator('.tiptap').inner_text()).strip() == 'Smoke body'
                        assert await page.locator('body').get_attribute('data-submits') == '0'
                        assert await page.evaluate('window.scrollY') > 0
                        assert await page.locator('.feature-guide__btn').count() == 0
                        print(f'PASS {kind} headless={headless} {mode}: natural viewport, overlay cleared, scrolled, uploaded, edited, ARM ready, no submit')

asyncio.run(main())
