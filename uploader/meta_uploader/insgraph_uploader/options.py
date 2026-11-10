"""Instagram 发布选项：三态数据类、状态常量与零浏览器的纯逻辑。

本模块不导入浏览器、不读页面、不构造 uploader：CLI 静态校验与上传器的
选项记录/状态映射都复用同一份实现。``None`` 始终表示“不动页面默认”，
禁止在传递过程中压缩成二值。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from utils.errors import UsageError

# 结果文件中的 status，只允许这 5 个。
NOT_REQUESTED = "not_requested"
SET = "set"
DEFAULT_OFF = "default_off"
UNSUPPORTED = "unsupported"
MISMATCH = "mismatch"

# 无法应用时的归因，仅在需要时写入 reason。
ENTRY_MISSING = "entry_missing"
ACCOUNT_INELIGIBLE = "account_ineligible"

# 控件 resolve() 的三态结果。
PRESENT = "present"
MISSING = "missing"
INELIGIBLE = "ineligible"

# 结果文件字段顺序。
OPTION_KEYS = ("location", "alt_text", "comments", "ai_generated")
# 应用顺序（spec §4.2）：先处理会开关模态框的项，最后展开高级设置。
APPLY_ORDER = ("alt_text", "location", "ai_generated", "comments")

MAX_CAPTION_LENGTH = 2200
MAX_ALT_TEXT_LENGTH = 1000

# 结果键 -> InstagramPublishOptions 字段名。
_OPTION_FIELDS = {
    "location": "location",
    "alt_text": "alt_texts",
    "comments": "comments",
    "ai_generated": "ai_generated",
}
_TOGGLE_KEYS = ("comments", "ai_generated")


@dataclass(frozen=True, slots=True)
class InstagramPublishOptions:
    """调用方请求的发布选项；``None`` 表示保持页面默认。"""

    location: str | None = None
    alt_texts: tuple[str, ...] | None = None
    comments: bool | None = None          # False = 关闭评论
    ai_generated: bool | None = None


class InstagramOptionControl(Protocol):
    """页面控件的最小异步接缝；测试用内存实现注入。"""

    async def resolve(self) -> str:
        """返回 "present" / "missing" / "ineligible"。"""
        ...

    async def read(self) -> object:
        """返回语义值（comments 返回 comments_enabled，而非原始 aria-checked）。"""
        ...

    async def set(self, requested: object) -> None:
        ...


class OptionMismatchError(RuntimeError):
    """控件已能判断请求无法表达；``applied`` 是失败时页面实际可读到的值。

    与普通异常不同：它只代表“这一项没生效”，管线记录 ``mismatch`` 后继续处理
    后续选项，并把错误文案并入最终的聚合错误（例如地点无精确匹配时的候选列表）。
    """

    def __init__(self, message: str, *, applied: object = None) -> None:
        super().__init__(message)
        self.applied = applied


def normalize_text(text: str) -> str:
    """空白折叠 + casefold，供地点与替代文字比较。"""
    return " ".join(text.split()).casefold()


def location_matches(requested: object, applied: object) -> bool:
    """规范化后精确相等；回读缺失或非字符串一律不匹配。"""
    if not isinstance(requested, str) or not isinstance(applied, str):
        return False
    return normalize_text(requested) == normalize_text(applied)


def alt_texts_match(requested: object, applied: object) -> bool:
    """长度相等且逐项规范化相等；回读缺失或数量不符不匹配。"""
    if applied is None or isinstance(applied, (str, bytes)):
        return False
    try:
        requested_items = list(requested)  # type: ignore[arg-type]
        applied_items = list(applied)      # type: ignore[arg-type]
    except TypeError:
        return False
    if len(requested_items) != len(applied_items):
        return False
    return all(
        isinstance(expected, str)
        and isinstance(actual, str)
        and normalize_text(expected) == normalize_text(actual)
        for expected, actual in zip(requested_items, applied_items)
    )


def _value_matches(requested: object, applied: object) -> bool:
    """按请求类型分派：地点是字符串，替代文字是有序序列。"""
    if isinstance(requested, str):
        return location_matches(requested, applied)
    return alt_texts_match(requested, applied)


def option_kind(key: str) -> str:
    """``toggle``（布尔开关）或 ``value``（文本/有序列表）。"""
    return "toggle" if key in _TOGGLE_KEYS else "value"


def requested_option(
    options: InstagramPublishOptions | None, key: str
) -> object:
    """读取某选项的请求值；``None`` 表示未请求，三态不压缩。"""
    if options is None:
        return None
    value = getattr(options, _OPTION_FIELDS[key])
    if key == "alt_text" and value is not None:
        return list(value)
    return value


def empty_option_record(options: InstagramPublishOptions | None) -> dict:
    """生成四项 ``not_requested`` 骨架，requested 保留三态原值。"""
    record: dict = {}
    for key in OPTION_KEYS:
        record[key] = {
            "requested": requested_option(options, key),
            "applied": None,
            "status": NOT_REQUESTED,
        }
    return record


def _unavailable_status(requested: object, kind: str, reason: str) -> tuple[str, str | None]:
    """入口缺失 / 账号不可用：请求 off 视为已满足，其余按不支持处理。"""
    if kind == "toggle" and requested is False:
        return DEFAULT_OFF, reason
    return UNSUPPORTED, reason


def option_status(
    requested: object,
    applied: object,
    *,
    kind: str,
    presence: str = PRESENT,
    acted: bool = False,
) -> tuple[str, str | None]:
    """实现 spec §5.2 的状态映射，返回 ``(status, reason)``。

    ``presence`` 是 ``resolve()`` 的三态；``acted=True`` 表示 ``set()`` 已经执行，
    此时以动作后的回读判定 ``set`` / ``mismatch``。入口存在但尚未满足时返回
    ``mismatch`` 作为“需要动作”的信号，动作后必须重新调用本函数判定。
    """
    if requested is None:
        return NOT_REQUESTED, None
    if presence == MISSING:
        return _unavailable_status(requested, kind, ENTRY_MISSING)
    if presence == INELIGIBLE:
        return _unavailable_status(requested, kind, ACCOUNT_INELIGIBLE)
    if presence != PRESENT:
        raise ValueError(f"未知的控件 presence: {presence!r}")
    if kind == "toggle":
        matched = isinstance(applied, bool) and applied == requested
        if acted:
            return (SET, None) if matched else (MISMATCH, None)
        if matched:
            # 无需动作即已满足：请求开启记 set，请求关闭记 default_off。
            return (SET, None) if requested is True else (DEFAULT_OFF, None)
        return MISMATCH, None
    return (SET, None) if _value_matches(requested, applied) else (MISMATCH, None)


def option_failures(record: dict) -> list[str]:
    """汇总 ``unsupported`` / ``mismatch``，生成人类可读的失败清单。"""
    failures: list[str] = []
    for key in OPTION_KEYS:
        entry = record.get(key) or {}
        status = entry.get("status")
        if status not in (UNSUPPORTED, MISMATCH):
            continue
        reason = entry.get("reason")
        failures.append(f"{key}={status}({reason})" if reason else f"{key}={status}")
    return failures


def instagram_caption(
    title: str, description: str = "", tags: list[str] | None = None
) -> str:
    """Instagram 只有配文：把标题、正文与标签合并；CLI 校验与上传器共用。"""
    parts = [part.strip() for part in (title, description) if part and part.strip()]
    cleaned = [tag.strip().lstrip('#') for tag in (tags or [])]
    cleaned = [tag for tag in cleaned if tag]
    if cleaned:
        parts.append(' '.join(f'#{tag}' for tag in cleaned))
    return '\n\n'.join(parts)


def validate_publish_options(
    options: InstagramPublishOptions | None,
    *,
    image_count: int,
    caption: str,
    has_video: bool = False,
    has_thumbnail: bool = False,
) -> None:
    """spec §3.3 静态校验：全部失败抛 ``UsageError``（退出码 2），零浏览器。"""
    if has_video == bool(image_count):
        raise UsageError("必须且只能传入视频或图片文件")
    if has_thumbnail and not has_video:
        raise UsageError("Instagram 自定义封面仅用于视频/Reel")
    if len(caption) > MAX_CAPTION_LENGTH:
        raise UsageError(
            f"Instagram 配文（标题、正文、标签合计）不能超过 "
            f"{MAX_CAPTION_LENGTH} 字符"
        )
    if options is None:
        return

    alt_texts = options.alt_texts
    if alt_texts is not None:
        count = len(alt_texts)
        if count not in (0, image_count):
            raise UsageError(
                f"Instagram 替代文字数量不符：{count} 条，图片 {image_count} 张"
                "（必须为 0 条或与图片张数一致）"
            )
        for index, text in enumerate(alt_texts, start=1):
            length = len(text) if isinstance(text, str) else 0
            if not 1 <= length <= MAX_ALT_TEXT_LENGTH:
                raise UsageError(
                    f"Instagram 第 {index} 条替代文字长度不合法：{length} 字符"
                    f"（要求 1-{MAX_ALT_TEXT_LENGTH} 字符，不会截断）"
                )

    location = options.location
    if location is not None and (
        not isinstance(location, str) or not location.strip()
    ):
        raise UsageError("Instagram 地点不能为空")
