import sau_commands.instagram
"""Instagram 的业务响应、账号边界和实际 DOM/事件回归。"""
import asyncio
import contextlib
import io
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from patchright.async_api import async_playwright

import sau_cli
from uploader.meta_uploader.insgraph_uploader.main import (
    InstagramUploader, _create_entry, _is_instagram_logged_out,
    instagram_created_media, instagram_response_payload, _dismiss_optional_prompt,
)
from uploader.meta_uploader.insgraph_uploader.options import (
    DEFAULT_OFF, SET, InstagramPublishOptions,
)
from uploader.meta_uploader.insgraph_uploader.posts import instagram_post_id, find_instagram_post
from utils.errors import LoginRequiredError, PublishResultUnknownError, UsageError


class InstagramContractTests(unittest.TestCase):
    def test_final_response_requires_matching_owner_caption_and_id(self):
        media = {'id': '123_42', 'pk': '123', 'code': 'ABC', 'user': {'pk': '42'}, 'caption': {'text': 'caption'}}
        payload = {'status': 'ok', 'media': media}
        self.assertEqual(instagram_created_media(payload, owner_id='42', caption='caption'), media)
        self.assertEqual(instagram_response_payload('for (;;);{"payload":{"did_delete":true}}')['payload']['did_delete'], True)
        for bad in ({'payload': {'statusCode': 202}}, {'status': 'ok'}, {'status': 'fail', 'media': media}):
            with self.subTest(bad=bad), self.assertRaises(RuntimeError):
                instagram_created_media(bad, owner_id='42', caption='caption')
        for owner, caption in [('99', 'caption'), ('42', 'another')]:
            with self.assertRaises(RuntimeError):
                instagram_created_media(payload, owner_id=owner, caption=caption)

    def test_real_url_shapes_and_external_url_rejection(self):
        for path in ('p/ABC', 'reel/ABC/', 'creator/p/ABC/', 'creator/reel/ABC/?hl=en'):
            self.assertEqual(instagram_post_id('https://www.instagram.com/' + path), 'ABC')
        for url in ('https://instagram.com.evil/p/ABC/', 'http://instagram.com/p/ABC/',
                    'https://instagram.com/creator/', 'https://bad@instagram.com/p/ABC/',
                    'https://instagram.com:8443/p/ABC/'):
            with self.subTest(url=url), self.assertRaises(ValueError):
                instagram_post_id(url)

    def test_caption_limit_and_mutually_exclusive_media(self):
        # §3.3：同类静态错误统一 UsageError（退出码 2），与 TikTok / 小红书一致。
        with self.assertRaises(UsageError):
            InstagramUploader('unused.json', title='x' * 2201, image_files=['image.png'])
        with self.assertRaises(UsageError):
            InstagramUploader('unused.json', title='title', image_files=['image.png'], video_file='video.mp4')

    def test_publish_deadline_raises_before_publish_click(self):
        app = InstagramUploader('unused.json', title='caption', video_file='video.mp4')

        budget = app.start_publish_budget()
        budget.deadline = time.monotonic() - 1
        with self.assertRaises(RuntimeError) as ctx:
            budget.check_pre_click()

        self.assertIn('15 分钟', str(ctx.exception))
        self.assertIn('尚未点击发布', str(ctx.exception))
        self.assertNotIsInstance(ctx.exception, PublishResultUnknownError)

    def test_publish_timeout_error_distinguishes_click_state(self):
        app = InstagramUploader('unused.json', title='caption', video_file='video.mp4')

        budget = app.start_publish_budget()
        before = budget.timeout_error(False)
        after = budget.timeout_error(True)

        self.assertIsInstance(before, RuntimeError)
        self.assertNotIsInstance(before, PublishResultUnknownError)
        self.assertIsInstance(after, PublishResultUnknownError)
        self.assertIn('禁止自动重发', str(after))

    def test_publish_result_unknown_keeps_exit_code_9_after_capture(self):
        with tempfile.TemporaryDirectory() as folder:
            video = Path(folder) / 'video.mp4'
            video.touch()
            result_file = Path(folder) / 'result.json'
            app = InstagramUploader('unused.json', title='caption', video_file=video, result_file=result_file)
            browser, context, page = AsyncMock(), AsyncMock(), AsyncMock()
            unknown = PublishResultUnknownError('publish result unknown')
            with patch(
                'uploader.meta_uploader.insgraph_uploader.main._open_instagram_page',
                AsyncMock(return_value=(browser, context, page)),
            ), patch(
                'uploader.meta_uploader.insgraph_uploader.main.instagram_identity',
                AsyncMock(return_value={'user_id': '42', 'username': 'creator'}),
            ), patch.object(
                InstagramUploader, '_upload_steps', AsyncMock(side_effect=unknown)
            ), patch.object(
                InstagramUploader, '_capture_failure', AsyncMock()
            ) as capture:
                with self.assertRaises(PublishResultUnknownError):
                    asyncio.run(app.upload())

            self.assertEqual(capture.await_count, 1)

    def test_publish_timeout_after_click_is_result_unknown(self):
        """点击已发出但最终创建响应未到时，必须按结果未知退出，不能重发。"""
        async def scenario():
            async with async_playwright() as p:
                browser = await p.chromium.launch(channel='chrome', headless=True)
                page = await browser.new_page()
                release = asyncio.Event()
                try:
                    html = '''<div role="dialog">
                        <div role="button" onclick="fetch('/api/v1/media/configure_to_clips/', {method:'POST'})">Share</div>
                        <div role="textbox" contenteditable="true" data-lexical-editor="true"></div></div>'''
                    async def route(request):
                        if '/configure_to_clips/' in request.request.url:
                            await release.wait()
                            await request.abort()
                            return
                        await request.fulfill(body=html, content_type='text/html')
                    await page.route('https://www.instagram.com/**', route)
                    await page.goto('https://www.instagram.com/')
                    with tempfile.TemporaryDirectory() as folder:
                        app = InstagramUploader(
                            'unused.json', title='caption', video_file='video.mp4',
                            result_file=Path(folder) / 'result.json',
                        )
                        budget = app.start_publish_budget()
                        budget.deadline = time.monotonic() + 3
                        with self.assertRaises(PublishResultUnknownError):
                            await app._publish(
                                page,
                                {'user_id': '42', 'username': 'creator'},
                                budget=budget,
                            )
                finally:
                    release.set()
                    await browser.close()
        asyncio.run(scenario())

    def test_notification_handler_covers_upload_edit_and_publish(self):
        """handler 只在 ``_upload_steps`` 注册一次，素材阶段不得提前移除。"""
        events = []

        class _RecordingPage:
            """只记录 locator handler 的增删，其余属性透传真实页面。"""

            def __init__(self, page):
                self._page = page

            def __getattr__(self, name):
                return getattr(self._page, name)

            async def add_locator_handler(self, locator, handler):
                events.append('add')
                await self._page.add_locator_handler(locator, handler)

            async def remove_locator_handler(self, locator):
                events.append('remove')
                await self._page.remove_locator_handler(locator)

        async def scenario():
            async with async_playwright() as p:
                browser = await p.chromium.launch(channel='chrome', headless=True)
                page = await browser.new_page()
                try:
                    # 与真实顺序一致：通知提示在点击创建之后才挂载。
                    await page.set_content(
                        f'<body>{_NAVIGATION_HTML}'
                        f'<script>{_DELAYED_NOTIFICATION_SCRIPT}</script></body>'
                    )
                    recorded = _RecordingPage(page)
                    with tempfile.TemporaryDirectory() as folder:
                        video = Path(folder) / 'video.mp4'
                        video.touch()
                        app = InstagramUploader(
                            'unused', title='caption', video_file=video
                        )
                        def record(name):
                            return AsyncMock(
                                side_effect=lambda *args, **kwargs: events.append(name)
                            )

                        original_upload = InstagramUploader._upload_files

                        async def upload_phase(self, page, *, budget):
                            events.append('upload')
                            await original_upload(self, page, budget=budget)

                        with patch.object(
                            InstagramUploader, '_upload_files', upload_phase
                        ), patch.object(
                            InstagramUploader, '_advance_media_editor', record('edit')
                        ), patch.object(
                            InstagramUploader, '_publish', record('publish')
                        ):
                            # 走真实 _upload_files：它若在执行中移除 handler，
                            # 事件顺序会多出一次 remove，编辑与配文阶段即失去保护。
                            await app._upload_steps(
                                recorded, {'user_id': '42'},
                                budget=app.start_publish_budget(),
                            )
                    self.assertEqual(
                        events, ['add', 'upload', 'edit', 'publish', 'remove']
                    )
                    self.assertEqual(await page.locator('#notify').count(), 0)
                finally:
                    await browser.close()

        asyncio.run(scenario())

    def test_verify_and_delete_are_reachable_from_cli(self):
        for action in ('verify', 'delete'):
            args = sau_cli.build_parser().parse_args(['instagram', action, '--account', 'creator',
                '--post-url', 'https://www.instagram.com/p/ABC/', '--expected-text', 'caption'])
            operation = AsyncMock(return_value={'status': 'deleted' if action == 'delete' else 'published'})
            with patch('sau_commands.instagram.instagram_post_action', operation), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(asyncio.run(sau_cli.dispatch(args)), 0)
            self.assertEqual(operation.await_args.kwargs['delete'], action == 'delete')

    def test_cover_cli_reaches_uploader_and_invalid_cover_stops_before_browser(self):
        with tempfile.TemporaryDirectory() as folder:
            video, cover = Path(folder)/'video.mp4', Path(folder)/'cover.PNG'
            video.touch()
            cover.touch()
            args = sau_cli.build_parser().parse_args(['instagram', 'upload-video', '--account', 'creator',
                '--file', str(video), '--thumbnail', str(cover), '--title', 'caption'])
            uploader = AsyncMock(return_value={'status': 'published'})
            with patch.object(InstagramUploader, 'upload', uploader), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(asyncio.run(sau_cli.dispatch(args)), 0)
            # 单独核对请求到构造函数的传递，避免只测 parser 丢失后续接线。
            request = sau_commands.instagram.InstagramUploadRequest('creator', 'caption', '', [], video_file=video, thumbnail=cover)
            with patch('sau_commands.instagram.InstagramUploader') as constructor:
                constructor.return_value.upload = AsyncMock(return_value={})
                asyncio.run(sau_commands.instagram.upload_instagram_content(request))
                self.assertEqual(constructor.call_args.kwargs['thumbnail'], cover)
            with self.assertRaisesRegex(UsageError, '仅用于视频'):
                InstagramUploader('unused', title='caption', image_files=[cover], thumbnail=cover)
            for invalid in (Path(folder)/'missing.png', Path(folder)/'cover.gif'):
                if invalid.suffix == '.gif':
                    invalid.touch()
                app = InstagramUploader('unused', title='caption', video_file=video, thumbnail=invalid)
                with patch('uploader.meta_uploader.insgraph_uploader.main._open_instagram_page', AsyncMock()) as launch:
                    with self.assertRaises((FileNotFoundError, ValueError)):
                        asyncio.run(app.upload())
                    launch.assert_not_called()


