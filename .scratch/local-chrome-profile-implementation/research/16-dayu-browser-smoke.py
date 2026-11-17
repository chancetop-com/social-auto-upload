"""Controlled Dayu anonymous verification; no real platform/account operations."""
import asyncio
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
import conf
from patchright.async_api import async_playwright
from uploader.dayu_uploader.verification import verify_dayu_article
from utils.local_browser import resolve_local_browser
from utils.local_browser_session import local_browser_session
from utils.local_profile import acquire_local_profile

URL = 'https://mparticle.uc.cn/controlled-profile-fixture'
HTML = '''<!doctype html><meta charset="utf-8"><title>Controlled Dayu fixture</title>
<div class="index-articleContainer-fixture"><h1>Controlled article</h1>
<div class="article-userInfoName-fixture">Synthetic creator</div>
<div class="index-articleSummary-fixture"><p>Controlled content</p></div></div>'''

async def main():
    with tempfile.TemporaryDirectory(prefix='sau-dayu-controlled-') as root:
        with patch.object(conf, 'LOCAL_CHROME_PATH', '', create=True):
            async with async_playwright() as pw:
                for kind, headless in [('chrome',False),('chromium',True)]:
                    config = resolve_local_browser(local_browser=kind, headless=headless)
                    async with local_browser_session(pw,platform='dayu',account='synthetic',configuration=config,
                                                     profile_root=root,create=True) as session:
                        await session.context.route('https://mparticle.uc.cn/**', lambda route:route.fulfill(content_type='text/html',body=HTML))
                        page = await session.context.new_page(); await page.goto(URL)
                        assert page.viewport_size is None
                        await page.evaluate('''() => {localStorage.setItem('main','saved'); document.cookie='main=saved; max-age=3600; path=/'}''')
                        public_contexts, observations = [], []
                        async def anonymous(**kwargs):
                            assert kwargs == {'no_viewport':True}
                            assert request.get.await_count == 1, 'anonymous context opened before backend lookup'
                            context = await session.browser.new_context(**kwargs)
                            public_contexts.append(context)
                            async def public_route(route):
                                assert not await context.cookies(), 'main cookies leaked into anonymous context'
                                assert not page.is_closed()
                                try:
                                    with acquire_local_profile('dayu','synthetic',kind,root=root): pass
                                except RuntimeError: pass
                                else: raise AssertionError('main Profile lock released during public verification')
                                await route.fulfill(content_type='text/html',body=HTML+'''<script>
                                if(localStorage.getItem('main')!==null) throw Error('main localStorage leaked');
                                document.body.dataset.isolated=String(localStorage.getItem('main')===null);
                                localStorage.setItem('anonymous','visitor');</script>''')
                            await context.route('https://mparticle.uc.cn/**',public_route)
                            async def close():
                                try:
                                    visitor = context.pages[0]
                                    observations.append(dict(
                                        viewport=visitor.viewport_size,
                                        isolated=await visitor.locator('body').get_attribute('data-isolated'),
                                        cookies=await visitor.evaluate('document.cookie'),
                                        anonymous=await visitor.evaluate('localStorage.getItem("anonymous")'),
                                    ))
                                finally:
                                    await context.close()
                            return SimpleNamespace(new_page=context.new_page,close=close)
                        record = dict(content_id='controlled-1',origin_id='b'*32,title='Controlled article',status=1)
                        request = SimpleNamespace(get=AsyncMock(return_value=SimpleNamespace(ok=True,json=AsyncMock(return_value={'dataList':{'data':[record],'totalPage':1}}))))
                        result = await verify_dayu_article(SimpleNamespace(request=request),SimpleNamespace(new_context=anonymous),
                            {'wmid':'a'*32,'name':'Synthetic creator'},content_id='controlled-1',public=True)
                        assert result['public_article'] == {'image_count':0,'content_checked':False}
                        assert observations == [dict(viewport=None,isolated='true',cookies='',anonymous='visitor')], observations
                        assert not public_contexts[0].pages, 'anonymous context was not closed'
                        assert await page.evaluate('localStorage.getItem("anonymous")') is None
                        assert await page.evaluate('document.cookie') == 'main=saved'
                        assert await page.title() == 'Controlled Dayu fixture'
                        version = session.browser.version
                    async with local_browser_session(pw,platform='dayu',account='synthetic',configuration=config,profile_root=root) as session:
                        await session.context.route('https://mparticle.uc.cn/**',lambda route:route.fulfill(content_type='text/html',body=HTML))
                        page=await session.context.new_page(); await page.goto(URL)
                        assert await page.evaluate('localStorage.getItem("main")') == 'saved'
                        assert await page.evaluate('localStorage.getItem("anonymous")') is None
                        assert await page.evaluate('document.cookie') == 'main=saved'
                    print(json.dumps(dict(kind=kind,headless=headless,version=version,no_viewport=True,backend_before_public=True,
                                          anonymous_isolation=True,main_lock=True,persistence=True)),flush=True)
    print('PASS 2 Dayu controlled configurations',flush=True)

asyncio.run(main())
