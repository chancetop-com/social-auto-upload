"""Drain both streams while forwarding only projected, invocation-scoped publish evidence."""
import json
from subprocess import CompletedProcess
from threading import Thread


def bounded_lines(stream):
    # A long line can contain merchant copy or a media payload. Discard it in bounded pieces.
    limit = 8192
    for line in iter(lambda: stream.readline(limit), ""):
        if len(line) == limit and not line.endswith("\n"):
            while line and not line.endswith("\n"):
                line = stream.readline(limit)
            continue
        yield line.rstrip("\r\n")


def instagram_command(proc, nonce, on_processing):
    marker = "SAU-EVENT " + nonce + " "
    evidence = set()

    def collect_stderr():
        for line in bounded_lines(proc.stderr):
            if line in ("publish_attempted=true", "publish_attempted=false"):
                evidence.add(line)
            elif "尚未点击发布" in line and "发布超时" in line:
                evidence.add("发布超时 尚未点击发布")

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
    if processing and code:
        evidence.add("publish_attempted=true")
    return CompletedProcess(proc.args, code, json.dumps(terminal), "\n".join(sorted(evidence)))
