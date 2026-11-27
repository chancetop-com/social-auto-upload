"""Settle the original upload using the child exit and the selected platform's evidence."""
from .platforms import successful_receipt


def receipt(proc, task):
    evidence = {"cliInvoked": True, "exitCode": proc.returncode}
    attempted = "publish_attempted=true" in proc.stderr.splitlines()
    if proc.returncode == 0:
        success = successful_receipt(task, proc.stdout, task["noPublish"])
        if success:
            return {**evidence, **success}
    if attempted:
        return {**evidence, "outcome": "unknown", "reason": "possible_submission", "publishAttempted": True}
    before_timeout = proc.returncode == 1 and "尚未点击发布" in proc.stderr and "发布超时" in proc.stderr
    explicit_failure = proc.returncode == 1 and "publish_attempted=false" in proc.stderr.splitlines()
    if proc.returncode in (2, 10, 11) or explicit_failure or before_timeout:
        reason = "pre_submit_failure"
        if proc.returncode == 10:
            reason = "login_required"
        elif before_timeout:
            reason = "upload_timeout"
        return {**evidence, "outcome": "failed", "reason": reason}
    return {**evidence, "outcome": "unknown", "reason": "possible_submission"}
