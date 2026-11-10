"""跨平台发布超时预算，语义与 TikTok 对齐。

整条上传/发布流程共用 15 分钟总预算：打开发布页、上传素材、填写元数据、
设置选项、点击发布以及等待平台确认都属于同一 deadline。

- 点击发布前超时：确定没有发布，按普通失败处理（CLI 退出 1）；
- 点击发布后超时：结果未知，抛出 ``PublishResultUnknownError``（退出 9），
  调用方不得自动重发。
"""
from __future__ import annotations

import time
from datetime import datetime
from typing import Any

from uploader.publish_gate import wait_until_publish_allowed
from utils.errors import PublishResultUnknownError

PUBLISH_TIMEOUT_SECONDS = 15 * 60


class PublishTimeoutBudget:
    """一次上传/发布流程的共享 deadline。"""

    def __init__(
        self,
        platform: str,
        *,
        timeout_seconds: float = PUBLISH_TIMEOUT_SECONDS,
        pre_click_message: str | None = None,
        result_unknown_message: str | None = None,
    ) -> None:
        self.platform = platform
        self.timeout_seconds = timeout_seconds
        self.pre_click_message = pre_click_message
        self.result_unknown_message = result_unknown_message
        self.deadline = time.monotonic() + timeout_seconds

    def remaining_seconds(self) -> float:
        """返回距离 deadline 的剩余秒数；已到达时返回 ``<= 0``。"""
        return self.deadline - time.monotonic()

    def pre_click_error(self) -> RuntimeError:
        if self.pre_click_message is not None:
            return RuntimeError(self.pre_click_message)
        minutes = max(1, int(self.timeout_seconds // 60))
        return RuntimeError(
            f"{self.platform}发布超时（{minutes} 分钟）：尚未点击发布，"
            "未发布任何内容。"
        )

    def check_pre_click(self) -> None:
        """在「尚未点击发布」的阶段检查总预算。"""
        if self.remaining_seconds() <= 0:
            raise self.pre_click_error()

    def clamp_ms(self, default_ms: int) -> int:
        """把本次等待收紧到剩余预算；预算耗尽时按点击前超时报错。"""
        remaining = self.remaining_seconds()
        if remaining <= 0:
            raise self.pre_click_error()
        remaining_ms = max(1, int(remaining * 1000))
        return min(default_ms, remaining_ms)

    def clamp_seconds(self, default_seconds: float) -> float:
        """``clamp_ms`` 的秒版本。"""
        remaining = self.remaining_seconds()
        if remaining <= 0:
            raise self.pre_click_error()
        return min(default_seconds, max(0.001, remaining))

    def post_click_timeout_ms(self, default_ms: int) -> int:
        """点击发布后的等待：预算耗尽时返回极小值，由调用方映射为结果未知。"""
        remaining_ms = max(1, int(self.remaining_seconds() * 1000))
        return min(default_ms, remaining_ms)

    def timeout_error(self, publish_clicked: bool) -> Exception:
        """点击发布前超时按失败处理，点击后超时按结果未知处理。"""
        if not publish_clicked:
            return self.pre_click_error()
        if self.result_unknown_message is not None:
            return PublishResultUnknownError(self.result_unknown_message)
        return PublishResultUnknownError(
            f"{self.platform}发布结果未知：发布点击已发出，但未确认发布成功；"
            "帖子可能已经发布。\n"
            "禁止自动重发。请先到平台后台按标题与发布时间核对；"
            "已存在则不要重发，不存在才可人工重试。"
        )

    async def wait_until_allowed(
        self,
        target: datetime | None,
        *,
        logger: Any = None,
        label: str | None = None,
    ) -> None:
        """等待 ``--not-before``，并把这部分主动等待从预算中顺延。"""
        started = time.monotonic()
        await wait_until_publish_allowed(
            target,
            logger=logger,
            label=label or f"{self.platform}发布",
        )
        self.deadline += time.monotonic() - started