# 首页四个导航弹出入口，第二项是创建；脚本让通知提示晚于创建弹窗出现。
_NAVIGATION_HTML = ''.join(
    '<a class="_a6hd" href="#" ' + ('onclick="createPost()"' if i == 1 else '')
    + '><span aria-selected="false">Navigation</span></a>' for i in range(4))

_DELAYED_NOTIFICATION_SCRIPT = """
      function picked(input) {
        const row = document.createElement('div');
        const button = document.createElement('div');
        button.setAttribute('role', 'button');
        button.textContent = 'Next';
        row.appendChild(button);
        input.closest('[role=dialog]').appendChild(row);
      }
      function createPost() {
        setTimeout(function () {
          const dialog = document.createElement('div');
          dialog.setAttribute('role', 'dialog');
          const input = document.createElement('input');
          input.type = 'file';
          input.accept = 'image/jpeg,video/mp4';
          input.addEventListener('change', function () { picked(input); });
          dialog.appendChild(input);
          document.body.appendChild(dialog);
        }, 700);
        // 提示晚于创建弹窗出现：旧实现只保护了点击创建那一下。
        setTimeout(function () {
          const dialog = document.createElement('div');
          dialog.setAttribute('role', 'dialog');
          dialog.id = 'notify';
          // 真实提示全屏覆盖：必须能挡住后续点击才会触发 handler。
          dialog.style.position = 'fixed';
          dialog.style.inset = '0';
          dialog.style.zIndex = '10';
          const icon = document.createElement('img');
          icon.src = 'https://static.cdninstagram.com/rsrc/xxhdpi_launcher.png?test';
          // 固定图标尺寸：占位图异步加载会移动按钮，人类化点击的 stillOn 会按
          // point-drift 硬失败（真实页面的 launcher 图标是已加载的本地资源）。
          icon.style.width = '16px';
          icon.style.height = '16px';
          const zone = document.createElement('div');
          zone.className = '_a9-z';
          const turnOn = document.createElement('button');
          turnOn.textContent = 'Turn On';
          turnOn.addEventListener('click', function () { throw new Error('wrong'); });
          const later = document.createElement('button');
          later.textContent = 'Not Now';
          later.addEventListener('click', function () { dialog.remove(); });
          zone.appendChild(turnOn);
          zone.appendChild(later);
          dialog.appendChild(icon);
          dialog.appendChild(zone);
          document.body.appendChild(dialog);
        }, 50);
      }
    """


