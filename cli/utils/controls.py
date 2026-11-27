# -*- coding: utf-8 -*-
"""开关状态读取（共享层，零平台知识）。

读取顺序固定为 ``aria-checked`` → ``is_checked()`` → ``None``。``None`` 是
「读不出来」的显式信号（ticket 39/40 的回读契约），调用方**不得**把它折叠成
``False``：读不出来和「关着」是两件事。
"""

from __future__ import annotations


async def read_switch_state(locator) -> bool | None:
    """返回开关的布尔状态；两种探测都失败时返回 ``None``。"""
    try:
        raw = await locator.get_attribute("aria-checked")
    except Exception:
        raw = None
    if raw is not None:
        normalised = str(raw).strip().lower()
        if normalised == "true":
            return True
        if normalised == "false":
            return False

    checker = getattr(locator, "is_checked", None)
    if checker is None:
        return None
    try:
        return bool(await checker())
    except Exception:
        return None


__all__ = ["read_switch_state"]
