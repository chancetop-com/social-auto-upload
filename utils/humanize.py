# -*- coding: utf-8 -*-
"""人类化交互层（共享层，零平台知识）。

这一层只回答两件事：**怎么打字**、**怎么点**。参数表来自上游 Go 的
``humanize`` 动作库（spec §3 U5 A，单一来源，平台不得复制第二份），
平台差异只允许 ``dataclasses.replace(DEFAULT_PROFILE, ...)``。

打字（``type_text``）
    长度 ≤ ``type_horizon_chars``（1000）时逐字符派发：ASCII 走
    ``keyboard.press``（真 keydown/keyup），中文 / emoji 走
    ``keyboard.insert_text``（只有 input 事件，与上游同级）；每个字符后采样
    一次 ``Keystroke``。超过阈值整段一次 ``insert_text``，零按键、零采样，
    打一条 ``info``（``type_text→bulk insert_text, chars=NNN``）。两条路径都
    以一次 ``after_type`` 结束。**禁止**剪贴板粘贴、**禁止** ``fill()``：粘贴
    失败会把上一条剪贴板内容静默写进正文。

点击（``click``）
    ``bounding_box`` → 内缩 ``min(size*0.15, 8px)`` 的随机落点 → 三次贝塞尔
    移动（``steps = clamp(round(dist/10), 10, 40)``，控制点沿法线偏移，每步
    5–9ms）→ ``PointerSettle`` → stillOn 复核（包围盒 ±1px、落点元素仍是目标、
    ``utils.dom.check(..., "interactive")``）→ ``mouse.down`` → ``ClickHold``
    → ``mouse.up``。

不变量
    * **内部零重试**（重试只发生在 ARM 循环）；
    * 不存在没有 stillOn 的坐标点击；
    * ``mouse.down`` 之前任何异常 = 确定未派发（``ElementUnusableError``）；
    * ``mouse.down`` 及其之后任何异常 = 可能已派发：异常上带
      ``click_dispatched = "maybe"`` 标记后原样上抛。

快速路径
    ``HUMANIZE=0`` 或 ``profile.enabled=False``：文本一次 ``insert_text``、
    点击一次 ``locator.click``、零 ``sleep``。用于排障与对照。

时间上界（spec §3 U5 F，均值 136ms/字）
    标题 20 字 ≈2.7s；正文 1000 字 ≈2.3min；10 个标签 ≈10.9s（每个标签另有
    一次 ``after_type`` ≈0.65s）；点击 ≈0.4s/次；合计 ≈2.6–2.7min，仍在
    15 分钟发布预算内。
"""

from __future__ import annotations

import asyncio
import math
import os
import random
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Iterator

from loguru import logger

from utils.dom import ElementUnusableError, check, normalise_point

#: 关闭整个人类化层：``HUMANIZE=0`` 与 ``profile.enabled=False`` 等价。
HUMANIZE_ENV = "HUMANIZE"

#: ``mouse.down`` 之后失败的异常标记；值是固定字符串 ``"maybe"``。
MAYBE_DISPATCHED = "click_dispatched"
MAYBE_DISPATCHED_VALUE = "maybe"

#: 点击失败的 ``what``：共享层不认识平台文案，调用方从异常类型/原因区分。
CLICK_WHAT = "点击目标"

_log = logger


@dataclass(frozen=True)
class LogNormal:
    """截断对数正态：``clamp(exp(mu + sigma*z), min_s, max_s)``。"""

    mu: float
    sigma: float
    min_s: float
    max_s: float

    def sample(self, rng: random.Random) -> float:
        value = math.exp(self.mu + self.sigma * rng.gauss(0.0, 1.0))
        return min(max(value, self.min_s), self.max_s)


@dataclass(frozen=True)
class HumanizeProfile:
    """11 个动作 + 打字视野 + 总开关；``DEFAULT_PROFILE`` 是唯一定义。"""

    keystroke: LogNormal
    after_type: LogNormal
    after_navigate: LogNormal
    before_submit: LogNormal
    pointer_settle: LogNormal
    click_hold: LogNormal
    before_click: LogNormal
    after_click: LogNormal
    between_scroll: LogNormal
    reading: LogNormal
    after_interact: LogNormal
    type_horizon_chars: int = 1000
    enabled: bool = True


