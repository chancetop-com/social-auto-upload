"""知乎文章和视频的定时设置。"""
from datetime import datetime, timedelta
import re

from patchright.async_api import Page, expect

from utils.browser_time import page_wall_clock
from utils.humanize import Humanizer
from utils.time_utils import require_schedule_window
from uploader.zhihu_uploader.constants import (
    ZHIHU_SCHEDULE_MAX_HOURS, ZHIHU_SCHEDULE_MINUTES,
)


def validate_zhihu_schedule(value: datetime | None, now: datetime | None = None) -> datetime | None:
    """按绝对时刻校验页面支持的范围，不换算时区。"""
    if value is None:
        return None
    if not isinstance(value, datetime):
        raise ValueError("知乎定时时间必须为 datetime；CLI 使用带时区的 ISO 8601")
    if value.second or value.microsecond:
        raise ValueError("知乎定时精确到分钟，不接受秒或微秒")
    window_message = (
        f"知乎定时需在当前时刻 {ZHIHU_SCHEDULE_MINUTES} 分钟后至 "
        f"{ZHIHU_SCHEDULE_MAX_HOURS} 小时内"
    )
    return require_schedule_window(
        value,
        min_lead=timedelta(minutes=ZHIHU_SCHEDULE_MINUTES),
        max_lead=timedelta(hours=ZHIHU_SCHEDULE_MAX_HOURS),
        label="知乎定时时间",
        now=now,
        too_soon=window_message,
        too_far=window_message,
    )


async def fill_zhihu_article_schedule(
    page: Page, value: datetime | None, humanizer: Humanizer
) -> None:
    """通过文章发布面板的日期、小时、分钟选择器填写并读回排期。"""
    target = validate_zhihu_schedule(value)
    if target is None:
        return
    wall_clock = await page_wall_clock(page, target)

    # 文章表单将“定时发布”作为单独开关；点击后弹出已观察到的计划时间面板。
    await humanizer.click(page.get_by_text("定时发布", exact=True))
    panel_label = page.get_by_text("开启定时发布", exact=True)
    await expect(panel_label).to_be_visible()
    picker = page.locator(".DateTimePicker")
    await expect(picker).to_have_count(1)
    date_button = page.locator(".DatePicker-Button")
    await expect(date_button).to_have_count(1)
    shown_date = await date_button.inner_text()
    if shown_date != wall_clock.strftime("%Y-%m-%d"):
        await humanizer.click(date_button)
        calendar = page.locator(".Calendar")
        await expect(calendar).to_be_visible()
        shown_month = (await calendar.locator(".Calendar-topToolDate").inner_text()).strip()
        wanted_month = f"{wall_clock.year} 年 {wall_clock.month} 月"
        if shown_month != wanted_month:
            # 48 小时范围最多只跨到相邻月份；按钮职责 class 来自页面日历实际 DOM。
            await humanizer.click(calendar.locator(".Calendar-topToolButton--nextMonth"))
        await expect(calendar.locator(".Calendar-topToolDate")).to_have_text(wanted_month)
        day = calendar.locator("td.Calendar-day:not(.is-disabled):not(.is-not-this-month)").filter(
            has_text=re.compile(rf"^{wall_clock.day}$"),
        )
        await expect(day).to_have_count(1)
        await humanizer.click(day)
        await expect(date_button).to_have_text(wall_clock.strftime("%Y-%m-%d"))

    # 页面将小时与分钟分成两个同构下拉；DOM 顺序已由实际弹层验证。
    time_selects = picker.locator(".Select-button")
    await expect(time_selects).to_have_count(2)
    await humanizer.click(time_selects.nth(0))
    hour = page.get_by_role("option", name=f"{wall_clock.hour:02d}", exact=True)
    await expect(hour).to_have_count(1)
    if not await hour.is_enabled():
        raise RuntimeError("知乎定时小时选项当前不可选，请检查时间范围")
    await humanizer.click(hour)
    await humanizer.click(time_selects.nth(1))
    minute = page.get_by_role("option", name=f"{wall_clock.minute:02d}", exact=True)
    await expect(minute).to_have_count(1)
    if not await minute.is_enabled():
        raise RuntimeError("知乎定时分钟选项当前不可选，请检查时间范围")
    await humanizer.click(minute)
    await expect(time_selects.nth(0)).to_have_text(f"{wall_clock.hour:02d}")
    await expect(time_selects.nth(1)).to_have_text(f"{wall_clock.minute:02d}")
    confirm = page.get_by_role("button", name="确认", exact=True)
    await expect(confirm).to_be_enabled()
    await humanizer.click(confirm)
    await expect(panel_label).to_have_count(0)


async def fill_zhihu_video_schedule(
    page: Page, value: datetime | None, humanizer: Humanizer
) -> None:
    """通过视频表单自己的定时区启用并读回日期与时间。"""
    target = validate_zhihu_schedule(value)
    if target is None:
        return
    wall_clock = await page_wall_clock(page, target)
    schedule = page.locator(".VideoUploadForm-scheduledPublish")
    await expect(schedule).to_have_count(1)
    # 视频页脚本将该组件挂在 VideoUploadForm-scheduledPublish 行内。
    toggle = schedule.locator('input[type="checkbox"]')
    await expect(toggle).to_have_count(1)
    # 先读状态再点：已启用时重复点击会关闭定时发布。
    if not await toggle.is_checked():
        await humanizer.click(toggle)
    picker = schedule.locator(".DateTimePicker")
    await expect(picker).to_be_visible()
    date_button = picker.locator(".DatePicker-Button")
    await expect(date_button).to_have_count(1)
    shown_date = await date_button.inner_text()
    if shown_date != wall_clock.strftime("%Y-%m-%d"):
        await humanizer.click(date_button)
        calendar = page.locator(".Calendar")
        await expect(calendar).to_be_visible()
        shown_month = (await calendar.locator(".Calendar-topToolDate").inner_text()).strip()
        wanted_month = f"{wall_clock.year} 年 {wall_clock.month} 月"
        if shown_month != wanted_month:
            await humanizer.click(calendar.locator(".Calendar-topToolButton--nextMonth"))
        await expect(calendar.locator(".Calendar-topToolDate")).to_have_text(wanted_month)
        day = calendar.locator("td.Calendar-day:not(.is-disabled):not(.is-not-this-month)").filter(
            has_text=re.compile(rf"^{wall_clock.day}$"),
        )
        await expect(day).to_have_count(1)
        await humanizer.click(day)
        await expect(date_button).to_have_text(wall_clock.strftime("%Y-%m-%d"))
    time_selects = picker.locator(".Select-button")
    await expect(time_selects).to_have_count(2)
    await humanizer.click(time_selects.nth(0))
    hour = page.get_by_role("option", name=f"{wall_clock.hour:02d}", exact=True)
    await expect(hour).to_have_count(1)
    if not await hour.is_enabled():
        raise RuntimeError("知乎定时小时选项当前不可选，请检查时间范围")
    await humanizer.click(hour)
    await humanizer.click(time_selects.nth(1))
    minute = page.get_by_role("option", name=f"{wall_clock.minute:02d}", exact=True)
    await expect(minute).to_have_count(1)
    if not await minute.is_enabled():
        raise RuntimeError("知乎定时分钟选项当前不可选，请检查时间范围")
    await humanizer.click(minute)
    await expect(time_selects.nth(0)).to_have_text(f"{wall_clock.hour:02d}")
    await expect(time_selects.nth(1)).to_have_text(f"{wall_clock.minute:02d}")
