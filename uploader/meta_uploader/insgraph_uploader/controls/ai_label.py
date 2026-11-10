"""AI 生成标识控件（工单 12）：配文页 ``Add AI label`` 开关。

DOM 语义与业务语义一致：``aria-checked=true`` 即“已声明为 AI 生成”，因此直接
复用 ``SwitchControl`` 且不反转。这里保留一个薄封装，是为了让控件注册表保持
“一项一个控件”的形态，并把该选项的可见文案固定在选项自身旁边。
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from .toggles import SwitchControl

if TYPE_CHECKING:  # 仅用于类型标注，纯逻辑测试不构造浏览器类型。
    from patchright.async_api import Page

# 英文优先、中文回退；与 spec §4.3.4 的回退顺序一致。
AI_LABEL_TEXTS = ("Add AI label", "AI label", "AI 标签", "添加 AI 标签")


class AiLabelControl(SwitchControl):
    """``Add AI label`` 开关：checked = 请求的 ``ai_generated`` 值。

    没有折叠面板（该开关在配文页直接可见）；``budget`` 用于把点击后回读的
    等待收紧到剩余发布预算。
    """

    def __init__(self, page: 'Page', *, budget: object | None = None) -> None:
        super().__init__(
            page,
            labels=AI_LABEL_TEXTS,
            panel=None,
            invert=False,
            budget=budget,
        )
