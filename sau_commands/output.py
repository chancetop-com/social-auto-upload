"""Shared user-facing CLI summaries."""

NO_PUBLISH_SUCCESS = "素材已上传，发布前检查已通过；已停止，未点击发布按钮。"
AI_DECLARATION_NOT_REQUESTED = "AI 声明：未请求（保留页面当前值）"


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
