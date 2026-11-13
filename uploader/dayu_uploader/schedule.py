"""大鱼号时间校验、原生日期选择，以及结果文件里的排期解析/格式化。"""
import re
from datetime import datetime, timedelta, timezone

from patchright.async_api import BrowserContext, Page, expect

from utils.browser_time import page_wall_clock
from utils.time_utils import (
    parse_aware_iso,
    require_minute_step,
    require_schedule_window,
)
from uploader.dayu_uploader.constants import (
    DAYU_CONTENT_PUBLIC, DAYU_CONTENT_SCHEDULED, DAYU_MONTH_NAMES,
    DAYU_SCHEDULE_MAX_DAYS, DAYU_SCHEDULE_MIN_HOURS,
    DAYU_SCHEDULE_STEP_MINUTES,
)


def target_from_result(schedule: str | None) -> datetime | None:
    """解析结果文件里的排期；未提供时返回 ``None``。"""
    if not schedule:
        return None
    return parse_aware_iso(schedule, label="结果文件中的定时时间")


def verify_saved_schedule(
    epoch_ms: float, target: datetime | None, *, missing_message: str
) -> datetime:
    """核对平台保存的毫秒时间戳；缺失或与请求不一致时立即失败。"""
    if (
        isinstance(epoch_ms, bool)
        or not isinstance(epoch_ms, (int, float))
        or epoch_ms <= 0
    ):
        raise RuntimeError(missing_message)
    actual = datetime.fromtimestamp(epoch_ms / 1000, timezone.utc)
    if target is not None and actual != target:
        raise RuntimeError(
            f"定时时间不一致: 预期={target.isoformat()}，"
            f"实际={actual.isoformat()}"
        )
    return actual


def format_saved_schedule(actual: datetime, target: datetime | None) -> str:
    """按请求的 offset 输出排期；未提供时输出 UTC。"""
    if target is None:
        return actual.isoformat()
    return actual.astimezone(target.tzinfo).isoformat()


def initial_status(record: dict) -> str:
    """平台状态对应的初始结果状态。"""
    return "published" if record["status"] == DAYU_CONTENT_PUBLIC else "submitted"


def apply_schedule_result(
    result: dict,
    record: dict,
    target: datetime | None,
    saved_actual: datetime | None,
) -> None:
    """把已校验的排期写回结果；立即发布且非定时状态时保持原样。"""
    if target is None and record["status"] != DAYU_CONTENT_SCHEDULED:
        return
    if saved_actual is None:
        raise RuntimeError("缺少已校验的定时时间，拒绝写回结果")
    result.update(
        schedule=format_saved_schedule(saved_actual, target),
        schedule_verified=True,
        status=(
            initial_status(record)
            if record["status"] == DAYU_CONTENT_PUBLIC
            else "scheduled"
        ),
    )


async def read_dayu_schedule(context: BrowserContext, origin_id: str, expected: str | None) -> dict:
    """读原稿的服务端保存值；查询旧结果时不再检查未来范围，也不改写平台时间。"""
    response = await context.request.get("https://mp.dayu.com/dashboard/getDraftInfo",
                                         params={"draft_id": origin_id}, timeout=30000)
    if not response.ok:
        raise RuntimeError(f"查询原作品定时设置失败: HTTP {response.status}")
    data = await response.json()
    if data.get("draft_id") != origin_id:
        raise RuntimeError("定时查询未返回本次原稿，可能登录失效或接口变化")
    enabled = data.get("is_timed_release")
    if expected is None:
        if enabled is not False:
            raise RuntimeError("平台未确认立即发布设置，拒绝确认发表")
        return {}
    target = parse_aware_iso(expected, label="结果文件中的定时时间")
    epoch = data.get("time_for_release")
    # 保存接口实测将控件隐藏秒数归整到分钟；核对精确 epoch，不能容忍平台错排一分钟。
    if enabled is not True:
        raise RuntimeError("平台未保存本次定时发布设置")
    actual = verify_saved_schedule(
        epoch, target, missing_message="平台未保存本次定时发布设置"
    )
    return {
        "schedule": format_saved_schedule(actual, target),
        "schedule_verified": True,
    }


