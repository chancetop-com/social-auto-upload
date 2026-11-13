"""时区感知时间的共用校验。"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone


#: 只接受扩展格式，避免 Python 3.10 与 3.11 对紧凑/周日期语法的差异。
_ISO_AWARE_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}"
    r"(?::\d{2}(?:\.\d{1,6})?)?"
    r"(?:[Zz]|[+-]\d{2}:?\d{2}|[+-]\d{2})$"
)


def parse_aware_iso(text: str, *, label: str = "时间") -> datetime:
    """解析带时区偏移的扩展格式 ISO 8601 绝对时刻；``Z`` 视为 UTC。"""
    value = text.strip()
    if not _ISO_AWARE_RE.fullmatch(value):
        raise ValueError(
            "ISO 8601 时间必须使用 YYYY-MM-DDTHH:MM[:SS][.ffffff] 加偏移后缀"
        )
    if value.endswith(("Z", "z")):
        value = value[:-1] + "+00:00"
    # Python 3.10 的 fromisoformat 不接受 ±HHMM / ±HH 偏移。
    value = re.sub(r"([+-]\d{2})(\d{2})$", r"\1:\2", value)
    value = re.sub(r"([+-]\d{2})$", r"\1:00", value)
    # Python 3.10 只接受 3 或 6 位小数秒；统一补到 6 位。
    value = re.sub(
        r"\.(\d{1,6})(?=[+-]|$)",
        lambda match: "." + (match.group(1) + "000000")[:6],
        value,
    )
    return require_aware(datetime.fromisoformat(value), label=label)


def require_aware(value: datetime, *, label: str = "定时发布时间") -> datetime:
    """确认时刻带时区；naive 输入没有绝对时刻，直接报错。"""
    if value.tzinfo is None:
        raise ValueError(f"{label}必须包含时区偏移")
    return value


def require_aware_now(now: datetime | None = None) -> datetime:
    """返回带时区的当前时刻；显式传入的时钟也必须带时区。"""
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError("校验当前时间必须包含时区")
    return current


def require_minute_step(
    value: datetime, step_minutes: int, *, label: str
) -> datetime:
    """要求秒/微秒为零且分钟是该步长的倍数。"""
    value = require_aware(value, label=label)
    if value.second or value.microsecond or value.minute % step_minutes:
        raise ValueError(
            f"{label}按 {step_minutes} 分钟一档，"
            f"请提供精确到 {step_minutes} 分钟的时间"
        )
    return value


def require_schedule_window(
    value: datetime,
    *,
    min_lead: timedelta,
    max_lead: timedelta | None,
    label: str,
    now: datetime | None = None,
    min_inclusive: bool = True,
    too_soon: str,
    too_far: str | None = None,
) -> datetime:
    """按绝对时刻校验平台允许的发布时间窗口。"""
    if (max_lead is None) != (too_far is None):
        raise ValueError("max_lead 与 too_far 必须同时提供")
    value = require_aware(value, label=label)
    current = require_aware_now(now)
    lower = current + min_lead
    too_early = value < lower if min_inclusive else value <= lower
    if too_early:
        raise ValueError(too_soon)
    if max_lead is not None and value > current + max_lead:
        raise ValueError(too_far)
    return value
