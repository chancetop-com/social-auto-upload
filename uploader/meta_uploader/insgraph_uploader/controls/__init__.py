"""发布选项控件注册表：按结果键返回页面控件实现。

后续工单各加一行：``location``（13）、``alt_text``（14）、``comments``（11）、
``ai_generated``（12）。本工单只建立接缝，返回空表。
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from ..options import InstagramOptionControl

if TYPE_CHECKING:  # 运行时只依赖 options，避免 main <-> controls 循环导入。
    from patchright.async_api import Page


def resolve_instagram_option_controls(
    page: 'Page',
    *,
    image_count: int,
    budget: object | None = None,
) -> dict[str, InstagramOptionControl]:
    """返回 ``{结果键: 控件}``；当前没有任何选项控件。

    ``page`` 是配文页；所有控件都必须把定位限定在 ``page.get_by_role('dialog')``
    内。``image_count`` 供替代文字控件断言输入框数量（不用 DOM 猜测图片数）。
    ``budget`` 是可选的 ``PublishTimeoutBudget``，供需要收紧等待的控件使用；
    不传时控件使用页面默认超时。
    """
    return {}
