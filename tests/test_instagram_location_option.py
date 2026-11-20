"""Instagram 地点参数校验、候选名称匹配与受控编辑器回读。"""
from __future__ import annotations

import asyncio
import contextlib
import io
import json
import os
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from patchright.async_api import async_playwright

import sau_cli
from sau_commands import instagram as instagram_command
from uploader.meta_uploader.insgraph_uploader.controls import location as location_control_module
from uploader.meta_uploader.insgraph_uploader.controls.location import (
    LocationCandidate,
    LocationControl,
)
from uploader.meta_uploader.insgraph_uploader.main import InstagramUploader
from uploader.meta_uploader.insgraph_uploader.options import (
    ACCOUNT_INELIGIBLE,
    ENTRY_MISSING,
    FINAL_EMPTY,
    FINAL_MISMATCH,
    LIST_NOT_COLLAPSED,
    MISMATCH,
    NO_CANDIDATES,
    NO_SAME_NAME,
    NOT_REQUESTED,
    PRESENT,
    SET,
    UNAVAILABLE,
    UNSUPPORTED,
    InstagramPublishOptions,
    OptionMismatchError,
)
from utils.errors import UsageError


class InstagramLocationFlagTests(unittest.TestCase):
    """A 层：两个命令都注册 ``--location``，未传不动页面，空白值退出 2。"""

    def _parse(self, *args):
        return sau_cli.build_parser().parse_args(['instagram', *args])

    def test_both_upload_commands_register_location(self):
        with tempfile.TemporaryDirectory() as folder:
            video = Path(folder) / 'video.mp4'
            image = Path(folder) / 'image.png'
            video.touch()
            image.touch()
            for action, media in (
                ('upload-video', ['--file', str(video)]),
                ('upload-note', ['--images', str(image)]),
            ):
                with self.subTest(action=action):
                    args = self._parse(
                        action, '--account', 'creator', *media,
                        '--title', 'caption', '--location', 'Shanghai',
                    )
                    self.assertEqual(args.location, 'Shanghai')

    def test_blank_location_exits_2_before_any_uploader(self):
        with tempfile.TemporaryDirectory() as folder:
            image = Path(folder) / 'image.png'
            image.touch()
            request = instagram_command.InstagramUploadRequest(
                'creator', 'caption', '', [], image_files=[image],
                options=InstagramPublishOptions(location='  '),
            )
            with self.assertRaisesRegex(UsageError, '地点不能为空'):
                instagram_command.validate_instagram_publish_request(request)
            upload = AsyncMock()
            with patch.object(
                instagram_command, 'upload_instagram_content', upload
            ), patch.object(InstagramUploader, 'upload', AsyncMock()), \
                    contextlib.redirect_stdout(io.StringIO()), \
                    contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(
                    sau_cli.main([
                        'instagram', 'upload-note', '--account', 'creator',
                        '--images', str(image), '--title', 'caption',
                        '--location', ' ',
                    ]),
                    2,
                )
            upload.assert_not_awaited()

    def test_empty_location_string_also_exits_2(self):
        """``--location ""`` 不能被折叠成“未请求”，必须是静态输入错误。"""
        with tempfile.TemporaryDirectory() as folder:
            image = Path(folder) / 'image.png'
            image.touch()
            args = self._parse(
                'upload-note', '--account', 'creator',
                '--images', str(image), '--title', 'caption',
                '--location', '',
            )
            options = instagram_command._build_publish_options(args)
            self.assertIsNotNone(options)
            self.assertEqual(options.location, '')
            upload = AsyncMock()
            with patch.object(
                instagram_command, 'upload_instagram_content', upload
            ), contextlib.redirect_stdout(io.StringIO()), \
                    contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(
                    sau_cli.main([
                        'instagram', 'upload-note', '--account', 'creator',
                        '--images', str(image), '--title', 'caption',
                        '--location', '',
                    ]),
                    2,
                )
            upload.assert_not_awaited()


