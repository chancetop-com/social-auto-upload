"""Controlled Business Suite DOM in a real persistent browser; no platform traffic."""
import tempfile
import os
from unittest.mock import patch
import unittest
from pathlib import Path

from patchright.async_api import async_playwright

from uploader.meta_uploader.facebook_page_uploader.main import is_logged_in, MetaBusinessUploader
from utils.errors import LoginRequiredError
from utils.local_browser import LocalBrowserConfig
from utils.local_browser_session import local_browser_session


class FacebookPageProfileDomTests(unittest.IsolatedAsyncioTestCase):
    async def test_local_probe_accepts_navigation_and_classifies_form_blank_and_checkpoint(self):
        with tempfile.TemporaryDirectory() as directory:
            async with async_playwright() as playwright:
                async with local_browser_session(playwright,platform='facebook-page',account='Controlled',create=True,
                    profile_root=Path(directory),configuration=LocalBrowserConfig('chrome',True,'channel=chrome')) as session:
                    state = {'html':'<nav><a href="/latest/home">Business Suite</a></nav>', 'checkpoint':False}
                    async def route(request):
                        html = ('<script>history.replaceState({}, "", "/checkpoint/")</script>'
                                if state['checkpoint'] else state['html'])
                        await request.fulfill(status=200,content_type='text/html',body=html)
                    await session.context.route('**/*',route)
                    self.assertTrue(await is_logged_in(session.context,managed=False))
                    state['html'] = '<input name="email" aria-label="Email">'
                    with self.assertRaises(LoginRequiredError): await is_logged_in(session.context,managed=False)
                    state['html'] = '<main>Unavailable</main>'
                    with self.assertRaisesRegex(RuntimeError,'导航'): await is_logged_in(session.context,managed=False)
                    state['checkpoint'] = True
                    with self.assertRaises(LoginRequiredError) as error:
                        await is_logged_in(session.context,managed=False)
                    self.assertEqual(error.exception.reason,'verification')
                    self.assertFalse(error.exception.publish_attempted)

    async def test_real_page_prefix_mismatch_is_rejected_before_media_or_submit(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'HUMANIZE':'0'}):
            media = Path(directory)/'photo.png'; media.touch()
            async with async_playwright() as playwright:
                async with local_browser_session(playwright,platform='facebook-page',account='Controlled',create=True,
                    profile_root=Path(directory)/'profiles',configuration=LocalBrowserConfig('chrome',True,'channel=chrome')) as session:
                    html = '<nav><a href="/latest/home">Home</a></nav><div data-surface="x:bizweb_create_post:left_panel"><div role="combobox" aria-haspopup="listbox">Page AB<img alt="Facebook"></div></div><div role="option">Page A</div>'
                    await session.context.route('**/*',lambda request: request.fulfill(status=200,content_type='text/html',body=html))
                    app = MetaBusinessUploader('facebook-page',account_name='Controlled',title='Fixture',image_files=[media],
                        page_name='Page A',result_file=Path(directory)/'result.json')
                    with self.assertRaisesRegex(RuntimeError,'请求 Page'):
                        await app.upload(session=session)
                    self.assertEqual(app.result['status'],'not_submitted')
                    self.assertFalse(app.publish_attempted)