class InstagramBrowserRegressionTests(unittest.TestCase):
    def test_optional_prompts_present_absent_and_failed_dismissal(self):
        """按实际图标与按钮层级构造 DOM；覆盖延迟提示、缺席及点击未关闭的异常。"""
        async def scenario():
            async with async_playwright() as p:
                browser = await p.chromium.launch(channel='chrome', headless=True)
                page = await browser.new_page()
                try:
                    # 只保留真实页面的业务结构；不同语言按钮不参与生产定位。
                    html = '''<script>
                      function notification(){document.body.insertAdjacentHTML('beforeend',
                        `<div role="dialog" id="notifications">
                        <img src="https://static.cdninstagram.com/rsrc/xxhdpi_launcher.png?test"
                             style="width:16px;height:16px">
                        <div class="_a9-z"><button onclick="throw Error('wrong action')">Enable</button>
                        <button onclick="this.closest('[role=dialog]').remove()">後で</button></div></div>`);}
                      function create(){document.body.insertAdjacentHTML('beforeend',
                        `<div role="dialog"><input type="file" accept="image/jpeg,video/mp4" onchange="upload()"></div>`);}
                      function upload(){setTimeout(()=>{
                        document.querySelector('[role=dialog]').insertAdjacentHTML('beforeend',
                          '<div role="button">Next</div>');
                        if(document.body.dataset.prompts==='true') document.body.insertAdjacentHTML('beforeend',
                          `<div role="dialog"><img src="https://static.cdninstagram.com/rsrc/reels_nux_icon.png?test"
                               style="width:16px;height:16px">
                          <div class="_a9-z"><div><div><span><button onclick="throw Error('wrong action')">詳しく見る</button></span></div>
                          <div><button onclick="this.closest('[role=dialog]').remove()">OK</button></div></div></div></div>`);
                      },250);}
                      if(document.body.dataset.prompts==='true') setTimeout(notification,250);
                      </script>'''
                    for prompts in (True, False):
                        navigation = ''.join(
                            '<a class="_a6hd" href="#" ' + ('onclick="create()"' if i == 1 else '')
                            + '><span aria-selected="false">Navigation</span></a>' for i in range(4))
                        await page.set_content(f'<body data-prompts="{str(prompts).lower()}">{navigation}{html}</body>')
                        # 通知提示与创建入口都在 250ms 后才出现；先等它们挂载，
                        # 否则 locator handler 可能在提示出现前就被移除。
                        await page.wait_for_timeout(300)
                        with tempfile.TemporaryDirectory() as folder:
                            video = Path(folder)/'video.mp4'
                            video.touch()
                            app = InstagramUploader('unused', title='caption', video_file=video)
                            await app._upload_files(
                                page, budget=app.start_publish_budget()
                            )
                        self.assertEqual(await page.get_by_role('dialog').count(), 1)
                        self.assertEqual(await page.get_by_role('button', name='Next').count(), 1)
                    await page.set_content('<div role="dialog"><button>Unrelated dialog</button></div>')
                    known = page.get_by_role('dialog').filter(has=page.locator('img[src*="reels_nux_icon"]'))
                    self.assertFalse(await _dismiss_optional_prompt(known, known.get_by_role('button')))
                    self.assertEqual(await page.get_by_role('dialog').count(), 1)
                    # 已出现的已知提示若点击后未消失，必须保留异常，不能当作缺席吞掉。
                    await page.set_content('<div role="dialog"><button>Cannot close</button></div>')
                    page.set_default_timeout(300)
                    from patchright.async_api import TimeoutError as BrowserTimeoutError
                    with self.assertRaises(BrowserTimeoutError):
                        await _dismiss_optional_prompt(page.get_by_role('dialog'), page.get_by_role('button'))
                finally:
                    await browser.close()
        asyncio.run(scenario())

    def test_delayed_notification_prompt_does_not_block_upload(self):
        """创建弹窗已打开后才出现的通知提示必须被关闭，不能卡住素材入口。"""
        async def scenario():
            async with async_playwright() as p:
                browser = await p.chromium.launch(channel='chrome', headless=True)
                page = await browser.new_page()
                try:
                    await page.set_content(
                        f'<body>{_NAVIGATION_HTML}'
                        f'<script>{_DELAYED_NOTIFICATION_SCRIPT}</script></body>'
                    )
                    with tempfile.TemporaryDirectory() as folder:
                        video = Path(folder) / 'video.mp4'
                        video.touch()
                        app = InstagramUploader('unused', title='caption', video_file=video)
                        await app._upload_files(page, budget=app.start_publish_budget())
                    # 提示先挡住创建入口，素材弹窗随后才挂载；等待期间必须主动关闭提示。
                    self.assertEqual(await page.locator('#notify').count(), 0)
                    self.assertEqual(await page.get_by_role('button', name='Next').count(), 1)
                finally:
                    await browser.close()
        asyncio.run(scenario())

    def test_composer_without_hash_classes_uses_heading_and_action_roles(self):
        """没有 hash 标题栏时，标题与主动作仍能靠 role + 可访问名推进两步。"""
        async def scenario():
            async with async_playwright() as p:
                browser = await p.chromium.launch(channel='chrome', headless=True)
                page = await browser.new_page()
                try:
                    await page.set_content('''<div role="dialog">
                      <div role="heading" id="heading">Crop</div>
                      <div role="button" id="next" onclick="advance()">Next</div>
                      <section id="media"></section></div>
                      <script>let step=0;function advance(){step++;
                        const h=document.getElementById('heading');
                        if(step===1){h.textContent='Edit';}
                        else{h.textContent='Create new post';
                          document.getElementById('media').innerHTML=
                            '<div contenteditable="true" role="textbox"></div>';}}
                      </script>''')
                    with tempfile.TemporaryDirectory() as folder:
                        image = Path(folder)/'image.png'
                        image.touch()
                        app = InstagramUploader(
                            'unused', title='caption', image_files=[image]
                        )
                        await app._advance_media_editor(
                            page, budget=app.start_publish_budget()
                        )
                    self.assertEqual(
                        await page.locator('[role=heading]').inner_text(),
                        'Create new post',
                    )
                    self.assertEqual(
                        await page.locator('[contenteditable=true][role=textbox]').count(),
                        1,
                    )
                finally:
                    await browser.close()
        asyncio.run(scenario())

    def test_prompt_dismisses_when_action_zone_hash_is_missing(self):
        """动作区 hash 类名变化时，仍能关闭已识别的可选提示。"""
        async def scenario():
            async with async_playwright() as p:
                browser = await p.chromium.launch(channel='chrome', headless=True)
                page = await browser.new_page()
                try:
                    await page.set_content('''<div role="dialog" id="notify">
                      <img src="https://static.cdninstagram.com/rsrc/xxhdpi_launcher.png?test">
                      <button>Turn On</button>
                      <button onclick="document.getElementById('notify').remove()">Not Now</button>
                      </div>''')
                    notify = page.get_by_role('dialog')
                    self.assertTrue(
                        await InstagramUploader._dismiss_prompt(page, notify)
                    )
                    self.assertEqual(await page.get_by_role('dialog').count(), 0)
                finally:
                    await browser.close()
        asyncio.run(scenario())

    def test_create_entry_uses_icon_label_and_generic_file_input(self):
        """导航顺序变化、素材 accept 不含 video 时，仍按图标 aria-label 打开创建。"""
        async def scenario():
            async with async_playwright() as p:
                browser = await p.chromium.launch(channel='chrome', headless=True)
                page = await browser.new_page()
                try:
                    await page.set_content('''<a href="#"><span>Notifications</span></a>
                      <a href="#" id="create" onclick="createPost()">
                        <svg aria-label="New post" width="24" height="24"></svg></a>
                      <a href="#"><span>Settings</span></a>
                      <script>function createPost(){
                        const dialog=document.createElement('div');
                        dialog.setAttribute('role','dialog');
                        dialog.innerHTML='<input type="file" accept="image/jpeg,image/png">'
                          + '<div role="button">Next</div>';
                        document.body.appendChild(dialog);
                      }</script>''')
                    with tempfile.TemporaryDirectory() as folder:
                        image = Path(folder)/'image.png'
                        image.touch()
                        app = InstagramUploader(
                            'unused', title='caption', image_files=[image]
                        )
                        await app._upload_files(
                            page, budget=app.start_publish_budget()
                        )
                    self.assertEqual(
                        await page.locator('[role=dialog] input[type=file]')
                        .evaluate('e=>e.files.length'),
                        1,
                    )
                finally:
                    await browser.close()
        asyncio.run(scenario())

    def test_create_entry_uses_label_as_primary_selector(self):
        """4 个入口同时存在时，仍以 New post 标签为主，不盲取第二项。"""
        async def scenario():
            async with async_playwright() as p:
                browser = await p.chromium.launch(channel='chrome', headless=True)
                page = await browser.new_page()
                try:
                    links = []
                    for index in range(4):
                        if index == 1:
                            links.append(
                                '<a class="_a6hd" href="#" id="create">'
                                '<span aria-selected="false">'
                                '<svg aria-label="New post"></svg></span></a>'
                            )
                        else:
                            links.append(
                                '<a class="_a6hd" href="#">'
                                '<span aria-selected="false">nav</span></a>'
                            )
                    await page.set_content(''.join(links))
                    entry = await _create_entry(page, budget=None)
                    self.assertEqual(await entry.get_attribute('id'), 'create')
                finally:
                    await browser.close()
        asyncio.run(scenario())

    def test_cover_waits_for_actual_preview_and_rejects_wrong_image(self):
        """真实 Chrome 中延迟替换预览，核对原图字节；错误预览必须停在编辑页。"""
        async def scenario():
            import base64
            import struct
            import zlib
            # 构造带正确 CRC 的 1×1 RGB PNG，避免依赖额外图像库或损坏的压缩样例。
            def chunk(kind, data):
                return struct.pack('!I', len(data)) + kind + data + struct.pack('!I', zlib.crc32(kind + data))
            png = (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('!2I5B', 1, 1, 8, 2, 0, 0, 0))
                   + chunk(b'IDAT', zlib.compress(b'\x00\xff\x00\x00')) + chunk(b'IEND', b''))
            async with async_playwright() as p:
                browser = await p.chromium.launch(channel='chrome', headless=True)
                page = await browser.new_page()
                try:
                    html = '''<input type="file" accept="image/jpeg,image/png" id="outside">
                      <div role="dialog"><div role="heading">crop</div>
                      <div role="button" onclick="advance()">Next</div><section id="media"></section></div>
                      <script>let step=0;function advance(){step++;
                        const h=document.querySelector('[role=heading]');
                        if(step===1){h.textContent='edit'; document.querySelector('#media').innerHTML=
                          `<input type="file" accept="image/png,image/jpeg" onchange="coverChanged(this)">
                           <video></video><div style="background-image:url(old)"></div>`;
                        }else{h.textContent='compose';document.querySelector('#media').innerHTML+=
                          '<div contenteditable="true" role="textbox" data-lexical-editor="true"></div>';}}
                      function coverChanged(input){setTimeout(()=>{const blob=document.body.dataset.wrong ?
                        new Blob([Uint8Array.from(atob('PNG_BASE64'), c=>c.charCodeAt(0))],{type:'image/png'}) : input.files[0];
                        document.querySelector('video + div').style.backgroundImage=`url("${URL.createObjectURL(blob)}")`;
                      },250);}</script>'''
                    html = html.replace('PNG_BASE64', base64.b64encode(png).decode())
                    await page.route('https://www.instagram.com/**', lambda route: route.fulfill(body=html, content_type='text/html'))
                    with tempfile.TemporaryDirectory() as folder:
                        cover = Path(folder)/'cover.png'
                        cover.write_bytes(png)
                        app = InstagramUploader('unused', title='caption', video_file='video.mp4', thumbnail=cover)
                        await page.goto('https://www.instagram.com/')
                        await app._advance_media_editor(
                            page, budget=app.start_publish_budget()
                        )
                        self.assertEqual(await page.locator('[role=heading]').inner_text(), 'compose')
                        self.assertEqual(await page.locator('#outside').evaluate('e=>e.files.length'), 0)
                        await page.reload()
                        # 可解码但非指定文件的预览同样不能通过（本次改用不同有效 PNG 文件字节）。
                        cover.write_bytes(png + b'other image bytes')
                        await page.locator('body').evaluate("e=>e.dataset.wrong='true'")
                        with self.assertRaisesRegex(RuntimeError, '预览与指定图片不匹配'):
                            await app._advance_media_editor(
                                page, budget=app.start_publish_budget()
                            )
                        self.assertEqual(await page.locator('[role=heading]').inner_text(), 'edit')
                finally:
                    await browser.close()
        asyncio.run(scenario())

    def test_delayed_login_foreign_owner_and_async_reel_creation(self):
        """用真实 Chrome DOM 和网络事件验证：延迟页面不能误判、同配文不能跨作者、202 必须等正式作品。"""
        async def scenario():
            async with async_playwright() as p:
                browser = await p.chromium.launch(channel='chrome', headless=True)
                page = await browser.new_page()
                try:
                    await page.set_content('''<script>setTimeout(() => {
                        document.body.innerHTML = '<a href="/direct/inbox/?hl=ja">Inbox</a>';
                    }, 250)</script>''')
                    self.assertFalse(await _is_instagram_logged_out(page))
                    foreign = '''<meta property="og:url" content="https://www.instagram.com/p/ABC/">
                        <meta property="instapp:owner_user_id" content="99"><main>same caption</main>'''
                    await page.route('https://www.instagram.com/p/ABC/', lambda r: r.fulfill(body=foreign, content_type='text/html'))
                    with self.assertRaisesRegex(RuntimeError, '作者'):
                        await find_instagram_post(page, post_url='https://www.instagram.com/p/ABC/', expected_text='same caption', owner_id='42')
                    await page.unroute_all()
                    own = foreign.replace('content="99"', 'content="42"') + '<meta name="description" content="different caption"><meta property="al:ios:url" content="instagram://media?id=123">'
                    await page.route('https://www.instagram.com/p/ABC/', lambda r: r.fulfill(body=own, content_type='text/html'))
                    with self.assertRaisesRegex(RuntimeError, '配文元数据'):
                        await find_instagram_post(page, post_url='https://www.instagram.com/p/ABC/', expected_text='same caption', owner_id='42')
                    await page.unroute_all()
                    own = own.replace('different caption', 'same caption')
                    await page.route('https://www.instagram.com/p/ABC/', lambda r: r.fulfill(body=own, content_type='text/html'))
                    verified = await find_instagram_post(page, post_url='https://www.instagram.com/p/ABC/', expected_text='same caption', owner_id='42')
                    self.assertEqual(verified['content_id'], '123_42')
                    await page.unroute_all()
                    html = '''<div role="dialog">
                        <div role="button" onclick="document.body.dataset.clicks=String(Number(document.body.dataset.clicks||0)+1); submitPost()">Share</div>
                        <div role="textbox" contenteditable="true" data-lexical-editor="true"></div></div>
                        <script>async function submitPost() {
                          await fetch('/api/v1/media/configure_to_clips/', {method:'POST'});
                          document.body.dataset.processing='true';
                          // 202 与最终响应之间留出足够窗口：人类化点击后事件循环更忙，
                          // 350ms 会让“任务仍未结束”的断言偶发失败，与 202 语义无关。
                          setTimeout(() => fetch('/api/v1/media/configure_to_clips/', {method:'POST'}), 1500);
                        }</script>'''
                    calls = 0
                    async def route(request):
                        nonlocal calls
                        if '/configure_to_clips/' not in request.request.url:
                            await request.fulfill(body=html, content_type='text/html')
                            return
                        calls += 1
                        if calls == 1:
                            payload = {'payload': {'statusCode': 202}}
                        else:
                            payload = {'payload': {'media': {'id': '123_42', 'code': 'ABC', 'user': {'pk': '42'}, 'caption': {'text': 'caption'}}}}
                        await request.fulfill(body='for (;;);' + json.dumps(payload), content_type='application/json')
                    await page.route('https://www.instagram.com/**', route)
                    await page.goto('https://www.instagram.com/')
                    with tempfile.TemporaryDirectory() as folder:
                        target = Path(folder)/'result.json'
                        app = InstagramUploader('unused.json', title='caption', video_file='video.mp4', result_file=target)
                        task = asyncio.create_task(app._publish(
                            page,
                            {'user_id': '42', 'username': 'creator'},
                            budget=app.start_publish_budget(),
                        ))
                        await page.locator('body[data-processing="true"]').wait_for()
                        self.assertFalse(task.done(), '202 后仍必须等待最终创建响应')
                        self.assertNotEqual(app.result['status'], 'published')
                        await task
                        self.assertEqual(app.result['status'], 'published')
                        self.assertEqual(app.result['content_id'], '123_42')
                        self.assertEqual(await page.locator('body').get_attribute('data-clicks'), '1')
                        self.assertEqual(calls, 2)
                finally:
                    await browser.close()
        asyncio.run(scenario())


