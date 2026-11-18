"""Supply wall-clock time and sleep to the installed CLI's real publish gate."""
import asyncio
import os
from datetime import datetime
from functools import partial
from pathlib import Path

if "SAU_TEST_CLOCK" in os.environ:
    from uploader import publish_gate

    clock_file = Path(os.environ["SAU_TEST_CLOCK"])
    entered_file = Path(os.environ["SAU_TEST_GATE_ENTERED"])

    def now(tz=None):
        return datetime.fromtimestamp(float(clock_file.read_text()), tz)

    async def sleep(seconds):
        entered_file.touch()
        await asyncio.sleep(min(seconds, 0.05))

    publish_gate.wait_until_publish_allowed = partial(
        publish_gate.wait_until_publish_allowed, now=now, sleep=sleep
    )

# Interrupt the requested result write at the OS boundary. Other CLI processes
# and Chromium keep their normal limits.
if "SAU_TEST_RESULT_LIMIT" in os.environ:
    import resource
    import signal
    import sys

    result_dir = os.environ["SAU_TEST_RESULT_LIMIT"]
    signal.signal(signal.SIGXFSZ, signal.SIG_DFL)

    def interrupt_result(event, args):
        if event == "open":
            path, _, flags = args
            if (isinstance(path, str) and os.path.dirname(path) == result_dir
                    and flags & (os.O_WRONLY | os.O_RDWR)):
                resource.setrlimit(resource.RLIMIT_FSIZE, (32, 32))

    sys.addaudithook(interrupt_result)
