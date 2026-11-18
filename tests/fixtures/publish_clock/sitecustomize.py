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