class InstagramLocationCandidateMatchingTests(unittest.TestCase):
    """名称匹配只看第一行；地址只做所点行证据，不参与比较。"""

    def test_first_same_name_wins_when_addresses_differ(self):
        entries = [
            LocationCandidate(0, 'Shanghai, China', 'Pudong, Shanghai'),
            LocationCandidate(1, 'Shanghai', 'Huangpu, Shanghai'),
            LocationCandidate(2, 'Shanghai', 'Xuhui, Shanghai'),
            LocationCandidate(3, 'Hangzhou', None),
        ]
        self.assertEqual(
            LocationControl._exact_entry('  shanghai ', entries), entries[1]
        )

    def test_approximate_and_address_text_never_match(self):
        entries = [
            LocationCandidate(0, 'Shanghai, China', 'Pudong, Shanghai'),
            LocationCandidate(1, 'Greater Shanghai', 'Shanghai'),
        ]
        self.assertIsNone(LocationControl._exact_entry('Shanghai', entries))

    def test_name_only_row_matches_and_has_no_address(self):
        entries = [LocationCandidate(0, 'Shanghai', None)]
        self.assertEqual(
            LocationControl._exact_entry('SHANGHAI', entries), entries[0]
        )


class InstagramLocationControlTests(unittest.IsolatedAsyncioTestCase):
    async def test_disabled_without_explicit_restriction_is_not_ineligible(self):
        class _DisabledEntry:
            async def is_disabled(self):
                return True

            async def get_attribute(self, name):
                return None

        control = LocationControl(page=None)
        with (
            patch.object(
                control, '_entry', new=AsyncMock(return_value=_DisabledEntry())
            ),
            patch.object(
                control, '_restriction', new=AsyncMock(return_value=None)
            ),
        ):
            self.assertEqual(await control.resolve(), UNAVAILABLE)

    async def test_no_exact_match_reports_all_candidates_without_clicking(self):
        control = LocationControl(page=None)
        candidates = [
            LocationCandidate(0, 'Shanghai, China', 'Pudong, Shanghai'),
            LocationCandidate(1, 'Shanghai World Financial Center', 'Lujiazui'),
        ]
        with (
            patch.object(control, '_entry', new=AsyncMock(return_value=object())),
            patch.object(control, '_type_and_wait', new=AsyncMock(return_value=candidates)),
            patch.object(control, '_click_entry', new_callable=AsyncMock) as click,
        ):
            with self.assertRaises(OptionMismatchError) as caught:
                await control.set('Shanghai')
        click.assert_not_awaited()
        self.assertEqual(caught.exception.reason, NO_SAME_NAME)
        for candidate in candidates:
            self.assertIn(candidate.name, str(caught.exception))
        self.assertIn('Pudong, Shanghai', str(caught.exception))
        self.assertIsNone(caught.exception.applied)

    async def test_empty_candidate_list_has_its_own_reason(self):
        control = LocationControl(page=None)
        with (
            patch.object(control, '_entry', new=AsyncMock(return_value=object())),
            patch.object(control, '_type_and_wait', new=AsyncMock(return_value=[])),
            patch.object(control, '_click_entry', new_callable=AsyncMock) as click,
        ):
            with self.assertRaises(OptionMismatchError) as caught:
                await control.set('Shanghai')
        click.assert_not_awaited()
        self.assertEqual(caught.exception.reason, NO_CANDIDATES)
        self.assertIn('未出现任何候选', str(caught.exception))


