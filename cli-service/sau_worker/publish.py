"""Settle the original upload using the child exit and the selected platform's evidence."""
import re

from .platforms import successful_receipt


PRE_SUBMIT_TIMEOUT = re.compile(
    r"Instagram 发布就绪超时（上限 60 秒或剩余预算）：Share 按钮未出现或不可用；尚未点击发布，未发布任何内容。|"
    r"(?:TikTok|Instagram|Rednote|小红书) ?发布超时（[0-9]+(?:\.[0-9]+)? (?:分钟|秒)）：尚未点击发布，未发布任何内容。"
)


def receipt(proc, task):
    evidence = {"cliInvoked": True, "exitCode": proc.returncode}
    attempted = "publish_attempted=true" in proc.stderr.splitlines()
    if proc.returncode == 0:
        success = successful_receipt(task, proc.stdout, task["noPublish"])
        if success:
            return {**evidence, **success}
    if attempted:
        return {**evidence, "outcome": "unknown", "reason": "possible_submission", "publishAttempted": True}
    diagnostics = proc.stderr.splitlines()
    before_timeout = proc.returncode == 1 and diagnostics and (
        diagnostics[-1] == "publish_failure=upload_timeout" or PRE_SUBMIT_TIMEOUT.fullmatch(diagnostics[-1])
    )
    explicit_failure = proc.returncode == 1 and diagnostics[-1:] == ["publish_attempted=false"]
    preparation_failed = task["noPublish"] and proc.returncode == 1
    if proc.returncode in (2, 10, 11) or explicit_failure or before_timeout or preparation_failed:
        reason = "pre_submit_failure"
        if proc.returncode == 10:
            reason = "verification_required" if diagnostics[-1:] == ["login_reason=verification"] else "login_required"
        elif before_timeout:
            reason = "upload_timeout"
        return {**evidence, "outcome": "failed", "reason": reason}
    return {**evidence, "outcome": "unknown", "reason": "possible_submission"}
