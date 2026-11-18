"""Public upload boundary against controlled, observed Instagram UI shapes.

Chinese creator anchors come from 20's 2026-11-17 captured menu; the English
div/icon shape comes from adspower commit 7ee8380's 09-creator-entry-evidence.md. Ordinary
navigation and composer roles come from the existing browser fixtures. No live
account, remote request or persistent Profile is used by this module.
"""
import asyncio
import functools
import json
import os
import tempfile
import unittest
from contextlib import chdir
from pathlib import Path
from unittest.mock import patch

from patchright.async_api import async_playwright

from uploader.meta_uploader.insgraph_uploader import main
from uploader.publish_timeout import PublishTimeoutBudget
from utils.browser_session import BrowserSession


HTML = (Path(__file__).parent / "fixtures" / "instagram_composer.html").read_text(encoding="utf-8")


class InstagramAccountUiTests(unittest.TestCase):
    async def scenario(self, *, creator=False, video=False, mode='local', humanize=True,
                       failure=False, failure_timeout=5, **changes):
        config = dict(creator=creator, **changes)
        html = HTML.replace('CONFIG', json.dumps(config))
        async with async_playwright() as p:
            browser = await p.chromium.launch(channel='chrome', headless=True)
            context = await browser.new_context()
            page_errors=[]
            context.on('page', lambda page: page.on('pageerror', lambda error: page_errors.append(str(error))))
            await context.add_cookies([{'name':'ds_user_id','value':'42','domain':'.instagram.com','path':'/'}])
            await context.route('**/*', lambda route: route.fulfill(body=html, content_type='text/html'))
            try:
                with tempfile.TemporaryDirectory() as folder, chdir(folder), patch.dict(os.environ, {'HUMANIZE':'1' if humanize else '0'}):
                    media = Path(folder) / ('demo.mp4' if video else 'demo.png')
                    media.touch()
                    app = main.InstagramUploader(account_name='fixture', title='caption',
                        video_file=media if video else None, image_files=[] if video else [media],
                        no_publish=True, result_file=Path(folder)/'result.json')
                    session = BrowserSession(browser=browser, context=context, mode=mode)
                    # A short real clock budget bounds negative UI cases; no selector,
                    # humanizer, session, upload or publishing implementation is mocked.
                    budget = functools.partial(PublishTimeoutBudget, timeout_seconds=failure_timeout if failure else 40)
                    with patch.object(main, 'PublishTimeoutBudget', budget):
                        if failure:
                            with self.assertRaises(Exception):
                                await app.upload(session=session)
                        else:
                            try:
                                result = await app.upload(session=session)
                            except Exception:
                                self.assertEqual(page_errors, [], 'fixture JavaScript errors')
                                raise
                            self.assertEqual(result['status'], 'prepared')
                    self.assertEqual(page_errors, [], 'fixture JavaScript errors')
                    page=context.pages[-1]
                    observed=await page.evaluate('({...JSON.parse(document.body.dataset.observed),caption:document.querySelector("[contenteditable]")?.innerText,postDisabled:document.querySelector("[data-action=post]")?.getAttribute("aria-disabled"),scrollY:window.scrollY})')
                    self.assertEqual(observed['wrongClicks'],0)
                    self.assertEqual(observed['shareClicks'],0)
                    self.assertEqual(len(context.pages),1)  # caller still owns context
                    self.assertFalse(app.publish_clicked)
                    if not failure:
                        self.assertEqual(observed['files'],[media.name])
                        self.assertEqual(observed['caption'],'caption')
                        clicks=[e['target'] for e in observed['events'] if e['name']=='click']
                        self.assertEqual(clicks[:2] if creator else clicks[:1], ['create','post'] if creator else ['create'])
                        self.assertEqual(clicks.count('advance'),2)
                        self.assertTrue(all(e['trusted'] for e in observed['events']))
                        if humanize:
                            self.assertTrue(any(e['name']=='keydown' and e.get('key')=='c' for e in observed['events']))
                            for target in ('create','post') if creator else ('create',):
                                target_events=[e['name'] for e in observed['events'] if e['target']==target]
                                self.assertLess(target_events.index('pointermove'),target_events.index('pointerdown'))
                    return observed
            finally:
                await browser.close()

    def test_both_account_shapes_and_media_reach_no_publish_with_humanizer(self):
        for mode in ('local','multilogin'):
            for creator in (False, True):
                for video in (False, True):
                    with self.subTest(mode=mode,creator=creator,video=video):
                        asyncio.run(self.scenario(mode=mode,creator=creator,video=video))

    def test_fast_path_supports_both_shapes(self):
        for creator in (False,True):
            with self.subTest(creator=creator):
                asyncio.run(self.scenario(creator=creator,humanize=False))

    def test_english_creator_video_and_note_reach_no_publish(self):
        for mode in ('local', 'adspower'):
            for video in (False, True):
                with self.subTest(mode=mode, video=video):
                    asyncio.run(self.scenario(creator=True, english=True, mode=mode, video=video))

    def test_english_creator_recovers_before_dispatch_from_menu_drift(self):
        asyncio.run(self.scenario(creator=True, english=True, driftPost=True))

    def test_english_creator_rejects_duplicate_and_mixed_language_menus(self):
        for change in ('duplicatePost', 'mixedPost', 'missingPost'):
            with self.subTest(change=change):
                state=asyncio.run(self.scenario(creator=True, english=True,
                    failure=True, humanize=False, **{change:True}))
                self.assertEqual([e['target'] for e in state['events'] if e['name']=='click'], ['create'])
                self.assertEqual(state['files'], [])

    def test_english_creator_never_repeats_a_dispatched_menu_click(self):
        state=asyncio.run(self.scenario(creator=True, english=True,
            failure=True, humanize=False, stalledPost=True))
        self.assertEqual([e['target'] for e in state['events'] if e['name']=='click'], ['create', 'post'])
        self.assertEqual(state['files'], [])

    def test_english_creator_disabled_container_never_dispatches(self):
        for humanize, change in ((False, 'blockedPost'), (False, 'disablePostOnHover'),
                                 (True, 'blockedPost'),
                                 (True, 'disablePostOnHover')):
            with self.subTest(humanize=humanize, change=change):
                state = asyncio.run(self.scenario(creator=True, english=True,
                    mode='adspower', humanize=humanize, failure=True,
                    failure_timeout=15, **{change: True}))
                self.assertEqual(state['postDisabled'], 'true')
                self.assertEqual([e['target'] for e in state['events'] if e['name']=='click'], ['create'])
                self.assertEqual(state['files'], [])

    def test_offscreen_creator_menu_scrolls_before_interaction_check(self):
        for english in (False, True):
            for humanize in (False, True):
                with self.subTest(english=english, humanize=humanize):
                    state = asyncio.run(self.scenario(creator=True, english=english,
                        humanize=humanize, offscreenPost=True))
                    self.assertGreater(state['scrollY'], 0)

    def test_ambiguous_or_missing_navigation_never_dispatches(self):
        for change in ('duplicateCreate','missingCreate'):
            with self.subTest(change=change):
                state=asyncio.run(self.scenario(failure=True,humanize=False,**{change:True}))
                self.assertFalse([e for e in state['events'] if e['name']=='click'])

    def test_submenu_ambiguity_missing_or_disabled_never_selects_another_action(self):
        for change in ('duplicatePost','missingPost','blockedPost','bothStates'):
            with self.subTest(change=change):
                state=asyncio.run(self.scenario(creator=True,failure=True,humanize=False,**{change:True}))
                self.assertEqual([e['target'] for e in state['events'] if e['name']=='click'],['create'])
                self.assertEqual(state['files'],[])

    def test_editor_does_not_click_share_early_or_choose_duplicate_next(self):
        for change in ('earlyShare','duplicateNext'):
            with self.subTest(change=change):
                asyncio.run(self.scenario(failure=True,humanize=False,**{change:True}))

    def test_no_publish_requires_an_interactive_share_button(self):
        asyncio.run(self.scenario(failure=True,humanize=False,blockedShare=True))
