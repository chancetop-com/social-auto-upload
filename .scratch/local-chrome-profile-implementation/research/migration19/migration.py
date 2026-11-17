"""Temporary one-time orchestration. Remove after the actual selected migration."""
import asyncio
from pathlib import Path
import stat
import unicodedata
from utils.browser_session import BrowserSession
from utils.local_browser import resolve_local_browser
from utils.local_profile import acquire_local_profile

def locate(base, platform, account):
    if not account.strip() or account in ('.', '..') or any(c in account for c in ('/', '\\', '\x00')):
        raise RuntimeError('unsafe account alias')
    base = Path(base).resolve()
    directory = base / 'cookies'
    if directory.is_symlink() or (directory.exists() and not directory.is_dir()):
        raise RuntimeError('unsafe cookies directory')
    targets = [directory / f'{platform}_{account}.json']
    if platform in ('dayu', 'zhihu', 'xueqiu'):
        targets.append(targets[0].with_suffix('.identity.json'))
    names = list(directory.iterdir()) if directory.exists() else []
    folded = lambda name: unicodedata.normalize('NFC', name).casefold()
    for target in targets:
        matches = [p for p in names if folded(p.name) == folded(target.name)]
        if matches and (len(matches) != 1 or matches[0].name != target.name):
            raise RuntimeError(f'ambiguous legacy target: {target}')
        try: mode = target.lstat().st_mode
        except FileNotFoundError: continue
        if not stat.S_ISREG(mode): raise RuntimeError(f'legacy target is not a regular file: {target}')
    return targets

async def strict_close(context, timeout):
    task = asyncio.create_task(context.close())
    deadline = asyncio.get_running_loop().time() + timeout
    cancelled = False
    try:
        try:
            done, _ = await asyncio.wait({task}, timeout=timeout)
        except asyncio.CancelledError:
            cancelled = True
            done, _ = await asyncio.wait({task}, timeout=max(0, deadline - asyncio.get_running_loop().time()))
        if cancelled: raise asyncio.CancelledError()
        if not done: raise TimeoutError('strict normal browser close timed out; deletion vetoed')
        task.result()
    finally:
        if not task.done(): task.cancel()

async def migrate(playwright, *, platform, account, base, login, probe, close_timeout=10, context_kwargs=None, record=lambda **event: None):
    config = resolve_local_browser(headless=False)
    targets = locate(base, platform, account)
    options = {**dict(context_kwargs or {}), **config.launch_options}
    with acquire_local_profile(platform, account, config.kind, root=Path(base)/'browser_profiles', create=True) as profile:
        for stage, action in [('login', login), ('reopen', probe)]:
            context = await playwright.chromium.launch_persistent_context(user_data_dir=str(profile.path), **options)
            record(stage=stage, launched=True, profile=str(profile.path), browser_kind=config.kind, source=config.source, headless=config.headless, version=getattr(context.browser, "version", "unknown"))
            try:
                positive = await action(BrowserSession(browser=context.browser, context=context, mode='local'))
                if positive is not True: raise RuntimeError(f'{stage}: no positive login evidence')
                record(stage=stage, positive=True)
            finally:
                await strict_close(context, close_timeout)
                record(stage=stage, close='normal')
        locate(base, platform, account)
        try:
            for target in targets:
                target.unlink(missing_ok=True)
        except OSError as exc:
            remaining = [str(path) for path in targets if path.exists() or path.is_symlink()]
            record(cleanup='failed', remaining=remaining)
            raise RuntimeError(f'legacy cleanup failed; remaining={remaining}: {exc}') from exc
        record(cleanup='complete', targets=[str(path) for path in targets])
