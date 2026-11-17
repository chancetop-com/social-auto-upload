"""Controlled DOM only: persistent Chromium, natural small viewport, real humanizer.
Run from repo root with PYTHONPATH=. No request reaches YouTube or any account.
"""
import asyncio
import tempfile
from pathlib import Path

from patchright.async_api import async_playwright
from uploader.youtube_uploader.main import YouTubeVideo
from utils.local_browser_session import local_browser_session

HTML = '''<!doctype html><style>
body { margin: 30px; font: 16px sans-serif; }
ytcp-button, ytcp-text-dropdown-trigger, tp-yt-paper-checkbox, tp-yt-paper-radio-button
{display:block;width:200px;height:40px;background:#ddd;margin:12px;padding:8px;cursor:pointer;}
[contenteditable] {border:1px solid;min-height:40px;width:400px}
#overlay {display:none;position:fixed;inset:0;background:#fff;z-index:999;}
</style><input type=file><div id=title-textarea><div id=textbox contenteditable=true></div></div>
<div id=description-textarea><div id=textbox contenteditable=true></div></div>
<div id=basics><ytcp-text-dropdown-trigger onclick="document.querySelector('#overlay').style.display='block'">Playlist</ytcp-text-dropdown-trigger></div>
<div id=overlay><ytcp-playlist-dialog>
<tp-yt-paper-checkbox onclick="document.body.dataset.playlist='Series'">Series</tp-yt-paper-checkbox>
<ytcp-button id=save-button onclick="document.querySelector('#overlay').style.display='none'">Done</ytcp-button>
</ytcp-playlist-dialog></div>
<div style='height:1500px'></div>
<tp-yt-paper-radio-button name=VIDEO_MADE_FOR_KIDS_NOT_MFK>Not for kids</tp-yt-paper-radio-button>
<tp-yt-paper-radio-button name=PUBLIC onclick="document.body.dataset.visibility='public'">Public</tp-yt-paper-radio-button>
<div class=progress-label>Checks complete</div>
<ytcp-button id=done-button onclick="document.body.dataset.submits=Number(document.body.dataset.submits||0)+1">Publish fixture</ytcp-button>
<a href='https://youtu.be/fixture'>fixture result</a><ytcp-button id=close-button>Close</ytcp-button>
'''

async def main():
    with tempfile.TemporaryDirectory(prefix='youtube-dom-') as root:
        media = Path(root) / 'fixture.mp4'
        media.write_bytes(b'synthetic upload fixture')
        async with async_playwright() as playwright:
            async with local_browser_session(playwright, platform='youtube', account='synthetic',
                                             profile_root=Path(root) / 'profiles', create=True,
                                             local_browser='chromium', headless=True) as session:
                async def controlled(route):
                    await route.fulfill(status=200, content_type='text/html', body=HTML)
                await session.context.route('**/*', controlled)
                app = YouTubeVideo('Fixture title', media, [], None, description='Fixture description', playlist='Series')
                await app.main(session=session)
                page = session.context.pages[-1]
                result = await page.evaluate('''() => ({title:document.querySelector('#title-textarea #textbox').textContent,
                    description:document.querySelector('#description-textarea #textbox').textContent,
                    playlist:document.body.dataset.playlist,visibility:document.body.dataset.visibility,
                    submits:document.body.dataset.submits,overlay:getComputedStyle(document.querySelector('#overlay')).display,
                    scrolled:scrollY>0,width:innerWidth,height:innerHeight})''')
                assert result['title'] == 'Fixture title', result
                assert result['description'] == 'Fixture description', result
                assert result['playlist'] == 'Series' and result['visibility'] == 'public', result
                assert result['submits'] == '1' and result['overlay'] == 'none', result
                assert result['scrolled'] and page.viewport_size is None, result
                print({'browser': session.browser.version, 'no_viewport': page.viewport_size is None, **result})

asyncio.run(main())
