"""发布选项控件注册表：按结果键返回页面控件实现。

后续工单各加一行：``location``（13）、``alt_text``（14）、``comments``（11）、
``ai_generated``（12）。本工单只建立接缝，返回空表。
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from ..options import InstagramOptionControl
from .location import LocationControl

if TYPE_CHECKING:  # 运行时只依赖 options，避免 main <-> controls 循环导入。
    from patchright.async_api import Page


def resolve_instagram_option_controls(
    page: 'Page',
    *,
    image_count: int,
    budget: object | None = None,
) -> dict[str, InstagramOptionControl]:
    """返回 ``{结果键: 控件}``；每个工单只填自己的 ``_register_*``。

    ``page`` 是配文页；所有控件都必须把定位限定在 ``page.get_by_role('dialog')``
    内。``image_count`` 供替代文字控件断言输入框数量（不用 DOM 猜测图片数）。
    ``budget`` 是可选的 ``PublishTimeoutBudget``，供需要收紧等待的控件使用；
    不传时控件使用页面默认超时。
    """
    controls: dict[str, InstagramOptionControl] = {}
    _register_location(controls, page, image_count=image_count, budget=budget)
    _register_alt_text(controls, page, image_count=image_count, budget=budget)
    _register_comments(controls, page, image_count=image_count, budget=budget)
    _register_ai_generated(controls, page, image_count=image_count, budget=budget)
    return controls


def _register_location(controls, page, *, image_count, budget) -> None:
    """地点控件（工单 13）。"""
    controls['location'] = LocationControl(page, budget=budget)


def _register_alt_text(controls, page, *, image_count, budget) -> None:
    """替代文字控件（工单 14）。"""


def _register_comments(controls, page, *, image_count, budget) -> None:
    """关闭评论控件（工单 11）。"""


def _register_ai_generated(controls, page, *, image_count, budget) -> None:
    """AI 标识控件（工单 12）。"""