#: 上游参数表原样落地（spec §3 U5 A）。平台不得复制第二份。
DEFAULT_PROFILE = HumanizeProfile(
    keystroke=LogNormal(-2.12, 0.50, 0.030, 0.400),
    after_type=LogNormal(-0.51, 0.40, 0.200, 3.0),
    after_navigate=LogNormal(0.41, 0.45, 0.600, 6.0),
    before_submit=LogNormal(0.0, 0.40, 0.400, 4.0),
    pointer_settle=LogNormal(-1.20, 0.35, 0.200, 1.200),
    click_hold=LogNormal(-2.47, 0.33, 0.045, 0.250),
    before_click=LogNormal(-1.61, 0.45, 0.080, 1.0),
    after_click=LogNormal(-0.92, 0.35, 0.150, 2.0),
    between_scroll=LogNormal(-0.22, 0.40, 0.250, 3.0),
    reading=LogNormal(-0.36, 0.40, 0.300, 3.0),
    after_interact=LogNormal(0.88, 0.30, 2.0, 3.0),
)


def _env_disabled() -> bool:
    return os.environ.get(HUMANIZE_ENV, "").strip() == "0"


def _same_box(first: Any, second: Any, *, tolerance: float) -> bool:
    for key in ("x", "y", "width", "height"):
        try:
            delta = abs(float(first[key]) - float(second[key]))
        except (KeyError, TypeError, ValueError):
            return False
        if delta > tolerance:
            return False
    return True


def _bezier(p0: float, p1: float, p2: float, p3: float, t: float) -> float:
    rest = 1.0 - t
    return (
        rest * rest * rest * p0
        + 3.0 * rest * rest * t * p1
        + 3.0 * rest * t * t * p2
        + t * t * t * p3
    )


def _not_dispatched(reason: str) -> ElementUnusableError:
    """``mouse.down`` 之前失败：确定没有派发任何点击。"""
    return ElementUnusableError(
        what=CLICK_WHAT,
        role="interactive",
        selector="",
        reason=reason,
        publish_clicked=False,
    )


def _mark_maybe_dispatched(exc: BaseException) -> None:
    """``mouse.down`` 之后的失败：可能在页面上已经发生了点击。"""
    try:
        setattr(exc, MAYBE_DISPATCHED, MAYBE_DISPATCHED_VALUE)
    except Exception:
        pass