def _location_page_html(
    candidates=(),
    *,
    outcome: str = 'collapse',
    entry: bool = True,
    restriction: str | None = None,
    response: str | None = None,
) -> str:
    """受控配文页：名称/地址分行的候选、可配置点击结果与 Share 计数器。"""
    rows = [
        {'name': name, 'address': address}
        for name, address in candidates
    ]
    entry_html = (
        '<div class="_abgh _aw1v"><label>'
        '<input aria-label="Add location" placeholder="Add location" '
        'name="creation-location-input" autocomplete="off"></label></div>'
        if entry
        else ''
    )
    restriction_html = (
        f'<div id="location-restriction">{restriction}</div>'
        if restriction
        else ''
    )
    fetch_call = (
        "; fetch('/api/v1/media/configure_to_clips/', {method:'POST'})"
        if response is not None
        else ''
    )
    return f'''
<div role="dialog" id="compose">
  <div role="heading" aria-level="1">Create new post</div>
  <div data-share-clicks="0"></div>
  {entry_html}
  <div id="suggestions"
       style="overflow-y:auto; max-height:240px; width:320px"></div>
  {restriction_html}
  <div role="textbox" contenteditable="true"
       data-lexical-editor="true"></div>
  <div role="button" id="share"
       onclick="const holder=document.querySelector('[data-share-clicks]');
                holder.dataset.shareClicks=String(Number(holder.dataset.shareClicks||0)+1){fetch_call}">Share</div>
</div>
<script>
  const candidates = {json.dumps(rows)};
  const outcome = {json.dumps(outcome)};
  const input = document.querySelector('input[placeholder="Add location"]');
  function render() {{
    const list = document.getElementById('suggestions');
    list.innerHTML = '';
    if (!input || !input.value.trim()) return;
    setTimeout(() => {{
      list.innerHTML = '';
      for (const candidate of candidates) {{
        const row = document.createElement('div');
        row.style.height = '60px';
        row.style.width = '300px';
        if (candidate.address) {{
          const name = document.createElement('div');
          name.textContent = candidate.name;
          const address = document.createElement('div');
          address.textContent = candidate.address;
          row.appendChild(name);
          row.appendChild(address);
        }} else {{
          row.textContent = candidate.name;
        }}
        row.addEventListener('click', () => {{
          document.body.dataset.clickedIndex = String(
            [...list.children].indexOf(row));
          document.body.dataset.clickedName = candidate.name;
          if (outcome === 'stale') {{
            input.value = candidate.name;
            return;
          }}
          list.innerHTML = '';
          if (outcome === 'mismatch') {{
            input.value = 'Beijing';
          }} else if (outcome === 'empty') {{
            input.value = '';
          }} else {{
            input.value = candidate.name;
          }}
        }});
        list.appendChild(row);
      }}
    }}, 30);
  }}
  if (input) {{
    input.addEventListener('input', render);
  }}
</script>
'''


