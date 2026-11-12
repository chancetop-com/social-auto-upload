"""浏览器时区读取与墙上时间换算。"""
import unittest
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from uploader.tk_uploader.schedule import prepare_schedule
from utils.browser_time import page_timezone, to_wall_clock


class _Page:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error

    async def evaluate(self, expression):
        if self.error is not None:
            raise self.error
        return self.result


class WallClockConversionTests(unittest.TestCase):
    def test_to_wall_clock_preserves_the_instant(self):
        value = datetime(2026, 11, 12, 10, 30, tzinfo=timezone.utc)
        local = to_wall_clock(value, ZoneInfo("Asia/Shanghai"))
        self.assertIsNone(local.tzinfo)
        self.assertEqual(local, datetime(2026, 11, 12, 18, 30))
        self.assertEqual(
            local.replace(tzinfo=ZoneInfo("Asia/Shanghai")).timestamp(),
            value.timestamp(),
        )


class TiktokSchedulePreparationTests(unittest.IsolatedAsyncioTestCase):
    async def test_rejects_non_five_minute_before_reading_timezone(self):
        page = _Page(error=AssertionError("不应读取时区"))
        with self.assertRaisesRegex(ValueError, "5 分钟"):
            await prepare_schedule(
                page, datetime(2026, 11, 12, 10, 32, tzinfo=timezone.utc)
            )

    async def test_converts_to_browser_wall_clock(self):
        page = _Page("Asia/Shanghai")
        result = await prepare_schedule(
            page, datetime(2026, 11, 12, 10, 30, tzinfo=timezone.utc)
        )
        self.assertEqual(result, datetime(2026, 11, 12, 18, 30))


class PageTimezoneTests(unittest.IsolatedAsyncioTestCase):
    async def test_reads_iana_zone(self):
        self.assertEqual(await page_timezone(_Page("Asia/Shanghai")), ZoneInfo("Asia/Shanghai"))

    async def test_rejects_evaluate_error(self):
        with self.assertRaisesRegex(RuntimeError, "无法读取浏览器时区"):
            await page_timezone(_Page(error=RuntimeError("boom")))

    async def test_rejects_empty_string(self):
        with self.assertRaisesRegex(RuntimeError, "无法读取浏览器时区"):
            await page_timezone(_Page(""))

    async def test_rejects_non_string(self):
        with self.assertRaisesRegex(RuntimeError, "无法读取浏览器时区"):
            await page_timezone(_Page({"self": True}))

    async def test_rejects_unknown_zone(self):
        with self.assertRaisesRegex(RuntimeError, "无法读取浏览器时区"):
            await page_timezone(_Page("Not/AZone"))


if __name__ == "__main__":
    unittest.main()
