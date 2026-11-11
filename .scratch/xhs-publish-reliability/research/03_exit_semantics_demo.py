"""03 决议用的离线演示：把真实提交段跑在可编排的假页面上。

不做真实网络访问、不发布任何东西。目的只有一个：把「点击 → URL 变化 → 例外」
的组合，映射成**当前代码**实际产生的退出码与点击次数，用来判断
「点击后落登录页」到底该报 9 还是 10。

运行： python3 .scratch/xhs-publish-reliability/research/03_exit_semantics_demo.py
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import uploader.xiaohongshu_uploader.main as xhs  # noqa: E402
from utils.errors import LoginRequiredError, PublishResultUnknownError  # noqa: E402

PUBLISH_URL = "https://creator.xiaohongshu.com/publish/publish?from=homepage&target=video"
SUCCESS_URL = "https://creator.xiaohongshu.com/publish/success?target=video"
LOGIN_URL = f"https://creator.xiaohongshu.com/login?source=&redirectReason=401&lastUrl={PUBLISH_URL}"


class FastBudget(xhs.PublishTimeoutBudget):
    """把 15 分钟压到 2 秒，只为演示。"""

    def __init__(self, platform, **kwargs):
        kwargs["timeout_seconds"] = 2.0
        super().__init__(platform, **kwargs)


xhs.PublishTimeoutBudget = FastBudget


class _Preview:
    async def inner_text(self):
        return "上传成功 1080p"


class _PreviewHost:
    async def query_selector(self, selector):
        return _Preview()


class _Locator:
    def __init__(self, page, selector):
        self.page = page
        self.selector = selector

    @property
    def first(self):
        return self

    def nth(self, index):
        return self

    async def count(self):
        return 0

    async def is_visible(self):
        return False

    async def inner_text(self):
        return ""

    async def set_input_files(self, files):
        return None

    async def click(self):
        self.page.clicks += 1
        mode = self.page.click_mode

        if mode == "miss":
            raise TimeoutError("locator.click: Timeout 30000ms exceeded.")

        if mode == "dispatch_then_raise_once":
            self.page.url = self.page.after_click_url
            if self.page.clicks == 1:
                raise RuntimeError("Target closed")
            return

        self.page.url = self.page.after_click_url


class FakePage:
    def __init__(self, *, click_mode, after_click_url, start_url=PUBLISH_URL):
        self.url = start_url
        self.click_mode = click_mode
        self.after_click_url = after_click_url
        self.clicks = 0

    async def goto(self, url):
        self.url = url

    async def wait_for_url(self, url, **kwargs):
        self.url = url

    async def wait_for_selector(self, selector, **kwargs):
        return _PreviewHost()

    def locator(self, selector):
        return _Locator(self, selector)

    async def screenshot(self, **kwargs):
        return None

    async def close(self):
        return None


async def _ignore(*args, **kwargs):
    return None


def _build_app():
    app = xhs.XiaoHongShuVideo(
        title="演示标题",
        file_path="demo.mp4",
        tags=[],
        publish_date=0,
        account_file="demo-cookies.json",
        debug=False,
    )
    app.publish_not_before = None
    app.fill_meta = _ignore
    app.set_thumbnail = _ignore
    app.apply_declarations = _ignore
    return app


def _exit_code(exc):
    if exc is None:
        return 0
    if isinstance(exc, LoginRequiredError):
        return 10
    if isinstance(exc, PublishResultUnknownError):
        return 9
    return 1


async def run(scenario, *, click_mode, after_click_url, managed):
    app = _build_app()
    page = FakePage(click_mode=click_mode, after_click_url=after_click_url)
    exc = None
    try:
        await app.upload_video_content(page, multilogin=managed)
    except Exception as error:  # noqa: BLE001 - 演示需要捕获全部
        exc = error
    return {
        "scenario": scenario,
        "mode": "托管" if managed else "本地",
        "exits": _exit_code(exc),
        "error": type(exc).__name__ if exc else "-",
        "clicks": page.clicks,
        "final_url": page.url.split("?")[0],
    }


SCENARIOS = [
    ("S1 点击命中 → 跳登录页（路由守卫）", "ok", LOGIN_URL),
    ("S2 点击命中 → 跳成功页", "ok", SUCCESS_URL),
    ("S3 点击命中 → URL 不动", "ok", PUBLISH_URL),
    ("S4 点击命中不了（选择器失效）", "miss", PUBLISH_URL),
    ("S5 已派发但随即抛错", "dispatch_then_raise_once", SUCCESS_URL),
]


async def main():
    rows = []
    for name, mode, url in SCENARIOS:
        for managed in (True, False):
            rows.append(await run(name, click_mode=mode, after_click_url=url, managed=managed))

    width = max(len(r["scenario"]) for r in rows)
    print(f"{'场景'.ljust(width)} | 模式 | exit | 异常 | 点击次数 | 落地 URL")
    print("-" * (width + 60))
    for r in rows:
        print(
            f"{r['scenario'].ljust(width)} | {r['mode']} | {r['exits']:>4} | "
            f"{r['error']:<24} | {r['clicks']:>5} 次 | {r['final_url']}"
        )


if __name__ == "__main__":
    asyncio.run(main())