class InstagramLoginGuardTests(unittest.TestCase):
    """§7.3/D：Instagram 未登录（守卫错误）必须映射为退出码 10。"""

    def test_unauthenticated_upload_exits_10(self):
        with tempfile.TemporaryDirectory() as folder:
            image = Path(folder) / 'image.png'
            image.touch()
            guard = AsyncMock(side_effect=LoginRequiredError('Instagram 未登录'))
            with patch.object(
                sau_commands.instagram, 'upload_instagram_content', guard
            ), contextlib.redirect_stdout(io.StringIO()), \
                    contextlib.redirect_stderr(io.StringIO()):
                code = sau_cli.main([
                    'instagram', 'upload-note', '--account', 'creator',
                    '--images', str(image), '--title', 'caption',
                ])
        self.assertEqual(code, 10)
        guard.assert_awaited_once()



# ---------------------------------------------------------------------------
# C 层哨兵：DOM 结构一律按 2026-11-10 有头实测（real-dom-2026-11-10.md）构造。
# 这些 fixture 故意复刻真实页面的“难用”之处：折叠行没有 aria-expanded、
# 面板边缘有覆盖层拦截鼠标、开关在标签的兄弟列、Alt text 是行内折叠区、
# 地点候选是无 ARIA role 的普通 div。旧选择器在这些结构上必须失败。
# ---------------------------------------------------------------------------

