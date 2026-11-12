"""TikTok 定时输入的准备步骤。"""
from __future__ import annotations

from datetime import datetime

from utils.browser_time import page_wall_clock
from utils.time_utils import require_minute_step


async def prepare_schedule(page, value: datetime) -> datetime:
    """先校验 5 分钟档，再换算到浏览器墙上时间。"""
    return await page_wall_clock(
        page, require_minute_step(value, 5, label="TikTok 定时")
    )
