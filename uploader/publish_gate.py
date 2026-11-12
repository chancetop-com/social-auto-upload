"""客户端发布闸门：在点击「发布」前等待到指定时间。

与平台原生定时发布（``--schedule``）不同，这里的等待发生在本地：上传、
填表、封面、声明等全部准备完成后，浏览器保持打开，直到到达
``publish_not_before`` 指定的绝对时刻才继续执行发布点击，因此语义是
「不早于」。CLI 参数层会把带时区输入换算到运行机器的本地时区；
这里只负责按该时刻等待。
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Callable

#: ``None`` 表示一次 ``asyncio.sleep`` 睡到目标时间；传入秒数则分段轮询。
DEFAULT_POLL_SECONDS: float | None = None
DEFAULT_LOG_INTERVAL_SECONDS = 300.0


def _now(target: datetime, now: Callable[..., datetime]) -> datetime:
    if target.tzinfo is not None:
        # 绝对时刻比较：不依赖 target 固定下来的本地 offset。
        return now(tz=timezone.utc)
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
    poll_seconds: float | None = DEFAULT_POLL_SECONDS,
    log_interval_seconds: float = DEFAULT_LOG_INTERVAL_SECONDS,
) -> None:
    """阻塞到目标时刻；``target`` 为 ``None`` 时立即返回。

    默认一次 ``sleep`` 睡到目标时间；醒来后会再核对一次墙上时钟，时钟被
    回拨时继续补睡。只有调用方显式传入 ``poll_seconds`` 时才分段轮询。
    目标时间已过时不等待，保证 ``--not-before`` 可以安全地指向过去的时间。
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
        if poll_seconds is None:
            await sleep(remaining)
        else:
            await sleep(min(remaining, poll_seconds))

    if logger is not None:
        logger.success(f"⏰ 已到 {target.strftime('%Y-%m-%d %H:%M')}，开始点击{label}")
