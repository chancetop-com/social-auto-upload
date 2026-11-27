"""Media acquisition uses an occurrence-scoped cache on the executing desktop."""
from hashlib import sha256


def media_task_id(workflow_id):
    return sha256(workflow_id.encode("utf-8")).hexdigest()


def predownload_args(task):
    urls = [item["url"] for item in task["media"]]
    if not urls or any(not url.startswith(("http://", "https://")) for url in urls):
        raise ValueError("Expected desktop-readable media URLs")
    return ["media", "predownload", "--task-id=" + media_task_id(task["workflowId"]), "--urls", *urls]