class InstagramLocationControlledCliTests(unittest.TestCase):
    """真实 Chrome 受控页 + CLI：两个命令都按候选名称选点。"""

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name)
        self.video = self.folder / 'video.mp4'
        self.video.touch()
        self.image = self.folder / 'image.png'
        self.image.touch()

    def _run(
        self,
        *,
        action: str,
        html: str,
        location_args=('--location', 'Shanghai'),
        no_publish: bool = True,
        response: str | None = None,
        entry_timeout_ms: int | None = None,
        suggestion_timeout_ms: int | None = None,
    ):
        """经 ``sau`` CLI 跑完整发布前流程，返回可观察结果。"""
        holder: dict[str, object] = {}
        result_file = self.folder / f'result-{uuid4().hex}.json'

        async def fake_upload(request, *, target=None):
            async with async_playwright() as p:
                browser = await p.chromium.launch(channel='chrome', headless=True)
                page = await browser.new_page()
                try:
                    if response is None:
                        await page.set_content(html)
                    else:
                        async def route(route):
                            if (
                                route.request.method == 'POST'
                                and '/api/v1/media/configure' in route.request.url
                            ):
                                await route.fulfill(
                                    body=response, content_type='text/plain'
                                )
                            else:
                                await route.fulfill(
                                    body=html, content_type='text/html'
                                )

                        await page.route('https://www.instagram.com/**', route)
                        await page.goto('https://www.instagram.com/')
                    app = InstagramUploader(
                        'unused.json',
                        title=request.title,
                        description=request.description,
                        tags=request.tags,
                        video_file=request.video_file,
                        image_files=[
                            str(path) for path in (request.image_files or [])
                        ],
                        options=request.options,
                        no_publish=request.no_publish,
                        result_file=request.result_file,
                    )
                    budget = app.start_publish_budget()
                    try:
                        await app._publish(
                            page,
                            {'user_id': '42', 'username': 'creator'},
                            budget=budget,
                        )
                    except Exception as error:
                        holder['error'] = error
                        raise
                    finally:
                        holder['result'] = app.result
                        holder['share_clicks'] = int(
                            await page.locator('[data-share-clicks]')
                            .get_attribute('data-share-clicks') or 0
                        )
                        body = page.locator('body')
                        holder['clicked_index'] = await body.get_attribute(
                            'data-clicked-index'
                        )
                        holder['clicked_name'] = await body.get_attribute(
                            'data-clicked-name'
                        )
                        inputs = page.locator('input[placeholder="Add location"]')
                        holder['input_value'] = (
                            await inputs.first.input_value()
                            if await inputs.count()
                            else None
                        )
                finally:
                    await browser.close()
            return holder['result']

        media = (
            ['--file', str(self.video)]
            if action == 'upload-video'
            else ['--images', str(self.image)]
        )
        argv = [
            'instagram', action, '--account', 'creator', '--title', 'caption',
            *media, '--result', str(result_file), *location_args,
        ]
        if no_publish:
            argv.append('--no-publish')
        stdout, stderr = io.StringIO(), io.StringIO()
        patches = []
        if entry_timeout_ms is not None:
            patches.append(patch.object(
                location_control_module, 'ENTRY_TIMEOUT_MS', entry_timeout_ms
            ))
        if suggestion_timeout_ms is not None:
            patches.append(patch.object(
                location_control_module,
                'SUGGESTION_TIMEOUT_MS',
                suggestion_timeout_ms,
            ))
        with ExitStack() as stack:
            for item in patches:
                stack.enter_context(item)
            stack.enter_context(patch.object(
                instagram_command, 'upload_instagram_content', fake_upload
            ))
            stack.enter_context(patch.dict(
                os.environ,
                {
                    'HUMANIZE': '0',
                    'ADSPOWER_API_KEY': '',
                    'MLX_API_TOKEN': '',
                },
            ))
            stack.enter_context(contextlib.redirect_stdout(stdout))
            stack.enter_context(contextlib.redirect_stderr(stderr))
            code = sau_cli.main(argv)
        saved = json.loads(result_file.read_text(encoding='utf-8'))
        return code, saved, holder, stdout.getvalue(), stderr.getvalue()

    def test_split_name_and_address_first_same_name_is_clicked(self):
        candidates = [
            ('Shanghai, China', 'Pudong, Shanghai'),
            ('Shanghai', 'Huangpu, Shanghai'),
            ('Shanghai', 'Xuhui, Shanghai'),
            ('Hangzhou', None),
        ]
        expected = {
            'requested': 'Shanghai',
            'applied': 'Shanghai',
            'status': SET,
            'candidate_name': 'Shanghai',
            'candidate_address': 'Huangpu, Shanghai',
            'candidate_index': 1,
        }
        for action in ('upload-video', 'upload-note'):
            with self.subTest(action=action):
                code, saved, holder, stdout, stderr = self._run(
                    action=action,
                    html=_location_page_html(candidates),
                )
                self.assertEqual(code, 0, stderr)
                self.assertEqual(holder['share_clicks'], 0)
                self.assertEqual(holder['clicked_index'], '1')
                self.assertEqual(holder['clicked_name'], 'Shanghai')
                self.assertEqual(holder['input_value'], 'Shanghai')
                self.assertEqual(saved['status'], 'prepared')
                self.assertEqual(saved['options']['location'], expected)
                printed = json.loads(stdout)
                self.assertEqual(printed['status'], 'prepared')
                self.assertEqual(printed['options']['location'], expected)

    def test_full_name_match_ignores_case_and_extra_whitespace(self):
        candidates = [
            ('Shanghai, China', 'Pudong, Shanghai'),
            ('Shanghai', None),
        ]
        expected = {
            'requested': '  sHaNgHaI  ',
            'applied': 'Shanghai',
            'status': SET,
            'candidate_name': 'Shanghai',
            'candidate_index': 1,
        }
        for action in ('upload-video', 'upload-note'):
            with self.subTest(action=action):
                code, saved, holder, _, stderr = self._run(
                    action=action,
                    html=_location_page_html(candidates),
                    location_args=('--location', '  sHaNgHaI  '),
                )
                self.assertEqual(code, 0, stderr)
                self.assertEqual(holder['share_clicks'], 0)
                self.assertEqual(holder['clicked_index'], '1')
                self.assertEqual(holder['input_value'], 'Shanghai')
                self.assertEqual(saved['options']['location'], expected)
                self.assertNotIn(
                    'candidate_address', saved['options']['location']
                )

    def test_no_same_name_reports_all_candidates_and_never_clicks(self):
        candidates = [
            ('Shanghai, China', 'Pudong, Shanghai'),
            ('Shanghai World Financial Center', 'Lujiazui, Shanghai'),
        ]
        for action in ('upload-video', 'upload-note'):
            with self.subTest(action=action):
                code, saved, holder, stdout, stderr = self._run(
                    action=action,
                    html=_location_page_html(candidates),
                )
                self.assertEqual(code, 1)
                self.assertEqual(stdout, '')
                self.assertEqual(holder['share_clicks'], 0)
                self.assertIsNone(holder['clicked_name'])
                self.assertEqual(saved['status'], 'not_submitted')
                self.assertEqual(
                    saved['options']['location'],
                    {
                        'requested': 'Shanghai',
                        'applied': None,
                        'status': MISMATCH,
                        'reason': NO_SAME_NAME,
                    },
                )
                for name, _address in candidates:
                    self.assertIn(name, stderr)
                self.assertIn('Pudong, Shanghai', stderr)
                self.assertIn('no_same_name_candidate', stderr)

    def test_empty_candidate_list_reports_no_candidates_and_never_clicks(self):
        for action in ('upload-video', 'upload-note'):
            with self.subTest(action=action):
                code, saved, holder, _, stderr = self._run(
                    action=action,
                    html=_location_page_html([]),
                    suggestion_timeout_ms=150,
                )
                self.assertEqual(code, 1)
                self.assertEqual(holder['share_clicks'], 0)
                self.assertIsNone(holder['clicked_name'])
                self.assertEqual(
                    saved['options']['location'],
                    {
                        'requested': 'Shanghai',
                        'applied': None,
                        'status': MISMATCH,
                        'reason': NO_CANDIDATES,
                    },
                )
                self.assertIn('未出现任何候选', stderr)

    def test_missing_entry_is_unsupported_not_default_off(self):
        for action in ('upload-video', 'upload-note'):
            with self.subTest(action=action):
                code, saved, holder, _, stderr = self._run(
                    action=action,
                    html=_location_page_html([], entry=False),
                    entry_timeout_ms=150,
                )
                self.assertEqual(code, 1)
                self.assertEqual(holder['share_clicks'], 0)
                self.assertIsNone(holder['clicked_name'])
                self.assertEqual(
                    saved['options']['location'],
                    {
                        'requested': 'Shanghai',
                        'applied': None,
                        'status': UNSUPPORTED,
                        'reason': ENTRY_MISSING,
                    },
                )
                self.assertIn('location=unsupported(entry_missing)', stderr)
                self.assertNotIn('default_off', stderr)

    def test_explicit_eligibility_prompt_uses_account_ineligible(self):
        prompt = "Location tagging isn't available for this account."
        for action in ('upload-video', 'upload-note'):
            with self.subTest(action=action):
                code, saved, holder, _, stderr = self._run(
                    action=action,
                    html=_location_page_html(
                        [], entry=False, restriction=prompt
                    ),
                    entry_timeout_ms=150,
                )
                self.assertEqual(code, 1)
                self.assertEqual(holder['share_clicks'], 0)
                self.assertIsNone(holder['clicked_name'])
                record = saved['options']['location']
                self.assertEqual(record['status'], UNSUPPORTED)
                self.assertEqual(record['reason'], ACCOUNT_INELIGIBLE)
                self.assertEqual(record['applied'], None)
                self.assertIn(prompt, record['detail'])
                self.assertIn('location=unsupported(account_ineligible)', stderr)
                self.assertIn(prompt, stderr)

    def test_list_that_never_collapses_stops_before_share(self):
        candidates = [('Shanghai', 'Huangpu, Shanghai')]
        for action in ('upload-video', 'upload-note'):
            with self.subTest(action=action):
                code, saved, holder, _, stderr = self._run(
                    action=action,
                    html=_location_page_html(candidates, outcome='stale'),
                    suggestion_timeout_ms=500,
                )
                self.assertEqual(code, 1)
                self.assertEqual(holder['share_clicks'], 0)
                self.assertEqual(holder['clicked_name'], 'Shanghai')
                record = saved['options']['location']
                self.assertEqual(record['status'], MISMATCH)
                self.assertEqual(record['reason'], LIST_NOT_COLLAPSED)
                self.assertEqual(record['candidate_name'], 'Shanghai')
                self.assertEqual(record['candidate_address'], 'Huangpu, Shanghai')
                self.assertEqual(record['candidate_index'], 0)
                self.assertIn('list_not_collapsed', stderr)

    def test_selected_name_mismatch_and_empty_stop_before_share(self):
        candidates = [('Shanghai', 'Huangpu, Shanghai')]
        cases = (
            ('mismatch', FINAL_MISMATCH, 'Beijing'),
            ('empty', FINAL_EMPTY, ''),
        )
        for action in ('upload-video', 'upload-note'):
            for outcome, reason, readback in cases:
                with self.subTest(action=action, outcome=outcome):
                    code, saved, holder, _, stderr = self._run(
                        action=action,
                        html=_location_page_html(candidates, outcome=outcome),
                    )
                    self.assertEqual(code, 1)
                    self.assertEqual(holder['share_clicks'], 0)
                    self.assertEqual(holder['clicked_name'], 'Shanghai')
                    self.assertEqual(holder['input_value'], readback)
                    record = saved['options']['location']
                    self.assertEqual(record['status'], MISMATCH)
                    self.assertEqual(record['reason'], reason)
                    self.assertEqual(record['applied'], readback or None)
                    self.assertEqual(record['candidate_name'], 'Shanghai')
                    self.assertEqual(
                        record['candidate_address'], 'Huangpu, Shanghai'
                    )
                    self.assertIn(reason, stderr)

    def test_published_status_keeps_location_evidence(self):
        candidates = [('Shanghai', 'Huangpu, Shanghai')]
        response = (
            'for (;;);{"status":"ok","media":'
            '{"id":"123_42","pk":"123","code":"LOC",'
            '"user":{"pk":"42"},"caption":{"text":"caption"}}}'
        )
        for action in ('upload-video', 'upload-note'):
            with self.subTest(action=action):
                code, saved, holder, stdout, stderr = self._run(
                    action=action,
                    html=_location_page_html(candidates, response=response),
                    no_publish=False,
                    response=response,
                )
                self.assertEqual(code, 0, stderr)
                self.assertEqual(holder['share_clicks'], 1)
                self.assertEqual(saved['status'], 'published')
                self.assertEqual(saved['options']['location'], {
                    'requested': 'Shanghai',
                    'applied': 'Shanghai',
                    'status': SET,
                    'candidate_name': 'Shanghai',
                    'candidate_address': 'Huangpu, Shanghai',
                    'candidate_index': 0,
                })
                self.assertEqual(json.loads(stdout)['status'], 'published')


