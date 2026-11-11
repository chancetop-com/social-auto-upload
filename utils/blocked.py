# -*- coding: utf-8 -*-
"""登录页 / 人机验证页分类（共享层，零平台知识）。

判定器只读页面状态，不注入脚本、不点击、不导航。规则是数据：

* **URL path 优先**：只比较 ``urlsplit(url).path``，不读 query、不做 unquote；
  多个前缀同时命中时取最长者（``/website-login/captcha`` 压过
  ``/website-login``）。前缀按**路径段边界**匹配：``/login`` 命中 ``/login``
  与 ``/login/step2``，不命中 ``/loginx``。
* **DOM 补强**：path 未命中时才查登录框，按 ``utils.dom`` 的 ``visible`` 档
  判定；path 命中直接返回，绝不查 DOM。
* **读失败 = 不拦截**：URL / 定位器 / 可见性探测抛错一律视为「没有命中」。
  网络故障与页面失效不是登录态失效。

``BlockedKind`` 只有两种取值，由调用方决定文案与退出码（小红书为 ``10``）。

依赖方向（spec §3 U11 B）：只允许 patchright、stdlib 与 ``utils.dom``；
不 import ``uploader.*`` / ``sau_commands.*`` / 平台常量。
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Literal
from urllib.parse import urlsplit

from utils.dom import check

BlockedKind = Literal["login", "verification"]


@dataclass(frozen=True)
class BlockedRules:
    """一个平台的风控页面规则（数据，不含判定逻辑）。"""

    login_paths: tuple[str, ...]
    verification_paths: tuple[str, ...]
    login_box_selector: str


async def classify(
    page: Any,
    rules: BlockedRules,
    *,
    visibility_check: Callable[[Any], Awaitable[bool] | bool] | None = None,
) -> BlockedKind | None:
    """返回 ``"login"`` / ``"verification"`` / ``None``。

    ``visibility_check`` 注入可见性判据：``checker(locator)`` 或
    ``checker(locator, "visible")`` 皆可（可返回 awaitable）；默认走
    ``utils.dom.check(locator, "visible")``。任何读取失败都返回 ``None``。
    """
    path = _page_path(page)
    if path is None:
        return None

    kind = _match_path(path, rules)
    if kind is not None:
        return kind

    if await _login_box_visible(page, rules, visibility_check):
        return "login"
    return None


def _page_path(page: Any) -> str | None:
    """读 ``main_frame.url``（回退 ``page.url``）的 path；读不到返回 ``None``。"""
    try:
        frame = getattr(page, "main_frame", None)
        url = getattr(frame, "url", None) if frame is not None else None
        if not url:
            url = getattr(page, "url", None)
    except Exception:
        return None
    if not isinstance(url, str) or not url.strip():
        return None
    try:
        return urlsplit(url).path
    except ValueError:
        return None


def _matches(path: str, prefix: str) -> bool:
    if not prefix:
        return False
    if path == prefix or path == prefix.rstrip("/"):
        return True
    return path.startswith(prefix.rstrip("/") + "/")


def _match_path(path: str, rules: BlockedRules) -> BlockedKind | None:
    """最长前缀优先；同长度时 verification 胜出（它更具体）。"""
    matches: list[tuple[int, BlockedKind]] = []
    for prefix in rules.login_paths:
        if _matches(path, prefix):
            matches.append((len(prefix.rstrip("/")), "login"))
    for prefix in rules.verification_paths:
        if _matches(path, prefix):
            matches.append((len(prefix.rstrip("/")), "verification"))
    if not matches:
        return None
    return max(matches, key=lambda item: (item[0], item[1] == "verification"))[1]


async def _login_box_visible(
    page: Any,
    rules: BlockedRules,
    visibility_check: Callable[..., Awaitable[bool] | bool] | None,
) -> bool:
    try:
        locator = page.locator(rules.login_box_selector)
    except Exception:
        return False
    try:
        if visibility_check is None:
            ok, _reason = await check(locator, "visible")
            return bool(ok)
        outcome = _call_visibility_check(visibility_check, locator)
        if inspect.isawaitable(outcome):
            outcome = await outcome
        if isinstance(outcome, tuple):
            return bool(outcome[0])
        return bool(outcome)
    except Exception:
        return False


def _call_visibility_check(checker: Callable[..., Any], locator: Any) -> Any:
    """兼容两种注入形状：``checker(locator)`` 与 ``checker(locator, role)``。"""
    try:
        parameters = inspect.signature(checker).parameters.values()
    except (TypeError, ValueError):
        parameters = ()
    positional = 0
    variadic = False
    for parameter in parameters:
        if parameter.kind is inspect.Parameter.VAR_POSITIONAL:
            variadic = True
        elif parameter.kind in (
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
        ):
            positional += 1
    if variadic or positional >= 2:
        return checker(locator, "visible")
    return checker(locator)


__all__ = ["BlockedKind", "BlockedRules", "classify"]
