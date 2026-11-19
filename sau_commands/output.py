"""Shared user-facing CLI summaries."""

NO_PUBLISH_SUCCESS = "素材已上传，发布前检查已通过；已停止，未点击发布按钮。"


def report_upload_success(request, label, media):
    """For Studio upload commands, report success and identify an immediate post."""
    if request.no_publish:
        print(f"{label} upload: {media}")
        print(NO_PUBLISH_SUCCESS)
        return False
    print(f"{label} upload submitted: {media}")
    return not request.publish_date
