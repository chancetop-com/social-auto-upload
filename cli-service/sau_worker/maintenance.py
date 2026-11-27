"""Run managed media retention at the desktop's next local 03:00."""
import asyncio
from datetime import datetime, time as wall_time, timedelta
import sys
import time


async def daily_cleanup(worker, *, clock=time.time, sleep=asyncio.sleep):
    last_run = None
    while True:
        now = clock()
        local = datetime.fromtimestamp(now)
        day = local.date()
        target = datetime.combine(day, wall_time(3))
        if target < local or day == last_run:
            day += timedelta(days=1)
            target = datetime.combine(day, wall_time(3))
        # Recompute regularly to follow local zone changes and suspend/resume.
        delay = target.timestamp() - now
        if delay > 0:
            await sleep(min(60, delay))
        wake = datetime.fromtimestamp(clock())
        if wake.date() != day or (wake.hour, wake.minute) != (3, 0):
            continue
        last_run = day
        cleanup = asyncio.create_task(asyncio.to_thread(worker.command, ["media", "cleanup"], timeout=None))
        try:
            proc = await asyncio.shield(cleanup)
            if proc.returncode:
                print("Scheduled media cleanup failed", file=sys.stderr, flush=True)
        except OSError:
            print("Scheduled media cleanup could not start", file=sys.stderr, flush=True)
        except asyncio.CancelledError:
            await asyncio.gather(cleanup, return_exceptions=True)
            raise
