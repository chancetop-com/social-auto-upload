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
    InstagramUploader, _is_instagram_logged_out, instagram_created_media, instagram_response_payload,
    _dismiss_optional_prompt,
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
                    html = '''<div role="dialog"><div class="_ac76">
                        <div role="button" onclick="fetch('/api/v1/media/configure_to_clips/', {method:'POST'})">任意语言</div>
                        </div><div role="textbox" contenteditable="true" data-lexical-editor="true"></div></div>'''
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
                        <img src="/images/instagram/xig/ico/xxhdpi_launcher.png?test">
                        <div class="_a9-z"><button onclick="throw Error('wrong action')">Enable</button>
                        <button onclick="this.closest('[role=dialog]').remove()">後で</button></div></div>`);}
                      function create(){document.body.insertAdjacentHTML('beforeend',
                        `<div role="dialog"><input type="file" accept="image/jpeg,video/mp4" onchange="upload()"></div>`);}
                      function upload(){setTimeout(()=>{
                        document.querySelector('[role=dialog]').insertAdjacentHTML('beforeend',
                          '<div class="_ac76"><div role="button">Next</div></div>');
                        if(document.body.dataset.prompts==='true') document.body.insertAdjacentHTML('beforeend',
                          `<div role="dialog"><img src="/images/instagram/clips/reels_nux_icon.png?test">
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
                        self.assertEqual(await page.locator('._ac76 [role=button]').count(), 1)
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
                      <div role="dialog"><div class="_ac76"><div role="heading">crop</div>
                      <button role="button" onclick="advance()">任意语言</button></div><section id="media"></section></div>
                      <script>let step=0;function advance(){step++;
                        const h=document.querySelector('[role=heading]');
                        if(step===1){h.textContent='edit'; document.querySelector('#media').innerHTML=
                          `<input type="file" accept="image/jpeg,image/png" onchange="coverChanged(this)">
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
                    html = '''<div role="dialog"><div class="_ac76">
                        <div role="button" onclick="document.body.dataset.clicks=String(Number(document.body.dataset.clicks||0)+1); submitPost()">任意语言</div>
                        </div><div role="textbox" contenteditable="true" data-lexical-editor="true"></div></div>
                        <script>async function submitPost() {
                          await fetch('/api/v1/media/configure_to_clips/', {method:'POST'});
                          document.body.dataset.processing='true';
                          setTimeout(() => fetch('/api/v1/media/configure_to_clips/', {method:'POST'}), 350);
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
                    # 真实页面输入后异步（debounce）挂载联想项；候选按子串过滤，
                    # 因此 "Shanghai, China" 会先于精确的 "Shanghai" 出现。
                    # 点击候选才写入输入框值，回读值因此可观察。
                    html = '''<div role="dialog"><div class="_ac76">
                        <div role="heading">Create new post</div></div>
                      <div class="row"><input placeholder="Add location" autocomplete="off"></div>
                      <div role="textbox" contenteditable="true" data-lexical-editor="true"></div>
                      <div id="suggestions"></div></div>
                      <script>
                        const candidates = ['Shanghai, China', 'Hangzhou', 'Shanghai'];
                        const input = document.querySelector('input[placeholder="Add location"]');
                        input.addEventListener('input', () => {
                          const list = document.getElementById('suggestions');
                          list.innerHTML = '';
                          const wanted = input.value.trim().toLowerCase();
                          if (!wanted) return;
                          setTimeout(() => {
                            const matches = candidates.filter(
                              label => label.toLowerCase().includes(wanted));
                            document.body.dataset.candidates = matches.join('|');
                            list.innerHTML = '';
                            // 真实列表可能夹带空文案项；下标漂移会让点击落到错误候选。
                            const blank = document.createElement('div');
                            blank.setAttribute('role', 'option');
                            blank.textContent = '   ';
                            list.appendChild(blank);
                            for (const label of matches) {
                              const option = document.createElement('div');
                              option.setAttribute('role', 'option');
                              option.textContent = label;
                              option.onclick = () => {
                                input.value = label;
                                document.body.dataset.clicked = label;
                                list.innerHTML = '';
                              };
                              list.appendChild(option);
                            }
                          }, 200);
                        });
                      </script>'''
                    await page.set_content(html)
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
                        # 输入框为空时回读已选地点 chip 文本。
                        await page.evaluate('''() => {
                            const input = document.querySelector('input[placeholder="Add location"]');
                            input.value = '';
                            const chip = document.createElement('div');
                            chip.setAttribute('role', 'button');
                            chip.textContent = 'Shanghai, China';
                            input.parentElement.appendChild(chip);
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


class InstagramCommentsOptionDomTests(unittest.TestCase):
    """C3：真实 Chrome 下 Advanced settings → Turn off commenting 开关的读写回读。"""

    def test_comments_switch_expands_advanced_settings_once(self):
        """展开、点击、回读一次完成；重复应用不得再次展开或点击。"""
        async def scenario():
            async with async_playwright() as p:
                browser = await p.chromium.launch(channel='chrome', headless=True)
                page = await browser.new_page()
                try:
                    # 结构按实测：折叠入口带 aria-expanded，开关是行内 input[role=switch]，
                    # checked 语义是“评论已关闭”，初始 false。
                    await page.set_content('''
                      <div role="dialog">
                        <div id="advanced" role="button" aria-expanded="false">Advanced settings</div>
                        <div id="panel" hidden>
                          <div class="row"><span>Turn off commenting</span>
                            <input role="switch" type="checkbox" aria-checked="false"></div>
                        </div>
                      </div>
                      <script>
                        const advanced = document.getElementById('advanced');
                        const panel = document.getElementById('panel');
                        const toggle = document.querySelector('input[role="switch"]');
                        advanced.addEventListener('click', () => {
                          advanced.dataset.clicks = String(Number(advanced.dataset.clicks || 0) + 1);
                          advanced.setAttribute('aria-expanded', 'true');
                          panel.hidden = false;
                        });
                        toggle.addEventListener('click', () => {
                          toggle.setAttribute('aria-checked', String(toggle.checked));
                        });
                      </script>
                    ''')
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
                        self.assertEqual(
                            await page.locator('#advanced').get_attribute('data-clicks'), '1'
                        )
                        self.assertEqual(
                            await page.locator('input[role=switch]').get_attribute('aria-checked'),
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
                            await page.locator('input[role=switch]').get_attribute('aria-checked'),
                            'true',
                        )
                finally:
                    await browser.close()
        asyncio.run(scenario())


class InstagramAltTextDomTests(unittest.TestCase):
    """C2：真实 Chrome 中 Accessibility 模态框的填写、关闭与重开回读。"""

    def test_alt_text_modal_roundtrip_sets_both_images(self):
        from uploader.meta_uploader.insgraph_uploader.options import (
            SET,
            InstagramPublishOptions,
        )

        async def scenario():
            async with async_playwright() as p:
                browser = await p.chromium.launch(channel='chrome', headless=True)
                page = await browser.new_page()
                try:
                    # 配文页本身是创建弹窗；无障碍模态框是它内部新开的另一个 dialog。
                    # 实测结构：入口 Accessibility，模态框内每张图一个 Alt text 输入框。
                    await page.set_content('''<div role="dialog" id="compose">
                      <div class="_ac76"><div role="heading">Create new post</div></div>
                      <div role="button" id="accessibility" aria-expanded="false"
                           onclick="toggleAltModal()">Accessibility</div>
                      <div role="dialog" id="alt-modal" style="display:none">
                        <div role="heading">Accessibility</div>
                        <label>Photo 1 <input type="text" placeholder="Alt text"></label>
                        <label>Photo 2 <input type="text" placeholder="Alt text"></label>
                        <div role="button" id="done" onclick="toggleAltModal()">Done</div>
                      </div>
                    </div>
                    <script>function toggleAltModal() {
                      const modal = document.getElementById('alt-modal');
                      const open = modal.style.display === 'none';
                      modal.style.display = open ? 'block' : 'none';
                      document.getElementById('accessibility')
                        .setAttribute('aria-expanded', String(open));
                    }</script>''')
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
                        # 两次填写按 --images 顺序落到对应输入框。
                        self.assertEqual(
                            await page.locator('input[placeholder="Alt text"]')
                            .evaluate_all('(inputs) => inputs.map((input) => input.value)'),
                            list(requested),
                        )
                        # 回读确实重新打开了模态框：结束时已关闭且值仍在。
                        self.assertFalse(await page.locator('#alt-modal').is_visible())
                        self.assertEqual(
                            await page.locator('#accessibility')
                            .get_attribute('aria-expanded'),
                            'false',
                        )
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
                    # 结构按 06 实测：配文弹窗内的行内 input[role=switch]，
                    # aria-checked 初始 false，点击后翻转。
                    await page.set_content('''
                      <div role="dialog">
                        <div class="row"><span>Add AI label</span>
                          <input role="switch" type="checkbox" aria-checked="false"></div>
                      </div>
                      <script>
                        const toggle = document.querySelector('input[role="switch"]');
                        toggle.addEventListener('click', () => {
                          toggle.dataset.clicks =
                            String(Number(toggle.dataset.clicks || 0) + 1);
                          toggle.setAttribute('aria-checked', String(toggle.checked));
                        });
                      </script>
                    ''')
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
                        switch = page.locator('input[role=switch]')
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
