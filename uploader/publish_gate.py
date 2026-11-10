"""客户端发布闸门：在点击「发布」前等待到指定时间。

与平台原生定时发布（``--schedule``）不同，这里的等待发生在本地：上传、
填表、封面、声明等全部准备完成后，浏览器保持打开，直到本地墙钟时间
``>= publish_not_before`` 才继续执行发布点击，因此语义是「不早于」。
"""
from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any, Callable

DEFAULT_POLL_SECONDS = 5.0
DEFAULT_LOG_INTERVAL_SECONDS = 300.0


def _now(target: datetime, now: Callable[..., datetime]) -> datetime:
    if target.tzinfo is not None:
        return now(tz=target.tzinfo)
    return now()


def remaining_seconds(
    target: datetime,
    *,
    now: Callable[..., datetime] = datetime.now,
) -> float:
    """返回距离 ``target`` 的剩余秒数；已到达时返回 ``<= 0``。"""
    return (target - _now(target, now)).total_seconds()


def _format_remaining(seconds: float) -> str:
    total = max(0, int(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours} 小时 {minutes} 分"
    if minutes:
        return f"{minutes} 分 {secs} 秒"
    return f"{secs} 秒"


async def wait_until_publish_allowed(
    target: datetime | None,
    *,
    logger: Any = None,
    label: str = "发布",
    now: Callable[..., datetime] = datetime.now,
    sleep: Callable[[float], Any] = asyncio.sleep,
    poll_seconds: float = DEFAULT_POLL_SECONDS,
    log_interval_seconds: float = DEFAULT_LOG_INTERVAL_SECONDS,
) -> None:
    """阻塞到本地时间 ``>= target``；``target`` 为 ``None`` 时立即返回。

    等待期间分段睡眠并定期输出剩余时间，避免长时间静默。目标时间已过时
    不等待，保证 ``--not-before`` 可以安全地指向过去的时间。
    """
    if target is None:
        return
    if not isinstance(target, datetime):
        raise TypeError("publish_not_before 必须是 datetime 或 None")

    remaining = remaining_seconds(target, now=now)
    if remaining <= 0:
        return

    if logger is not None:
        logger.info(
            f"⏳ 已准备就绪，将在 {target.strftime('%Y-%m-%d %H:%M')} 之后点击{label}，"
            f"预计还需等待 {_format_remaining(remaining)}"
        )

    next_log_at = remaining - log_interval_seconds
    while True:
        remaining = remaining_seconds(target, now=now)
        if remaining <= 0:
            break
        if logger is not None and remaining <= next_log_at:
            logger.info(f"⏳ 距离{label}还有 {_format_remaining(remaining)}")
            next_log_at = remaining - log_interval_seconds
        await sleep(min(remaining, poll_seconds))

    if logger is not None:
        logger.success(f"⏰ 已到 {target.strftime('%Y-%m-%d %H:%M')}，开始点击{label}")
