"""Instagram 原作品删除：菜单项按精确文案定位（真机验收 2026-11-11）。

真实详情页的“···”菜单已增至 9 项，`Delete` 不再固定在首位。用例用真实 Chrome
复刻可测结构：详情元数据、三圆点菜单按钮、9 项菜单与“删除/取消”确认框，验证
定位只看文案、点击的确实是 `Delete`；反例覆盖“菜单里没有精确 Delete 项”时不得
猜其他条目。
"""
from __future__ import annotations

import asyncio
import contextlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from patchright.async_api import async_playwright

from uploader.meta_uploader.insgraph_uploader import posts

POST_URL = 'https://www.instagram.com/p/ABC/'
OWNER_ID = '42'
CONTENT_ID = '123_42'
EXPECTED_TEXT = '原有配文里的短句'
DELETE_URL = f'https://www.instagram.com/api/v1/web/create/{CONTENT_ID}/delete/'


def _post_page_html(
    menu_items: list[str], confirm_labels: tuple[str, ...] = ('Delete', 'Cancel')
) -> str:
    """作品详情页：``find_instagram_post`` 需要的元数据 + 菜单与确认框。"""
    items = '[' + ', '.join(f'"{label}"' for label in menu_items) + ']'
    confirm = '[' + ', '.join(f'"{label}"' for label in confirm_labels) + ']'
    return f'''
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <meta property="og:url" content="{POST_URL}">
  <meta property="instapp:owner_user_id" content="{OWNER_ID}">
  <meta name="description" content="creator 的帖子：{EXPECTED_TEXT} #tag">
  <meta property="al:ios:url" content="instagram://media?id=123">
</head>
<body>
<main><article>{EXPECTED_TEXT}</article></main>
<div role="button" aria-haspopup="dialog" id="more" onclick="openMenu()">
  <svg width="24" height="24"><circle cx="12" cy="12" r="2.5"></circle></svg>
</div>
<script>
  const MENU_ITEMS = {items};
  function openMenu() {{
    const dialog = document.createElement('div');
    dialog.setAttribute('role', 'dialog');
    MENU_ITEMS.forEach((label, index) => {{
      const button = document.createElement('button');
      button.textContent = label;
      button.addEventListener('click', () => {{
        document.body.dataset.clicked = label;
        document.body.dataset.clickedIndex = String(index);
        if (label === 'Delete') openConfirm();
      }});
      dialog.appendChild(button);
    }});
    document.body.appendChild(dialog);
  }}
  function openConfirm() {{
    const confirm = document.createElement('div');
    confirm.setAttribute('role', 'dialog');
    confirm.setAttribute('aria-modal', 'true');
    const heading = document.createElement('div');
    heading.setAttribute('role', 'heading');
    heading.textContent = 'Delete post?';
    confirm.appendChild(heading);
    const labels = {confirm};
    labels.forEach((label) => {{
      const button = document.createElement('button');
      button.textContent = label;
      button.addEventListener('click', () => {{
        document.body.dataset.confirmed = label;
        if (label === 'Delete') {{
          fetch('/api/v1/web/create/{CONTENT_ID}/delete/', {{method: 'POST'}});
        }}
      }});
      confirm.appendChild(button);
    }});
    document.body.appendChild(confirm);
  }}
</script>
</body>
</html>
'''