# 开关行：标签列 + 开关列是兄弟；开关自身与父元素 textContent 为空。
def _switch_row(row_id: str, label: str, switch_id: str, description: str) -> str:
    """构造一行真实配文页开关；行 id、文案与开关 id 由调用方区分。"""
    return f'''
  <div class="row" id="{row_id}">
    <div>
      <div><span dir="auto">{label}</span></div>
      <div><span>{description}</span></div>
    </div>
    <div><div><div><div>
      <input id="{switch_id}" role="switch" type="checkbox" aria-checked="false">
    </div></div></div></div>
  </div>'''


_AI_ROW_HTML = _switch_row(
    'ai-row', 'Add AI label', 'ai-switch',
    'This label is required for realistic photos and videos made with AI.',
)

# 真实配文页同时有三项开关；干扰项故意排在 Add AI label 之前，纯“取第一个
# [role=switch]”的实现必须在这里失败。
_AI_LABEL_HTML = (
    '''
<div role="dialog" id="compose">
  <div class="_ac76"><div role="heading">Create new post</div></div>'''
    + _switch_row(
        'hide-like-row', 'Hide like and view counts', 'hide-like-switch',
        'The like and view counts on this post will be hidden.',
    )
    + _AI_ROW_HTML
    + _switch_row(
        'comments-row', 'Turn off commenting', 'comments-switch',
        'You can change this later by going to the ··· menu at the top of your post.',
    )
    + '''
  <div role="textbox" contenteditable="true" data-lexical-editor="true"></div>
</div>
<script>
  for (const input of document.querySelectorAll('[role=switch]')) {
    input.addEventListener('click', () => {
      input.dataset.clicks = String(Number(input.dataset.clicks || 0) + 1);
      input.setAttribute('aria-checked', String(input.checked));
    });
  }
</script>
'''
)