def validate_dayu_schedule(value: datetime | None, now: datetime | None = None) -> datetime | None:
    """按绝对时刻校验，不换算时区，也不自动取整。"""
    if value is None:
        return None
    if not isinstance(value, datetime):
        raise ValueError("大鱼号定时时间必须为 datetime；CLI 使用 UTC 零偏移的 ISO 8601（…Z）")
    value = require_minute_step(
        value, DAYU_SCHEDULE_STEP_MINUTES, label="大鱼号定时"
    )
    window_message = (
        f"大鱼号定时必须在当前时刻的 {DAYU_SCHEDULE_MIN_HOURS} 小时后至 "
        f"{DAYU_SCHEDULE_MAX_DAYS} 天内"
    )
    return require_schedule_window(
        value,
        min_lead=timedelta(hours=DAYU_SCHEDULE_MIN_HOURS),
        max_lead=timedelta(days=DAYU_SCHEDULE_MAX_DAYS),
        label="大鱼号定时时间",
        now=now,
        too_soon=window_message,
        too_far=window_message,
    )


async def fill_dayu_schedule(page: Page, value: datetime | None) -> None:
    """使用页面实际提供的日、时、分选项；立即发布时也读回未启用状态。"""
    target = validate_dayu_schedule(value)
    wall_clock = (
        await page_wall_clock(page, target) if target is not None else None
    )
    # 正文普通布局与全屏布局各有一份设置；可见 radio 容器配合直接文本前缀排除隐藏副本和其他选项。
    option = page.locator(".article-write_radio:visible").filter(has_text=re.compile(r"^\s*定时发布"))
    await expect(option).to_have_count(1)
    toggle = option.locator(":scope > .w-radio")
    if "w-radio_checked" in (await toggle.get_attribute("class") or ""):
        await toggle.click()
    await expect(toggle).not_to_have_class(re.compile(r"\bw-radio_checked\b"))
    # 此输入只显示选中值，点击入口是其同组件的 mask；直接点击 input 会被 mask 拦截。
    widget = page.locator(".widgets-datepicker-m:visible")
    if target is None:
        await expect(widget).to_have_count(0)
        return
    await toggle.click()
    await expect(toggle).to_have_class(re.compile(r"\bw-radio_checked\b"))
    await expect(widget).to_have_count(1)
    await widget.locator(".widgets-datepicker-m_mask").click()
    # 两份布局各自创建日历实例；只操作打开的日历，视图类区分日期、小时和分钟。
    picker = page.locator(".datetimepicker:visible")
    await expect(picker).to_have_count(1)
    days = picker.locator(".datetimepicker-days")
    heading = days.locator("th.switch")
    desired_month = f"{DAYU_MONTH_NAMES[wall_clock.month - 1]} {wall_clock.year}"
    if (await heading.inner_text()).strip() != desired_month:
        # 七天范围最多跨到下个月，下一月按钮在此范围可用；不按未知月份循环点击。
        await days.locator("th.next").click()
    await expect(heading).to_have_text(desired_month)
    day = days.locator("td.day:not(.old):not(.new)").filter(has_text=re.compile(f"^{wall_clock.day}$"))
    await expect(day).not_to_have_class(re.compile(r"\bdisabled\b"))
    await day.click()
    hour = picker.locator(".datetimepicker-hours .hour").filter(has_text=re.compile(f"^{wall_clock.hour}:00$"))
    await expect(hour).not_to_have_class(re.compile(r"\bdisabled\b"))
    await hour.click()
    # 原生日历的小时不补零（1:05），输入框则补零（01:05）；不能共用显示格式定位分钟。
    minute = picker.locator(".datetimepicker-minutes .minute").filter(has_text=re.compile(f"^{wall_clock.hour}:{wall_clock.minute:02d}$"))
    await expect(minute).not_to_have_class(re.compile(r"\bdisabled\b"))
    await minute.click()
    await expect(picker).to_have_count(0)
    await expect(widget.locator("input")).to_have_value(wall_clock.strftime("%Y年%m月%d日 %H:%M"))
