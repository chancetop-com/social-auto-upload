"""知乎作品提交后的只读核验。"""
from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urlsplit

from patchright.async_api import async_playwright, expect

from utils.local_browser_session import local_browser_session
from uploader.zhihu_uploader.session import (
    account_alias, check_zhihu_account, raise_if_login_required, read_zhihu_identity,
)


async def verify_zhihu_result(account_file=None, result_file=None, headless=None, *,
                              account_name=None, local_browser=None, session=None) -> dict:
    """只读打开结果文件保存的作品 URL；缺 URL 时要求先查询创作中心原作品。"""
    result_file = Path(result_file).resolve()
    result = json.loads(result_file.read_text(encoding="utf-8"))
    expected = result.get("identity")
    if not isinstance(expected, dict) or not expected.get("name") or not expected.get("avatar_path"):
        raise ValueError("结果文件缺少原作品作者信息，无法核验")
    url = result.get("url")
    if not url:
        raise ValueError(
            "结果文件没有知乎作品 URL；请在创作中心的内容管理中按标题和提交时间核对原作品，勿重新上传"
        )
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.hostname not in {"www.zhihu.com", "zhuanlan.zhihu.com"}:
        raise ValueError("结果文件中的知乎作品 URL 不受支持")
    if not re.search(r"/(?:p|pin|zvideo|video)/\d+/?$", parsed.path):
        raise ValueError("结果文件 URL 未包含知乎文章或视频作品 ID")

    if session is None:
        async with async_playwright() as playwright:
            async with local_browser_session(playwright, platform="zhihu",
                    account=account_alias(account_file, account_name), headless=headless,
                    local_browser=local_browser) as owned:
                return await verify_zhihu_result(result_file=result_file, session=owned)
    await check_zhihu_account(session=session)
    page = await session.context.new_page()
    try:
        response = await page.goto(url, wait_until="domcontentloaded", timeout=45000)
    except Exception:
        raise_if_login_required(page, managed=False)
        raise
    if response is not None and response.status >= 400:
        raise RuntimeError(f"知乎原作品 URL 访问失败，HTTP {response.status}")
    raise_if_login_required(page, managed=False)
    try:
        if await read_zhihu_identity(page, strict=True) != expected:
            raise RuntimeError("知乎当前账号与原作品作者证据不一致，请登录原作品账号后核验")
        title = result.get("title")
        if not title:
            raise ValueError("结果文件缺少标题，无法核对原作品")
        # 新版视频详情把标题与简介放在同一正文区，标题后还带分隔符。
        await expect(page.locator("main")).to_contain_text(title, timeout=30000)
    except Exception:
        raise_if_login_required(page, managed=False)
        raise
    result.update(success=True, status="published", verified=True)
    result_file.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result