class Humanizer:
    """一个页面一个实例：随机流、指针位置与停顿都保持连续。"""

    def __init__(
        self,
        page: Any,
        *,
        profile: HumanizeProfile = DEFAULT_PROFILE,
        rng: random.Random | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.page = page
        self.profile = profile
        self.enabled = bool(profile.enabled) and not _env_disabled()
        self._rng = rng if rng is not None else random.Random()
        self._sleep = sleep
        self._pointer: tuple[float, float] | None = None

    # -- pauses ------------------------------------------------------------
    async def _pause(self, action: LogNormal) -> None:
        if not self.enabled:
            return
        await self._sleep(action.sample(self._rng))

    async def after_type(self) -> None:
        await self._pause(self.profile.after_type)

    async def before_submit(self) -> None:
        await self._pause(self.profile.before_submit)

    async def after_navigate(self) -> None:
        await self._pause(self.profile.after_navigate)

    async def between_scroll(self) -> None:
        await self._pause(self.profile.between_scroll)

    async def reading(self) -> None:
        await self._pause(self.profile.reading)

    async def after_interact(self) -> None:
        await self._pause(self.profile.after_interact)

    async def before_click(self) -> None:
        await self._pause(self.profile.before_click)

    async def after_click(self) -> None:
        await self._pause(self.profile.after_click)

    # -- typing ------------------------------------------------------------
    async def type_text(self, text: str) -> None:
        """逐字符（≤1000）或整段一次（>1000）写入，并以 ``after_type`` 结束。"""
        text = str(text)
        if not self.enabled:
            if text:
                await self.page.keyboard.insert_text(text)
            return

        if len(text) > self.profile.type_horizon_chars:
            await self.page.keyboard.insert_text(text)
            _log.info(f"type_text→bulk insert_text, chars={len(text)}")
            await self._pause(self.profile.after_type)
            return

        for char in text:
            await self._dispatch_char(char)
            await self._pause(self.profile.keystroke)
        await self._pause(self.profile.after_type)

    async def _dispatch_char(self, char: str) -> None:
        # 换行 / 制表符不是可打字字符，只能走具名 key；其余非 ASCII 走插入。
        if char == "\n":
            await self.page.keyboard.press("Enter")
        elif char == "\t":
            await self.page.keyboard.press("Tab")
        elif char.isascii() and char.isprintable():
            await self.page.keyboard.press(char)
        else:
            await self.page.keyboard.insert_text(char)

    async def press(self, key: str) -> None:
        """单个具名键（清理键 / Enter），按下后采样一次 ``Keystroke``。"""
        await self.page.keyboard.press(key)
        await self._pause(self.profile.keystroke)

    # -- clicking ----------------------------------------------------------
    async def click(self, locator: Any, *, point: tuple[float, float] | None = None) -> None:
        """坐标点击：移动 → 停顿 → stillOn 复核 → 按下 → 保持 → 抬起。"""
        if not self.enabled:
            # Fast path: ``locator.click`` may fail *after* the browser already
            # dispatched the event, so we cannot prove "not dispatched".
            try:
                await locator.click()
            except Exception as exc:
                _mark_maybe_dispatched(exc)
                raise
            return

        ratio = normalise_point(point)
        box = await locator.bounding_box()
        if not box:
            raise _not_dispatched("no-bounding-box")
        try:
            width = float(box["width"])
            height = float(box["height"])
        except (KeyError, TypeError, ValueError) as exc:
            raise _not_dispatched("no-bounding-box") from exc
        if width <= 0 or height <= 0:
            raise _not_dispatched("zero-box")

        target = self._inset_point(box, ratio, width, height)
        start = self._pointer if self._pointer is not None else (0.0, 0.0)
        for x, y, delay in self._path(start, target):
            await self._sleep(delay)
            await self.page.mouse.move(x, y)
        self._pointer = target

        await self._pause(self.profile.pointer_settle)

        still = await locator.bounding_box()
        if not still or not _same_box(box, still, tolerance=1.0):
            raise _not_dispatched("point-drift")
        ok, reason = await check(locator, "interactive", point=ratio)
        if not ok:
            raise _not_dispatched(reason or "still-on")

        mouse = self.page.mouse
        try:
            await mouse.down()
            await self._pause(self.profile.click_hold)
            await mouse.up()
        except Exception as exc:
            # 按下即不可回退：从这里开始的任何异常都可能是已派发。
            _mark_maybe_dispatched(exc)
            raise

    def _inset_point(
        self,
        box: Any,
        ratio: tuple[float, float],
        width: float,
        height: float,
    ) -> tuple[float, float]:
        """以比例锚点为中心，在 ``min(size*0.15, 8px)`` 内缩范围内抖动。"""
        origin_x = float(box["x"])
        origin_y = float(box["y"])
        inset_x = min(width * 0.15, 8.0)
        inset_y = min(height * 0.15, 8.0)

        anchor_x = origin_x + width * ratio[0]
        anchor_y = origin_y + height * ratio[1]

        low_x = max(origin_x + inset_x, anchor_x - inset_x)
        high_x = min(origin_x + width - inset_x, anchor_x + inset_x)
        low_y = max(origin_y + inset_y, anchor_y - inset_y)
        high_y = min(origin_y + height - inset_y, anchor_y + inset_y)

        return (
            low_x + (high_x - low_x) * self._rng.random(),
            low_y + (high_y - low_y) * self._rng.random(),
        )

    def _step_delay(self) -> float:
        """每一步 5–9ms。"""
        return (5.0 + self._rng.random() * 4.0) / 1000.0

    def _path(
        self, start: tuple[float, float], end: tuple[float, float]
    ) -> Iterator[tuple[float, float, float]]:
        dx = end[0] - start[0]
        dy = end[1] - start[1]
        distance = math.hypot(dx, dy)
        steps = int(min(40, max(10, round(distance / 10.0))))
        if distance <= 1e-9:
            yield (end[0], end[1], self._step_delay())
            return

        # 控制点沿法线偏移，两侧随机；偏移量随距离缩放。
        normal_x = -dy / distance
        normal_y = dx / distance
        side = 1.0 if self._rng.random() < 0.5 else -1.0
        bend = distance * (0.05 + 0.10 * self._rng.random()) * side
        control_1 = (
            start[0] + dx / 3.0 + normal_x * bend,
            start[1] + dy / 3.0 + normal_y * bend,
        )
        control_2 = (
            start[0] + 2.0 * dx / 3.0 + normal_x * bend,
            start[1] + 2.0 * dy / 3.0 + normal_y * bend,
        )

        for index in range(1, steps + 1):
            t = index / steps
            eased = t * t * (3.0 - 2.0 * t)
            yield (
                _bezier(start[0], control_1[0], control_2[0], end[0], eased),
                _bezier(start[1], control_1[1], control_2[1], end[1], eased),
                self._step_delay(),
            )


__all__ = [
    "CLICK_WHAT",
    "DEFAULT_PROFILE",
    "HUMANIZE_ENV",
    "HumanizeProfile",
    "Humanizer",
    "LogNormal",
    "MAYBE_DISPATCHED",
    "MAYBE_DISPATCHED_VALUE",
]