# Advanced settings：行内折叠，无 aria-expanded，chevron 表状态，行上有覆盖层。
# 真实配文页收起面板时仍保留面板内的 switch 节点（只是不可见），因此这里用
# display:none 收起、而不是清空 innerHTML——只看“DOM 里有 switch”的实现会误判。
_ADVANCED_HTML = (
    '''
<div role="dialog" id="compose">
  <div class="_ac76"><div role="heading">Create new post</div></div>'''
    + _AI_ROW_HTML
    + '''
  <div style="position: relative">
    <div id="advanced" role="button" tabindex="0" aria-disabled="false"
         style="cursor: pointer;">
      <span dir="auto">Advanced settings</span>
      <span style="display: inline-block; transform: rotate(0deg);">
        <svg aria-label="Down chevron icon" role="img" width="16" height="16">
          <title>Down chevron icon</title></svg>
      </span>
    </div>
    <div id="advanced-overlay"
         style="position: absolute; left: 0; right: 0; top: 0; height: 44px; z-index: 10;"></div>
    <div id="advanced-panel" style="display: none">
      <div class="row" id="comments-row">
        <div>
          <div><span dir="auto">Turn off commenting</span></div>
          <div><span>You can change this later by going to the ··· menu at the top of your post.</span></div>
        </div>
        <div><div><div><div>
          <input id="comments-switch" role="switch" type="checkbox" aria-checked="false">
        </div></div></div></div>
      </div>
    </div>
  </div>
  <div role="textbox" contenteditable="true" data-lexical-editor="true"></div>
</div>
<script>
  const advancedRow = document.getElementById('advanced');
  const advancedPanel = document.getElementById('advanced-panel');
  let advancedOpen = false;
  const commentsSwitch = document.getElementById('comments-switch');
  commentsSwitch.addEventListener('click', () => {
    commentsSwitch.setAttribute('aria-checked', String(commentsSwitch.checked));
  });
  function toggleAdvanced() {
    advancedOpen = !advancedOpen;
    advancedRow.dataset.clicks = String(Number(advancedRow.dataset.clicks || 0) + 1);
    advancedRow.querySelector('svg').setAttribute(
      'aria-label', advancedOpen ? 'Up chevron icon' : 'Down chevron icon');
    advancedPanel.style.display = advancedOpen ? '' : 'none';
  }
  advancedRow.addEventListener('keydown', (event) => {
    if (event.key === 'Enter') { event.preventDefault(); toggleAdvanced(); }
  });
  advancedRow.addEventListener('click', toggleAdvanced);
</script>
'''
)

# Accessibility：行内折叠区；输入框展开时才挂载，折叠时移除但值保留。
# 值只在字段显式失焦（blur）时提交——折叠导致的焦点移动不算，避免产品代码
# 省略 blur 却被“顺带失焦”掩盖。
_ALT_HTML = '''
<div role="dialog" id="compose">
  <div class="_ac76"><div role="heading">Create new post</div></div>
  <div style="position: relative">
    <div id="accessibility" role="button" tabindex="0" aria-disabled="false"
         style="cursor: pointer;">
      <span dir="auto">Accessibility</span>
      <span style="display: inline-block; transform: rotate(0deg);">
        <svg aria-label="Down chevron icon" role="img" width="16" height="16">
          <title>Down chevron icon</title></svg>
      </span>
    </div>
    <div id="accessibility-overlay"
         style="position: absolute; left: 0; right: 0; top: 0; height: 44px; z-index: 10;"></div>
  </div>
  <div id="alt-section"></div>
  <div role="textbox" contenteditable="true" data-lexical-editor="true"></div>
</div>
<script>
  const accessibilityRow = document.getElementById('accessibility');
  const altSection = document.getElementById('alt-section');
  const altValues = ['', ''];
  let altOpen = false;
  function renderAlt() {
    altSection.innerHTML = '';
    if (!altOpen) return;
    altValues.forEach((value, index) => {
      const input = document.createElement('input');
      input.type = 'text';
      input.setAttribute('aria-label', 'Alt text');
      if (!value) input.setAttribute('placeholder', 'Alt text');
      input.value = value;
      // 实测：input 事件不写入页面状态，只有失焦才提交。这里进一步要求“字段
      // 自己失焦”（relatedTarget 为空）：焦点移到折叠行并不算提交，因此产品
      // 代码必须显式 blur，否则重开折叠区只能读到空值。
      input.addEventListener('blur', (event) => {
        if (event.relatedTarget) return;
        altValues[index] = input.value;
      });
      altSection.appendChild(input);
    });
  }
  function toggleAlt() {
    altOpen = !altOpen;
    accessibilityRow.querySelector('svg').setAttribute(
      'aria-label', altOpen ? 'Up chevron icon' : 'Down chevron icon');
    renderAlt();
  }
  accessibilityRow.addEventListener('keydown', (event) => {
    if (event.key === 'Enter') { event.preventDefault(); toggleAlt(); }
  });
  accessibilityRow.addEventListener('click', toggleAlt);
</script>
'''

