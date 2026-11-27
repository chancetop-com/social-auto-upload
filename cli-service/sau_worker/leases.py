"""Keep a claimed command's grant alive until its worker finishes."""
import asyncio
from contextlib import asynccontextmanager, suppress
from contextvars import ContextVar
from pathlib import Path
from tempfile import TemporaryDirectory

import httpx

from .providers import window_closed


local_close_marker = ContextVar("local_close_marker", default=None)


async def heartbeat(worker, body, interval):
    while True:
        await asyncio.sleep(interval)
        try:
            await worker.post("/publish-task/profile-lease/renew", body)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 409:
                return
        except httpx.HTTPError:
            pass  # Only a valid, unexpired grant can be renewed after reconnect.


@asynccontextmanager
async def command_lease(worker, record):
    if not record.get("leaseGrantId"):
        # A command already claimed before the Gateway's lease migration.
        yield
        return
    body = {"workflowId": record["workflowId"], "sessionId": worker.session_id,
            "leaseGrantId": record["leaseGrantId"]}
    task = record["task"]
    renewal = asyncio.create_task(heartbeat(worker, body, record["renewAfterSeconds"]))
    with TemporaryDirectory(prefix="sau-close-") as directory:
        marker = Path(directory) / "closed"
        token = local_close_marker.set(marker if task["provider"] == "local-chrome" else None)
        cancelled = False
        try:
            yield
        except asyncio.CancelledError:
            # A subprocess in a thread can outlive cancellation; let the lease expire.
            cancelled = True
            raise
        finally:
            renewal.cancel()
            with suppress(asyncio.CancelledError):
                await renewal
            local_close_marker.reset(token)
            if not cancelled:
                try:
                    completion = await worker.post("/publish-task/profile-lease/complete", body)
                    if completion["idle"]:
                        if task["provider"] == "local-chrome":
                            closed = marker.is_file()
                        else:
                            closed = await window_closed(worker.client, worker.settings.providers, task)
                        if closed:
                            await worker.post("/publish-task/profile-lease/release", {**body, "windowClosed": True})
                except httpx.HTTPError:
                    pass  # A lost completion or observation falls back to expiry.
