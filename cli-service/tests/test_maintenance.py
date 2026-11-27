from datetime import datetime
import asyncio
import subprocess
import sys

import pytest


@pytest.mark.asyncio
async def test_local_three_skips_a_missed_day_and_drains_the_cleanup_child(tmp_path):
    from sau_worker.maintenance import daily_cleanup

    instant = datetime(2026, 11, 24, 2, 59, 59).timestamp()
    calls = []

    async def sleep(seconds):
        nonlocal instant
        if not calls:
            instant += seconds
        elif len(calls) == 1 and datetime.fromtimestamp(instant).day == 24:
            # Laptop resumes the next afternoon.
            instant = datetime(2026, 11, 25, 15).timestamp()
        elif len(calls) == 1:
            instant += seconds
        else:
            raise asyncio.CancelledError

    class Desktop:
        def command(self, args, timeout):
            calls.append((datetime.fromtimestamp(instant), args, timeout))
            return subprocess.run([sys.executable, "-c", "print('cleaned')"], cwd=tmp_path, capture_output=True)

    with pytest.raises(asyncio.CancelledError):
        await daily_cleanup(Desktop(), clock=lambda: instant, sleep=sleep)
    assert calls == [(datetime(2026, 11, 24, 3), ["media", "cleanup"], None),
                     (datetime(2026, 11, 26, 3), ["media", "cleanup"], None)]