class _EvidenceLocationControl:
    """In-memory location control that behaves like a split-row selection."""

    def __init__(self):
        self.value = None
        self.last_evidence = {}

    async def resolve(self):
        return PRESENT

    async def read(self):
        return self.value

    async def set(self, requested):
        self.value = 'Shanghai'
        self.last_evidence = {
            'candidate_name': 'Shanghai',
            'candidate_address': 'Huangpu, Shanghai',
            'candidate_index': 1,
        }


class InstagramLocationDefaultResultTests(unittest.TestCase):
    """默认结果文件保留顶层状态、既有 options 形状并追加所点行证据。"""

    def test_default_result_file_keeps_location_contract_for_both_commands(self):
        for action in ('upload-video', 'upload-note'):
            with self.subTest(action=action), tempfile.TemporaryDirectory() as folder:
                media = (
                    {'video_file': 'video.mp4'}
                    if action == 'upload-video'
                    else {'image_files': ['image.png']}
                )
                app = InstagramUploader(
                    'unused.json',
                    title='caption',
                    options=InstagramPublishOptions(location='Shanghai'),
                    **media,
                )
                self.addCleanup(
                    lambda path=app.result_file: path.unlink(missing_ok=True)
                )
                self.assertEqual(
                    app.result_file.parent, Path('.local/instagram-results')
                )
                control = _EvidenceLocationControl()
                asyncio.run(app._apply_options(
                    page=None,
                    budget=app.start_publish_budget(),
                    controls={'location': control},
                ))
                saved = json.loads(
                    app.result_file.read_text(encoding='utf-8')
                )
                self.assertEqual(saved['platform'], 'instagram')
                self.assertEqual(saved['status'], 'not_submitted')
                self.assertEqual(
                    saved['options']['location'],
                    {
                        'requested': 'Shanghai',
                        'applied': 'Shanghai',
                        'status': SET,
                        'candidate_name': 'Shanghai',
                        'candidate_address': 'Huangpu, Shanghai',
                        'candidate_index': 1,
                    },
                )
                self.assertEqual(
                    saved['options']['comments'],
                    {
                        'requested': None,
                        'applied': None,
                        'status': NOT_REQUESTED,
                    },
                )


if __name__ == '__main__':
    unittest.main()
