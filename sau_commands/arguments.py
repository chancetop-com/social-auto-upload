"""CLI 共用的路径、标签和时间参数规则。"""
from __future__ import annotations
import argparse
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable
from conf import BASE_DIR
from utils.time_utils import parse_aware_iso

#: ``--schedule`` 约定为 UTC 绝对时刻，填写前换算到浏览器时区。
SCHEDULE_EXAMPLE = "YYYY-MM-DDTHH:MM:00Z"
SCHEDULE_HELP = f"Schedule time in {SCHEDULE_EXAMPLE} (UTC)"
SCHEDULE_HELP_ZH = f"定时发布时间，格式 {SCHEDULE_EXAMPLE}（UTC）"
#: ``--not-before`` 同样使用 UTC 绝对时刻，但保留秒级精度。
NOT_BEFORE_EXAMPLE = "YYYY-MM-DDTHH:MM:SSZ"

def has_interactive_terminal() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


def resolve_account_file(platform: str, account_name: str) -> Path:
    account_file = Path(BASE_DIR) / "cookies" / f"{platform}_{account_name}.json"
    account_file.parent.mkdir(exist_ok=True)
    return account_file


def parse_tags(raw_tags: str | None) -> list[str]:
    if not raw_tags:
        return []

    tags: list[str] = []
    for item in raw_tags.split(","):
        cleaned = item.strip().lstrip("#")
        if cleaned:
            tags.append(cleaned)
    return tags


def parse_image_files(raw_files: Iterable[Path]) -> list[Path]:
    return [Path(file) for file in raw_files]


def parse_utc_instant(
    value: str, *, label: str, require_minute: bool
) -> datetime:
    """解析零偏移的 UTC 绝对时刻；可按平台要求限制到分钟。"""
    if "." in value.strip():
        raise ValueError(f"{label} 不接受小数秒")
    parsed = parse_aware_iso(value, label=label)
    if parsed.utcoffset() != timedelta(0):
        raise ValueError(f"{label} 必须是 UTC 绝对时刻（零偏移）")
    if require_minute and parsed.second:
        raise ValueError(f"{label} 精确到分钟，不接受秒")
    return parsed


def parse_schedule(raw_schedule: str | None) -> datetime | int:
    if raw_schedule is None:
        return 0
    return parse_utc_instant(
        raw_schedule, label="--schedule", require_minute=True
    )


def existing_file_path(value: str) -> Path:
    path = Path(value)
    if not path.is_file():
        raise argparse.ArgumentTypeError(f"File not found: {value}")
    return path


def schedule_value(value: str):
    try:
        return parse_schedule(value)
    except (ValueError, OverflowError, OSError) as exc:
        raise argparse.ArgumentTypeError(
            f"Invalid schedule '{value}': {exc}. "
            f"Expected UTC ISO 8601: {SCHEDULE_EXAMPLE}"
        ) from exc


def not_before_value(value: str) -> datetime:
    """解析 ``--not-before``：UTC 绝对时刻，并换算到运行机器本地时区。"""
    try:
        parsed = parse_utc_instant(
            value, label="--not-before", require_minute=False
        )
    except (ValueError, OverflowError, OSError) as exc:
        raise argparse.ArgumentTypeError(
            f"Invalid --not-before '{value}': {exc}. "
            f"Expected UTC ISO 8601: {NOT_BEFORE_EXAMPLE}"
        ) from exc
    try:
        return parsed.astimezone()
    except (OverflowError, OSError):
        # 极端年份在部分时区无法本地化；等待仍按绝对时刻比较，保留 UTC。
        return parsed


def add_not_before_flag(parser: argparse.ArgumentParser) -> None:
    """为发布命令注册客户端发布闸门参数。"""
    parser.add_argument(
        "--not-before",
        type=not_before_value,
        default=None,
        metavar="TIME",
        help=(
            "All content is prepared first; click publish only at or after "
            f"the UTC absolute instant TIME (format {NOT_BEFORE_EXAMPLE}). "
            "Omit to publish immediately."
        ),
    )


def add_runtime_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--debug", action="store_true", help="Enable debug mode")
    headless_group = parser.add_mutually_exclusive_group()
    headless_group.add_argument("--headed", dest="headless", action="store_false", help="Run with browser UI")
    headless_group.add_argument("--headless", dest="headless", action="store_true", help="Run in headless mode")
    parser.set_defaults(headless=False)
