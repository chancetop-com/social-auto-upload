"""Shared user-facing CLI summaries."""

from utils.caption_topics import STATUS_LINKED
from utils.post_location import LocationReport

NO_PUBLISH_SUCCESS = "素材已上传，发布前检查已通过；已停止，未点击发布按钮。"
AI_DECLARATION_NOT_REQUESTED = "AI 声明：未请求（保留页面当前值）"
LOCATION_NOT_REQUESTED = "帖子地点：未请求（保留页面当前值）"


def report_caption_topics(request, prefix: str) -> None:
    """Print one inline-topic result per caption occurrence, in order.

    ``prefix`` keeps the platform summary distinguishable from the existing
    success line (for example ``Xiaohongshu 配文话题 1/2：#coffee 已关联``).
    Duplicates are preserved.  No caption topic means no extra line, so the
    omitted/empty-caption path stays byte-for-byte unchanged.
    """
    results = getattr(request, "topic_results", None)
    if not results:
        return
    total = len(results)
    for item in results:
        text = item.get("text") or ""
        if item.get("status") == STATUS_LINKED:
            outcome = "已关联"
        else:
            reason = item.get("reason") or "未关联"
            outcome = f"保留文字，{reason}"
        print(f"{prefix} 配文话题 {item.get('index')}/{total}：{text} {outcome}")


def report_location(request):
    """Print the post-location request and its page readback (ticket 18).

    Omitted ``--location`` is reported as not requested; the uploader never
    touches the control.  A successful selection reports the requested name,
    the clicked candidate (with its visible address when present) and the
    collapsed control's final name.
    """
    location = getattr(request, "location", None)
    if location is None:
        print(LOCATION_NOT_REQUESTED)
        return
    report = getattr(request, "location_report", None)
    if isinstance(report, dict):
        requested = report.get("requested") or location
        summary = LocationReport(
            requested=requested,
            clicked_name=report.get("clicked_name") or requested,
            address=report.get("address"),
            final_name=report.get("final_name") or "未读到",
        )
        print(summary.summary())
        return
    print(f"帖子地点：请求={location}，终值=未读到，结果=未验证")


def report_ai_declaration(request):
    """Print the AI/content-type request and its page readback (ticket 15).

    The uploader records the readback on the request.  On pre-publish failure no
    success summary is printed at all; the exception carries the same
    request/final-value/reason fields.
    """
    content_type = getattr(request, "content_type", None)
    if content_type is None:
        print(AI_DECLARATION_NOT_REQUESTED)
        return
    report = getattr(request, "declaration_report", None)
    field = "AI 声明" if content_type == "ai" else "内容类型声明"
    if isinstance(report, dict):
        label = report.get("requested_label") or content_type
        observed = report.get("observed")
        shown = observed if observed else "未读到"
        status = "已设置"
    else:
        label = content_type
        shown = "未读到"
        status = "未验证"
    print(
        f"{field}：请求={content_type}（{label}），"
        f"终值={shown}，结果={status}"
    )


def report_upload_success(request, label, media):
    """For Studio upload commands, report success and identify an immediate post."""
    if request.no_publish:
        print(f"{label} upload: {media}")
        print(NO_PUBLISH_SUCCESS)
        return False
    print(f"{label} upload submitted: {media}")
    return not request.publish_date
