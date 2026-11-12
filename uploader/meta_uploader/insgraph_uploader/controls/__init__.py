"""发布选项控件注册表：按结果键返回页面控件实现。

每个工单只填自己的 ``_register_*``：``location``（13）、``alt_text``（14）、
``comments``（11）、``ai_generated``（12）。

``humanizer`` 由发布器按 page 缓存后传进来：四个控件共用同一个实例，指针位置
与随机流保持连续；不传时各控件按 page 自建（仍全部人类化，绝无原生回退）。
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from ..options import InstagramOptionControl
from .ai_label import ai_label_control
from .alt_text import AltTextControl
from .location import LocationControl
from .toggles import SwitchControl

if TYPE_CHECKING:  # 运行时只依赖 options，避免 main <-> controls 循环导入。
    from patchright.async_api import Page

    from uploader.publish_timeout import PublishTimeoutBudget
    from utils.humanize import Humanizer


def resolve_instagram_option_controls(
    page: 'Page',
    *,
    image_count: int,
    budget: 'PublishTimeoutBudget | None' = None,
    humanizer: 'Humanizer | None' = None,
) -> dict[str, InstagramOptionControl]:
    """返回 ``{结果键: 控件}``；每个工单只填自己的 ``_register_*``。

    ``page`` 是配文页；控件入口与开关都必须限定在 ``page.get_by_role('dialog')``
    内。唯一例外是联想列表：实测它挂在页面根且没有 ARIA role，只能从输入框
    元素出发按几何 + 文本枚举（见 ``location.py``）。``image_count`` 供替代文字控件断言输入框数量（不用 DOM 猜测图片数）。
    ``budget`` 是可选的 ``PublishTimeoutBudget``，供需要收紧等待的控件使用；
    ``humanizer`` 是发布器的共享行为层实例。四个 ``_register_*`` 共用同一签名，
    便于这里一次调用全部控件；不需要图片张数的控件忽略 ``image_count``。
    """
    controls: dict[str, InstagramOptionControl] = {}
    _register_location(
        controls, page, image_count=image_count, budget=budget, humanizer=humanizer
    )
    _register_alt_text(
        controls, page, image_count=image_count, budget=budget, humanizer=humanizer
    )
    _register_comments(
        controls, page, image_count=image_count, budget=budget, humanizer=humanizer
    )
    _register_ai_generated(
        controls, page, image_count=image_count, budget=budget, humanizer=humanizer
    )
    return controls


def _register_location(
    controls, page, *, image_count, budget, humanizer
) -> None:
    """地点控件（工单 13）。"""
    controls['location'] = LocationControl(
        page, budget=budget, humanizer=humanizer
    )


def _register_alt_text(
    controls, page, *, image_count, budget, humanizer
) -> None:
    """替代文字控件（工单 14）：张数取自调用方，不猜 DOM。"""
    controls['alt_text'] = AltTextControl(
        page, image_count=image_count, budget=budget, humanizer=humanizer
    )


def _register_comments(
    controls, page, *, image_count, budget, humanizer
) -> None:
    """关闭评论控件（工单 11）：Advanced settings 内语义反转的开关。"""
    controls["comments"] = SwitchControl(
        page,
        labels=("Turn off commenting", "关闭评论"),
        panel_labels=("Advanced settings", "高级设置"),
        invert=True,
        budget=budget,
        humanizer=humanizer,
    )


def _register_ai_generated(
    controls, page, *, image_count, budget, humanizer
) -> None:
    """AI 标识控件（工单 12）：配文页直接可见、语义不反转的开关。"""
    controls["ai_generated"] = ai_label_control(
        page, budget=budget, humanizer=humanizer
    )
