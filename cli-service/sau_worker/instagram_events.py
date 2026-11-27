"""Drain both streams while forwarding only projected, invocation-scoped publish evidence."""
import json
from subprocess import CompletedProcess
from threading import Thread

from .publish import PRE_SUBMIT_TIMEOUT


def bounded_lines(stream):
    # A long line can contain merchant copy or a media payload. Discard it in bounded pieces.
    limit = 8192
    for line in iter(lambda: stream.readline(limit), ""):
        if len(line) == limit and not line.endswith("\n"):
            while line and not line.endswith("\n"):
                line = stream.readline(limit)
            yield ""  # A discarded final line must also supersede earlier diagnostics.
            continue
        yield line.rstrip("\r\n")


def instagram_command(proc, nonce, on_processing):
    marker = "SAU-EVENT " + nonce + " "
    attempted = False
    last_diagnostic = ""

    def collect_stderr():
        nonlocal attempted, last_diagnostic
        for line in bounded_lines(proc.stderr):
            attempted |= line == "publish_attempted=true"
            last_diagnostic = line if line in ("publish_attempted=false", "publish_failure=upload_timeout", "login_reason=verification") or PRE_SUBMIT_TIMEOUT.fullmatch(line) else ""

    stderr_reader = Thread(target=collect_stderr, daemon=True)
    stderr_reader.start()
    terminal = {}
    processing = False
    try:
        for line in bounded_lines(proc.stdout):
            if terminal or not line.startswith(marker):
                continue
            try:
                event = json.loads(line[len(marker):])
            except (ValueError, RecursionError):
                continue
            if not isinstance(event, dict):
                continue
            status = event.get("status")
            if status == "processing" and not processing:
                processing = True
                on_processing()
            elif status in ("prepared", "published"):
                terminal = {k: event.get(k) for k in ("status", "post_id", "post_url")}
    finally:
        stderr_reader.join()
    code = proc.wait()
    diagnostic = "publish_attempted=true" if attempted or (code and (processing or terminal.get("status") == "published")) else last_diagnostic
    return CompletedProcess(proc.args, code, json.dumps(terminal), diagnostic)