# 地点：候选是无 ARIA role 的普通 div，尺寸/位置才是判据。
# 真实结构：联想列表由 portal 挂到 body，**不在** [role=dialog] 内；仍留在
# dialog 里的 fixture 会让“回退到 dialog 作用域”的实现也通过。
_LOCATION_HTML = '''
<div role="dialog" id="compose">
  <div class="_ac76"><div role="heading">Create new post</div></div>
  <div class="_abgh _aw1v">
    <label><input aria-label="Add location" placeholder="Add location"
                  name="creation-location-input" autocomplete="off"></label>
  </div>
  <div role="textbox" contenteditable="true" data-lexical-editor="true"></div>
</div>
<!-- 真实结构：portal 滚动容器挂在页面根，候选行是它的直接子节点 -->
<div id="suggestions" style="overflow-y:auto; max-height:240px; width:320px"></div>
<script>
  const locationCandidates = ['Shanghai, China', 'Hangzhou', 'Shanghai'];
  const locationInput = document.querySelector('input[placeholder="Add location"]');
  locationInput.addEventListener('input', () => {
    const list = document.getElementById('suggestions');
    list.innerHTML = '';
    const wanted = locationInput.value.trim().toLowerCase();
    if (!wanted) return;
    setTimeout(() => {
      const matches = locationCandidates.filter(
        (label) => label.toLowerCase().includes(wanted));
      document.body.dataset.candidates = matches.join('|');
      list.innerHTML = '';
      for (const label of matches) {
        const row = document.createElement('div');
        row.style.height = '60px';
        row.style.width = '237px';
        row.textContent = label;
        row.addEventListener('click', () => {
          locationInput.value = label;
          document.body.dataset.clicked = label;
          list.innerHTML = '';
        });
        list.appendChild(row);
      }
    }, 200);
  });
</script>
'''


class InstagramLocationOptionDomTests(unittest.TestCase):
    """C1：真实 Chrome 里驱动真实控件注册表完成 输入 → 联想 → 选中 → 回读。"""

    def test_exact_location_suggestion_is_selected_and_read_back(self):
        async def scenario():
            from uploader.meta_uploader.insgraph_uploader.controls import (
                resolve_instagram_option_controls,
            )
            from uploader.meta_uploader.insgraph_uploader.options import (
                InstagramPublishOptions,
            )

            async with async_playwright() as p:
                browser = await p.chromium.launch(channel='chrome', headless=True)
                page = await browser.new_page()
                try:
                    # 候选按子串过滤，因此 "Shanghai, China" 会先于精确的 "Shanghai"
                    # 出现；没有 role=option，只有尺寸与位置可辨。
                    await page.set_content(_LOCATION_HTML)
                    with tempfile.TemporaryDirectory() as folder:
                        image = Path(folder) / 'image.png'
                        image.touch()
                        app = InstagramUploader(
                            'unused.json', title='caption',
                            image_files=[str(image)],
                            options=InstagramPublishOptions(location='  shanghai '),
                            result_file=Path(folder) / 'result.json',
                        )
                        # 走真实注册表：不注入 controls，由 resolve_instagram_option_controls 构造。
                        await app._apply_options(
                            page, budget=app.start_publish_budget()
                        )
                        record = app.result['options']['location']
                        self.assertEqual(record['status'], 'set')
                        # applied 是页面候选标签，不是原始请求值。
                        self.assertEqual(record['applied'], 'Shanghai')
                        self.assertEqual(record['requested'], '  shanghai ')
                        # 模糊候选 "Shanghai, China" 确实出现过，但没有被点击。
                        self.assertIn(
                            'Shanghai, China',
                            await page.locator('body').get_attribute('data-candidates'),
                        )
                        self.assertEqual(
                            await page.locator('body').get_attribute('data-clicked'),
                            'Shanghai',
                        )
                        self.assertEqual(
                            await page.locator('#suggestions > div').count(), 0
                        )
                        # 输入框为空时阅读地点区块文本（防御旧版 chip 结构）。
                        await page.evaluate('''() => {
                            const input = document.querySelector('input[placeholder="Add location"]');
                            input.value = '';
                            const chip = document.createElement('div');
                            chip.setAttribute('role', 'button');
                            chip.textContent = 'Shanghai, China';
                            input.closest('._abgh').appendChild(chip);
                        }''')
                        controls = resolve_instagram_option_controls(
                            page, image_count=1
                        )
                        self.assertEqual(
                            await controls['location'].read(), 'Shanghai, China'
                        )
                finally:
                    await browser.close()
        asyncio.run(scenario())


class InstagramLocationStaleListTests(unittest.TestCase):
    """C1 反例：候选项点击后若没有从 DOM 卸载，不能把输入框文本当成已选地点。"""

    def test_suggestion_that_never_detaches_is_mismatch(self):
        async def scenario():
            from uploader.meta_uploader.insgraph_uploader.options import (
                InstagramPublishOptions,
            )

            async with async_playwright() as p:
                browser = await p.chromium.launch(channel='chrome', headless=True)
                page = await browser.new_page()
                try:
                    # 与真实页面同构：无 role，只靠尺寸与位置识别；点击只改输入框，
                    # 列表节点故意保留（模拟“看起来选中、其实没生效”）。
                    await page.set_content('''<div role="dialog">
                        <div style="height:44px"><input placeholder="Add location" autocomplete="off"></div>
                        <!-- 真实结构：portal 滚动容器，候选行是它的直接子节点 -->
  <div id="suggestions" style="overflow-y:auto; max-height:240px; width:320px"></div>
                      </div>
                      <script>
                        const input = document.querySelector('input[placeholder="Add location"]');
                        input.addEventListener('input', () => {
                          const list = document.getElementById('suggestions');
                          if (!input.value.trim()) return;
                          setTimeout(() => {
                            list.innerHTML = '';
                            for (const label of ['Shanghai, China', 'Shanghai']) {
                              const row = document.createElement('div');
                              row.style.height = '60px';
                              row.style.width = '300px';
                              const text = document.createElement('div');
                              text.textContent = label;
                              row.appendChild(text);
                              row.onclick = () => { input.value = label; };
                              list.appendChild(row);
                            }
                          }, 100);
                        });
                      </script>''')
                    with tempfile.TemporaryDirectory() as folder:
                        image = Path(folder) / 'image.png'
                        image.touch()
                        app = InstagramUploader(
                            'unused.json', title='caption',
                            image_files=[str(image)],
                            options=InstagramPublishOptions(location='Shanghai'),
                            result_file=Path(folder) / 'result.json',
                        )
                        with self.assertRaises(RuntimeError) as ctx:
                            await app._apply_options(
                                page, budget=app.start_publish_budget()
                            )
                    self.assertIn('location=mismatch', str(ctx.exception))
                    self.assertEqual(
                        app.result['options']['location']['status'], 'mismatch'
                    )
                    # 输入框里已经是候选标签，但列表没消失，不能算 set。
                    self.assertEqual(
                        await page.locator('#suggestions > div').count(), 2
                    )
                finally:
                    await browser.close()
        asyncio.run(scenario())


