# -*- coding: utf-8 -*-
"""帖子地点：名称归一化、候选选择、结果与失败文案（ticket 18）。

两个上传器观察到的控件相同：

* 入口 ``.address-card-wrapper .address-card-select``；
* 候选行 ``.option-item``，名称 ``.option-name``、地址 ``.option-subname``；
* 收起后的控件 ``.address-card-select .d-select-description`` 只显示名称。

匹配契约（issue 09）：比较候选**完整名称**，去掉首尾空白、合并连续空白、
忽略大小写；按页面顺序取第一个同名候选。地址只用于记录所点行，不参与匹配。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

#: 页面明确写出这些限制时才报告「账号不可用」。只看地点控件附近，不扫全页。
ELIGIBILITY_PHRASES: tuple[str, ...] = (
    "当前账号暂不支持添加地点",
    "暂不支持添加地点",
    "无法添加地点",
    "地点功能暂不可用",
    "没有添加地点的权限",
    "账号不可用",
)


def normalise_location_name(value: Any) -> str:
    """Trim, collapse whitespace and casefold; ``None`` becomes ``""``."""
    if value is None:
        return ""
    return " ".join(str(value).split()).casefold()


@dataclass(frozen=True)
class LocationRow:
    """One candidate row as read from the page (name/address only)."""

    name: str
    address: str

    @classmethod
    def from_mapping(cls, row: Mapping[str, Any]) -> "LocationRow":
        return cls(
            name=str(row.get("name") or "").strip(),
            address=str(row.get("address") or "").strip(),
        )


@dataclass(frozen=True)
class LocationReport:
    """The observable result of one post-location selection."""

    requested: str
    clicked_name: str
    address: str | None
    final_name: str
    status: str = "set"

    def as_dict(self) -> dict[str, Any]:
        return {
            "requested": self.requested,
            "clicked_name": self.clicked_name,
            "address": self.address,
            "final_name": self.final_name,
            "status": self.status,
        }

    def summary(self) -> str:
        return (
            f"帖子地点：请求={self.requested}，"
            f"所点行={format_clicked_row(self.clicked_name, self.address)}，"
            f"终值={self.final_name}，结果=已设置"
        )


def pick_location_row(
    rows: Sequence[Mapping[str, Any] | LocationRow], requested: str
) -> tuple[int, LocationRow] | None:
    """Return the first same-name row in page order, or ``None``."""
    wanted = normalise_location_name(requested)
    for index, raw in enumerate(rows):
        row = raw if isinstance(raw, LocationRow) else LocationRow.from_mapping(raw)
        if normalise_location_name(row.name) == wanted:
            return index, row
    return None


def format_clicked_row(name: str, address: str | None = None) -> str:
    shown = (name or "").strip()
    address = (address or "").strip()
    return f"{shown} · {address}" if address else shown


def match_eligibility_notice(text: str | None) -> str | None:
    """Return the explicit eligibility phrase found in *text*, if any."""
    if not text:
        return None
    folded = " ".join(str(text).split()).casefold()
    for phrase in ELIGIBILITY_PHRASES:
        if phrase.casefold() in folded:
            return phrase
    return None


def no_match_reason(
    rows: Sequence[LocationRow], requested: str, *, limit: int = 3
) -> str:
    """Distinct reason for an empty list versus approximate-only suggestions."""
    if not rows:
        return "无同名候选（候选列表为空）"
    names = [row.name for row in rows if row.name][:limit]
    shown = "、".join(names) if names else "（名称不可读）"
    suffix = "…" if len(rows) > limit else ""
    return f"无同名候选（仅有近似候选：{shown}{suffix}）"


def location_failure_message(
    *,
    requested: str,
    clicked_name: str | None = None,
    address: str | None = None,
    final_name: str | None = None,
    reason: str,
) -> str:
    clicked = (
        "未点选"
        if clicked_name is None
        else format_clicked_row(clicked_name, address)
    )
    if final_name is None:
        final = "未读到"
    elif not final_name:
        final = "（空）"
    else:
        final = final_name
    return (
        f"帖子地点设置失败：请求={requested}，所点行={clicked}，"
        f"终值={final}，原因={reason}；尚未点击发布。"
    )


class LocationVerificationError(RuntimeError):
    """Pre-publish location failure carrying the same fields as the CLI line."""

    def __init__(
        self,
        *,
        requested: str,
        reason: str,
        clicked_name: str | None = None,
        address: str | None = None,
        final_name: str | None = None,
    ) -> None:
        self.requested = requested
        self.reason = reason
        self.clicked_name = clicked_name
        self.address = address
        self.final_name = final_name
        super().__init__(
            location_failure_message(
                requested=requested,
                clicked_name=clicked_name,
                address=address,
                final_name=final_name,
                reason=reason,
            )
        )
