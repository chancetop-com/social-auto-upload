import asyncio
import time
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

from uploader.base_video import BaseVideoUploader
from uploader.publish_timeout import PUBLISH_TIMEOUT_SECONDS, PublishTimeoutBudget
from utils.errors import PublishResultUnknownError


class _DummyUploader(BaseVideoUploader):
    publish_platform_label = "测试平台"


class PublishTimeoutBudgetTests(unittest.TestCase):
    def test_default_budget_is_fifteen_minutes(self):
        self.assertEqual(PUBLISH_TIMEOUT_SECONDS, 15 * 60)

    def test_pre_click_timeout_is_regular_failure(self):
        budget = PublishTimeoutBudget("测试平台")
        budget.deadline = time.monotonic() - 1

        with self.assertRaises(RuntimeError) as ctx:
            budget.check_pre_click()

        self.assertIn("测试平台", str(ctx.exception))
        self.assertIn("15 分钟", str(ctx.exception))
        self.assertIn("尚未点击发布", str(ctx.exception))
        self.assertNotIsInstance(ctx.exception, PublishResultUnknownError)

    def test_custom_messages_are_preserved(self):
        budget = PublishTimeoutBudget(
            "测试平台",
            pre_click_message="PRE",
            result_unknown_message="POST",
        )
        budget.deadline = time.monotonic() - 1

        self.assertEqual(str(budget.pre_click_error()), "PRE")
        self.assertEqual(str(budget.timeout_error(True)), "POST")

    def test_post_click_timeout_is_result_unknown(self):
        budget = PublishTimeoutBudget("测试平台")

        before = budget.timeout_error(False)
        after = budget.timeout_error(True)

        self.assertNotIsInstance(before, PublishResultUnknownError)
        self.assertIsInstance(after, PublishResultUnknownError)
        self.assertIn("禁止自动重发", str(after))

    def test_clamp_uses_remaining_budget(self):
        budget = PublishTimeoutBudget("测试平台", timeout_seconds=10)
        budget.deadline = time.monotonic() + 2

        self.assertLessEqual(budget.clamp_ms(60_000), 2_000)
        self.assertLessEqual(budget.clamp_seconds(60), 2)

    def test_clamp_never_returns_zero_timeout(self):
        budget = PublishTimeoutBudget("测试平台")
        with patch("uploader.publish_timeout.time.monotonic", return_value=100.0):
            budget.deadline = 100.0007
            self.assertEqual(budget.clamp_ms(60_000), 1)
            self.assertEqual(budget.clamp_seconds(60), 0.001)

    def test_uploader_budget_is_shared_across_one_run(self):
        uploader = _DummyUploader()

        started = uploader.start_publish_budget()

        self.assertIs(uploader.publish_budget, started)
        self.assertEqual(started.platform, "测试平台")

    def test_post_click_clamp_never_raises_pre_click_error(self):
        budget = PublishTimeoutBudget("测试平台")
        budget.deadline = time.monotonic() - 1

        self.assertEqual(budget.post_click_timeout_ms(60_000), 1)

    def test_clamp_raises_pre_click_error_when_exhausted(self):
        budget = PublishTimeoutBudget("测试平台")
        budget.deadline = time.monotonic() - 1

        for clamp in (budget.clamp_ms, budget.clamp_seconds):
            with self.subTest(clamp=clamp), self.assertRaises(RuntimeError) as ctx:
                clamp(60_000)
            self.assertNotIsInstance(ctx.exception, PublishResultUnknownError)

    def test_wait_until_allowed_extends_deadline(self):
        budget = PublishTimeoutBudget("测试平台")
        original = time.monotonic() + 100
        budget.deadline = original

        async def fake_wait(*_args, **_kwargs):
            await asyncio.sleep(0.02)

        with patch("uploader.publish_timeout.wait_until_publish_allowed", fake_wait):
            asyncio.run(budget.wait_until_allowed(datetime.now() + timedelta(hours=1)))

        self.assertGreater(budget.deadline, original + 0.01)


if __name__ == "__main__":
    unittest.main()
