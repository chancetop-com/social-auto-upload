"""绝对时刻与浏览器墙上时间之间的唯一换算点。"""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from utils.time_utils import require_aware

_BROWSER_TIMEZONE_JS = "Intl.DateTimeFormat().resolvedOptions().timeZone"


def to_wall_clock(value: datetime, tz: ZoneInfo) -> datetime:
    """把带偏移的绝对时刻换算成浏览器时区的墙上时间（naive）。

    ``tz`` 必须来自浏览器页面本身；naive 输入没有绝对时刻，直接报错。
    """
    value = require_aware(value)
    return value.astimezone(tz).replace(tzinfo=None)


async def page_timezone(page) -> ZoneInfo:
    """读取页面实际生效的浏览器时区；读不到直接失败，不回退到进程时区。"""
    try:
        name = await page.evaluate(_BROWSER_TIMEZONE_JS)
    except Exception as exc:
        raise RuntimeError(f"无法读取浏览器时区：{exc}") from exc
    if not isinstance(name, str) or not name.strip():
        raise RuntimeError(f"无法读取浏览器时区：页面返回 {name!r}")
    try:
        return ZoneInfo(name.strip())
    except Exception as exc:
        raise RuntimeError(f"无法读取浏览器时区：未知时区 {name!r}") from exc


async def page_wall_clock(page, value: datetime) -> datetime:
    """按页面实际生效的浏览器时区换算墙上时间。"""
    return to_wall_clock(value, await page_timezone(page))
