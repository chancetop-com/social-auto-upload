"""Temporary actual migration entry; explicit original data and worktree source."""
import asyncio
import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ORIGINAL = Path('/Users/chancetio/Desktop/Web/social-media-auto-upload/social-auto-upload')
WORKTREE = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(WORKTREE))
spec = importlib.util.spec_from_file_location('conf', ORIGINAL / 'conf.py')
conf = importlib.util.module_from_spec(spec)
sys.modules['conf'] = conf
spec.loader.exec_module(conf)
assert Path(conf.BASE_DIR).resolve() == ORIGINAL
from patchright.async_api import async_playwright
from migration import migrate, locate
from utils.local_browser import resolve_local_browser
from utils.errors import LoginRequiredError

TARGETS = {'tiktok':'lukechen','rednote':'rednote','instagram':'luke','xiaohongshu':'180'}
platform = sys.argv[1]
account = TARGETS[platform]

def record(**event):
    event = {'time':datetime.now(timezone.utc).isoformat(), 'platform':platform, 'account':account, **event}
    print(json.dumps(event, ensure_ascii=False), flush=True)
    with (WORKTREE/'.scratch/local-chrome-profile-implementation/research/19-live-events.jsonl').open('a') as stream:
        stream.write(json.dumps(event, ensure_ascii=False)+'\n')

async def probe(session):
    if platform == 'tiktok':
        from uploader.tk_uploader.main_chrome import is_logged_in
        valid = await is_logged_in(session.context, managed=False)
    elif platform == 'instagram':
        from uploader.meta_uploader.insgraph_uploader.main import _navigate_local_page, instagram_identity
        page = await session.context.new_page()
        await _navigate_local_page(page, timeout=60_000)
        await instagram_identity(page)
        valid = True
    else:
        if platform == 'rednote':
            from uploader.rednote_uploader.main import probe_session
        else:
            from uploader.xiaohongshu_uploader.main import probe_session
        kind, _ = await probe_session(session.context, close_page=False)
        valid = kind == 'valid'
    if not valid: raise LoginRequiredError(f'{platform}: positive login evidence absent')
    return True

async def login(session):
    if platform == 'tiktok':
        from uploader.tk_uploader.main_chrome import login_in
        record(state='opening_login_browser', profile=str(ORIGINAL/'browser_profiles'/platform/account/'chrome'))
        await login_in(session)
        return True
    if platform == 'rednote':
        from uploader.rednote_uploader.main import rednote_setup
        record(state='opening_login_browser')
        return await rednote_setup(handle=True, account_name=account, headless=False,
                                   session=session, max_checks=1200)
    if platform == 'instagram':
        from uploader.meta_uploader.insgraph_uploader.main import _navigate_local_page, instagram_identity
        page = await session.context.new_page()
        await _navigate_local_page(page, 'https://www.instagram.com/accounts/login/')
        record(state='waiting_for_human_login')
        await page.locator('a[href^="/direct/inbox/"]').wait_for(state='visible', timeout=3600_000)
        await instagram_identity(page)
        return True
    from uploader.xiaohongshu_uploader.main import (_build_xhs_creator_url, _save_xhs_qrcode,
        _cleanup_login_qrcode, classify_blocked, XHS_LOGIN_SUCCESS_SETTLE_SECONDS)
    from utils.humanize import Humanizer
    page = await session.context.new_page()
    await page.goto(_build_xhs_creator_url('/login'))
    await Humanizer(page).after_navigate()
    info = await _save_xhs_qrcode(page, str(ORIGINAL/'browser_profiles'/platform/account/'chrome/login'))
    qrpath = Path(info['image_path'])
    record(state='waiting_for_human_login', qr_path=str(qrpath))
    try:
        for _ in range(1200):
            if await classify_blocked(page) is None:
                await asyncio.sleep(XHS_LOGIN_SUCCESS_SETTLE_SECONDS)
                return await probe(session)
            await asyncio.sleep(3)
        raise RuntimeError('waiting for human login timed out')
    finally:
        _cleanup_login_qrcode(qrpath)

async def main():
    config = resolve_local_browser(headless=False)
    assert config.kind == 'chrome' and config.source == 'channel=chrome' and not config.headless
    targets = locate(ORIGINAL, platform, account)
    record(state='preflight', source_root=str(WORKTREE), conf_path=conf.__file__, data_root=str(conf.BASE_DIR),
           browser_kind=config.kind, source=config.source, headless=config.headless,
           targets=[{'path':str(p), 'exists':p.exists()} for p in targets])
    context_kwargs = {}
    if platform == 'instagram':
        from uploader.meta_uploader.insgraph_uploader.main import _proxy_options
        context_kwargs = {'proxy': _proxy_options(None)}
        record(proxy_configured=context_kwargs['proxy'] is not None)
    async with async_playwright() as playwright:
        await migrate(playwright, platform=platform, account=account, base=ORIGINAL,
                      login=login, probe=probe, context_kwargs=context_kwargs, record=record)
    record(state='complete')

if __name__ == '__main__':
    try: asyncio.run(main())
    except BaseException as exc:
        record(state='failed', error_type=type(exc).__name__, error=str(exc),
               remaining=[str(p) for p in locate(ORIGINAL,platform,account) if p.exists()])
        raise