class InstagramPostDeleteTests(unittest.TestCase):
    """§4.4：菜单项按文案定位；``Delete`` 不在首位也必须命中，找不到就报错。"""

    async def _run_delete_flow(
        self, menu_items, *, confirm_labels=('Delete', 'Cancel')
    ):
        """在真实 Chrome 中执行删除流程；返回结果、点击记录与删除请求。"""
        delete_requests: list[str] = []

        async def route(request):
            if (
                request.request.method == 'POST'
                and '/api/v1/web/create/' in request.request.url
            ):
                delete_requests.append(request.request.url)
                await request.fulfill(
                    body='for (;;);{"payload":{"did_delete":true}}',
                    content_type='application/json',
                )
                return
            await request.fulfill(
                body=_post_page_html(menu_items, confirm_labels),
                content_type='text/html',
            )

        async with async_playwright() as p:
            browser = await p.chromium.launch(channel='chrome', headless=True)
            context = await browser.new_context()
            page = await context.new_page()
            try:
                await page.route('https://www.instagram.com/**', route)
                with tempfile.TemporaryDirectory() as folder:
                    folder = Path(folder)
                    # 产品会把失败证据写到相对路径 .local/；切到临时目录，避免污染仓库。
                    with contextlib.chdir(folder):
                        browser_handle = MagicMock()
                        browser_handle.close = AsyncMock()
                        with (
                            patch.object(
                                posts,
                                '_open_instagram_page',
                                AsyncMock(
                                    return_value=(browser_handle, context, page)
                                ),
                            ),
                            patch.object(
                                posts,
                                'instagram_identity',
                                AsyncMock(
                                    return_value={
                                        'user_id': OWNER_ID,
                                        'username': 'creator',
                                    }
                                ),
                            ),
                            # 缩短等待窗口：失败用例不必等生产默认超时。
                            patch.object(posts, '_MENU_TIMEOUT_MS', 1_000),
                            patch.object(posts, '_CONFIRM_TIMEOUT_MS', 2_000),
                            patch.object(
                                posts, '_DELETE_RESPONSE_TIMEOUT_MS', 5_000
                            ),
                        ):
                            try:
                                result = await posts.instagram_post_action(
                                    folder / 'account.json',
                                    post_url=POST_URL,
                                    expected_text=EXPECTED_TEXT,
                                    delete=True,
                                    result_file=folder / 'result.json',
                                )
                                error = None
                            except RuntimeError as captured:
                                result, error = None, captured
                    clicked = await page.locator('body').get_attribute(
                        'data-clicked'
                    )
                    clicked_index = await page.locator('body').get_attribute(
                        'data-clicked-index'
                    )
                    confirmed = await page.locator('body').get_attribute(
                        'data-confirmed'
                    )
                return (
                    result, error, clicked, clicked_index, confirmed,
                    delete_requests,
                )
            finally:
                with contextlib.suppress(Exception):
                    await browser.close()

    def test_delete_menu_item_is_located_by_label_not_index(self):
        menu_items = [
            'Edit', 'Pin to profile', 'Delete', 'Go to post', 'Share to…',
            'Copy link', 'Embed', 'Unpin from profile', 'About this account',
        ]
        result, error, clicked, clicked_index, confirmed, requests = asyncio.run(
            self._run_delete_flow(menu_items)
        )
        self.assertIsNone(error)
        self.assertEqual(result['status'], 'deleted')
        self.assertEqual(result['content_id'], CONTENT_ID)
        # 按下标取项会点成 Edit；命中 Delete 才能走到删除确认。
        self.assertEqual((clicked, clicked_index), ('Delete', '2'))
        self.assertEqual(confirmed, 'Delete')
        self.assertEqual(requests, [DELETE_URL])

    def test_confirm_action_is_located_by_label_when_cancel_is_first(self):
        """确认框按钮顺序不可假设：Cancel 在首位时仍必须点中 Delete。"""
        menu_items = ['Edit', 'Delete', 'Cancel']
        result, error, clicked, clicked_index, confirmed, requests = asyncio.run(
            self._run_delete_flow(
                menu_items, confirm_labels=('Cancel', 'Delete')
            )
        )
        self.assertIsNone(error)
        self.assertEqual(result['status'], 'deleted')
        self.assertEqual((clicked, clicked_index), ('Delete', '1'))
        self.assertEqual(confirmed, 'Delete')
        self.assertEqual(requests, [DELETE_URL])

    def test_confirm_without_exact_delete_label_fails_closed(self):
        """确认框没有精确 Delete 文案时不得按首位猜测（首位是 Cancel）。"""
        menu_items = ['Edit', 'Delete', 'Cancel']
        result, error, clicked, clicked_index, confirmed, requests = asyncio.run(
            self._run_delete_flow(
                menu_items, confirm_labels=('Cancel', 'Remove')
            )
        )
        self.assertIsNone(result)
        self.assertIsNotNone(error)
        # 菜单项仍会被点开，但确认框里不能点任何按钮。
        self.assertEqual((clicked, clicked_index), ('Delete', '1'))
        self.assertIsNone(confirmed)
        self.assertEqual(requests, [])

    def test_menu_without_exact_delete_raises_and_never_clicks(self):
        # 只有模糊干扰项：没有文案精确等于 Delete 的条目，不能猜。
        menu_items = ['Edit', 'Delete forever', 'Delete from profile', 'Cancel']
        result, error, clicked, clicked_index, confirmed, requests = asyncio.run(
            self._run_delete_flow(menu_items)
        )
        self.assertIsNone(result)
        self.assertIsNotNone(error)
        self.assertIn('Instagram 原作品操作未完成', str(error))
        self.assertIsNone(clicked)
        self.assertIsNone(clicked_index)
        self.assertIsNone(confirmed)
        self.assertEqual(requests, [])


if __name__ == '__main__':
    unittest.main()
