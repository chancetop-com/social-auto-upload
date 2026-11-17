"""Opt-in persistent local lifecycle; legacy and managed sessions are unchanged."""
import asyncio
from contextlib import asynccontextmanager
from loguru import logger

from utils.browser_session import BrowserSession
from utils.local_browser import resolve_local_browser
from utils.local_profile import acquire_local_profile
from utils.errors import LoginRequiredError


@asynccontextmanager
async def local_browser_session(playwright, *, platform, account, headless=None,
                                local_browser=None, configuration=None, create=False,
                                profile_root=None, context_kwargs=None, context_setup=None):
    config = configuration or resolve_local_browser(headless=headless, local_browser=local_browser)
    with acquire_local_profile(platform, account, config.kind, root=profile_root, create=create) as profile:
        if not profile.exists:
            raise LoginRequiredError(f'本地 Profile 不存在；请先运行 sau {platform} login --account {account!r} --local-browser {config.kind}')
        try:
            context = await playwright.chromium.launch_persistent_context(
                user_data_dir=str(profile.path), **dict(context_kwargs or {}), **config.launch_options)
        except Exception as error:
            raise RuntimeError(f'本地浏览器启动失败 source={config.source} browser_kind={config.kind} headless={config.headless}: {error}；未切换来源或运行模式。') from error
        try:
            if context_setup:
                await context_setup(context)
            version = getattr(context.browser, 'version', None) or config.version
            resolved_path = config.executable_path or (getattr(playwright.chromium, 'executable_path', 'unknown') if config.kind == 'chromium' else 'unknown')
            logger.info('mode=local source={} resolved_path={} browser_kind={} version={} headless={} profile={}',
                        config.source, resolved_path, config.kind, version, config.headless, profile.path)
            yield BrowserSession(browser=context.browser, context=context, mode='local')
        finally:
            await close_persistent_context(context)


CLOSE_TIMEOUT_SECONDS = 10


async def close_persistent_context(context):
    """Bounded best-effort close; persistent context owns the browser.

    A fresh cancellation during cleanup waits only the remaining bound before
    propagating. Failed closes never turn a confirmed publication into a retry.
    """
    task = asyncio.create_task(context.close())
    deadline = asyncio.get_running_loop().time() + CLOSE_TIMEOUT_SECONDS
    cancelled = False
    try:
        try:
            done, _ = await asyncio.wait({task}, timeout=CLOSE_TIMEOUT_SECONDS)
        except asyncio.CancelledError:
            cancelled = True
            done, _ = await asyncio.wait({task}, timeout=max(0, deadline - asyncio.get_running_loop().time()))
        if not done:
            task.cancel()
            logger.warning('Persistent context cleanup timed out; preserving operation result. Profile may remain occupied; no takeover or retry.')
        elif task.cancelled():
            logger.warning('Persistent context cleanup cancelled; preserving operation result.')
        elif task.exception() is not None:
            logger.warning('Persistent context cleanup failed; preserving operation result: {}', task.exception())
    finally:
        if not task.done():
            task.cancel()
        if cancelled:
            raise asyncio.CancelledError