class InstagramCommentsOptionDomTests(unittest.TestCase):
    """C3：真实 Chrome 下 Advanced settings → Turn off commenting 开关的读写回读。"""

    def test_comments_switch_expands_advanced_settings_once(self):
        """展开、点击、回读一次完成；重复应用不得再次展开或点击。"""
        async def scenario():
            async with async_playwright() as p:
                browser = await p.chromium.launch(channel='chrome', headless=True)
                page = await browser.new_page()
                try:
                    # 实测：折叠行无 aria-expanded，且行上有覆盖层拦截鼠标；
                    # 开关在标签的兄弟列，checked 语义是“评论已关闭”，初始 false；
                    # 面板收起时只 display:none，switch 节点仍在 DOM 里（不可见）。
                    await page.set_content(_ADVANCED_HTML)
                    page.set_default_timeout(2_000)
                    with tempfile.TemporaryDirectory() as folder:
                        image = Path(folder) / 'image.png'
                        image.touch()
                        app = InstagramUploader(
                            'unused.json', title='caption', image_files=[image],
                            options=InstagramPublishOptions(comments=False),
                            result_file=Path(folder) / 'result.json',
                        )
                        await app._apply_options(
                            page=page, budget=app.start_publish_budget()
                        )
                        # 折叠行不维护 aria-expanded，展开与否只能看内容/chevron。
                        self.assertIsNone(
                            await page.locator('#advanced').get_attribute('aria-expanded')
                        )
                        self.assertEqual(
                            await page.locator('#advanced').get_attribute('data-clicks'), '1'
                        )
                        self.assertEqual(
                            await page.locator('#comments-switch').get_attribute('aria-checked'),
                            'true',
                        )
                        self.assertEqual(
                            app.result['options']['comments'],
                            {'requested': False, 'applied': False, 'status': SET},
                        )
                        # 第二次应用：高级设置已展开、开关已 off，必须零点击。
                        await app._apply_options(
                            page=page, budget=app.start_publish_budget()
                        )
                        self.assertEqual(
                            await page.locator('#advanced').get_attribute('data-clicks'), '1'
                        )
                        self.assertEqual(
                            app.result['options']['comments']['status'], DEFAULT_OFF
                        )
                        self.assertEqual(
                            await page.locator('#comments-switch').get_attribute('aria-checked'),
                            'true',
                        )
                finally:
                    await browser.close()
        asyncio.run(scenario())


class InstagramAltTextDomTests(unittest.TestCase):
    """C2：真实 Chrome 中 Accessibility 行内折叠区的填写、折叠与重开回读。"""

    def test_alt_text_accordion_roundtrip_sets_both_images(self):
        from uploader.meta_uploader.insgraph_uploader.options import (
            SET,
            InstagramPublishOptions,
        )

        async def scenario():
            async with async_playwright() as p:
                browser = await p.chromium.launch(channel='chrome', headless=True)
                page = await browser.new_page()
                try:
                    # 实测：没有嵌套 dialog / Done 按钮；输入框随折叠区挂载与移除。
                    await page.set_content(_ALT_HTML)
                    page.set_default_timeout(2_000)
                    with tempfile.TemporaryDirectory() as folder:
                        images = [Path(folder) / f'{index}.png' for index in range(2)]
                        for image in images:
                            image.touch()
                        requested = ('第一张图的描述', '第二张图的描述')
                        app = InstagramUploader(
                            'unused.json', title='caption', image_files=images,
                            options=InstagramPublishOptions(alt_texts=requested),
                            result_file=Path(folder) / 'result.json',
                        )
                        # 不注入 controls：走真实注册表 + 真实 DOM。
                        await app._apply_options(
                            page, budget=app.start_publish_budget()
                        )
                        self.assertEqual(
                            app.result['options']['alt_text'],
                            {'requested': list(requested), 'applied': list(requested),
                             'status': SET},
                        )
                        # 结束时恢复为原先的收起状态：输入框从 DOM 移除。
                        self.assertEqual(
                            await page.locator('#alt-section input').count(), 0
                        )
                        self.assertEqual(
                            await page.locator('#accessibility')
                            .locator('svg').get_attribute('aria-label'),
                            'Down chevron icon',
                        )
                        # 值在折叠/重开后保留：重新展开即可读回。
                        await page.locator('#accessibility').focus()
                        await page.keyboard.press('Enter')
                        self.assertEqual(
                            await page.locator('input[aria-label="Alt text"]')
                            .evaluate_all('(inputs) => inputs.map((input) => input.value)'),
                            list(requested),
                        )
                        # 收回复起状态，避免影响后续断言。
                        await page.locator('#accessibility').focus()
                        await page.keyboard.press('Enter')
                        self.assertEqual(await page.get_by_role('dialog').count(), 1)
                finally:
                    await browser.close()
        asyncio.run(scenario())


class InstagramAiLabelDomTests(unittest.TestCase):
    """C4：真实 Chrome 下配文页 Add AI label 开关的开启与幂等回读。"""

    def test_ai_label_switch_turns_on_once(self):
        """请求开启 → 点击一次 → 回读 set；再次应用不得重复点击。"""
        async def scenario():
            async with async_playwright() as p:
                browser = await p.chromium.launch(channel='chrome', headless=True)
                page = await browser.new_page()
                try:
                    # 实测：开关在标签的兄弟列，开关自身与父元素 textContent 为空；
                    # aria-checked 初始 false，点击后翻转。
                    await page.set_content(_AI_LABEL_HTML)
                    with tempfile.TemporaryDirectory() as folder:
                        app = InstagramUploader(
                            'unused.json', title='caption', video_file='video.mp4',
                            options=InstagramPublishOptions(ai_generated=True),
                            result_file=Path(folder) / 'result.json',
                        )
                        # 不注入 controls：走真实注册表 + 真实 DOM。
                        await app._apply_options(
                            page=page, budget=app.start_publish_budget()
                        )
                        self.assertEqual(
                            app.result['options']['ai_generated'],
                            {'requested': True, 'applied': True, 'status': SET},
                        )
                        switch = page.locator('#ai-switch')
                        self.assertEqual(
                            await switch.get_attribute('aria-checked'), 'true'
                        )
                        self.assertEqual(
                            await switch.get_attribute('data-clicks'), '1'
                        )
                        # 第二次应用：开关已 on，必须零点击且仍记 set。
                        await app._apply_options(
                            page=page, budget=app.start_publish_budget()
                        )
                        self.assertEqual(
                            await switch.get_attribute('data-clicks'), '1'
                        )
                        self.assertEqual(
                            app.result['options']['ai_generated'],
                            {'requested': True, 'applied': True, 'status': SET},
                        )
                finally:
                    await browser.close()
        asyncio.run(scenario())
