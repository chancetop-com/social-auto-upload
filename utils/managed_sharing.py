"""Command-wide admission and last-user teardown for a local managed profile."""
from __future__ import annotations

import asyncio
from concurrent.futures import Future
from contextlib import asynccontextmanager
from contextvars import ContextVar
from hashlib import sha256
from threading import Thread
from time import monotonic, sleep

from loguru import logger

from utils.base_social_media import get_supported_social_media
from utils.errors import (
    ProfileConnectionUnavailableError, ProfileStartingError, ProviderRequestRejected, RateLimitedError,
)
from utils.managed_browser import SharedBrowserProvider
from utils.managed_pages import managed_pages
from utils.profile_store import ProfileStore

LIFECYCLE_TIMEOUT = 10.0
# An admitted member must outlast a contender's provider reads, CDP retries
# and final status query before giving up the obligation to stop the browser.
DEPARTURE_TIMEOUT = 180.0
_current = ContextVar("managed_command", default=None)


def current_command():
    return _current.get()


def _digest(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def _provider_request(provider, operation, *args):
    """Provider errors can carry authorization headers and complete CDP URLs."""
    try:
        return getattr(provider, operation)(*args)
    except RateLimitedError:
        raise RateLimitedError(f"{provider.mode} {operation} 请求过于频繁（HTTP 429）。") from None
    except ProviderRequestRejected:
        raise ProviderRequestRejected(f"{provider.mode} {operation} 请求被拒绝。") from None
    except ProfileStartingError:
        raise RuntimeError(f"{provider.mode} {operation}：Profile 正在启动。") from None
    except ProfileConnectionUnavailableError:
        raise ProfileConnectionUnavailableError(f"{provider.mode} {operation}：Profile 的当前连接不可用。") from None
    except Exception:
        raise RuntimeError(f"{provider.mode} {operation} 失败，无法确认 Profile 当前状态或连接。") from None


async def _provider_call(provider, operation, *args):
    return await asyncio.to_thread(_provider_request, provider, operation, *args)


def _stop_finished(state, acknowledged_endpoint):
    # A replacement instance establishes completion only after a successful
    # Stop reply. A lost request can still execute against a reopened profile.
    return not state.active or (
        acknowledged_endpoint is not None and bool(state.endpoint) and _digest(state.endpoint) != acknowledged_endpoint
    )


async def _wait_for_stopped(provider, deadline, acknowledged_endpoint=None):
    # Only read operations may outlive the deadline. asyncio.run joins its
    # default executor on exit, so a stalled HTTP read needs a daemon thread.
    outcome = Future()
    outcome.set_running_or_notify_cancel()

    def observe():
        try:
            _provider_request(provider, "probe")
            while monotonic() < deadline:
                try:
                    state = _provider_request(provider, "observe")
                except ProfileConnectionUnavailableError:
                    pass  # CDP can disappear before Launcher changes its status.
                else:
                    if _stop_finished(state, acknowledged_endpoint):
                        outcome.set_result(state)
                        return
                sleep(min(0.5, max(0, deadline - monotonic())))
            raise asyncio.TimeoutError
        except Exception as exc:
            outcome.set_exception(exc)

    remaining = deadline - monotonic()
    if remaining > 0:
        Thread(target=observe, daemon=True).start()
        try:
            return await asyncio.wait_for(asyncio.wrap_future(outcome), remaining)
        except asyncio.TimeoutError:
            pass
    raise RuntimeError(f"{provider.mode} Profile 上次停止尚未确认，等待超时。")


class ManagedCommand:
    def __init__(self, platform, mode, profile_id, explicit_headless):
        self.platform = platform
        self.mode = mode
        self.profile_id = profile_id
        self.explicit_headless = explicit_headless
        self.store = ProfileStore(mode, profile_id)
        self.reservation = self.store.try_lock("platform-" + platform)
        if self.reservation is None:
            raise RuntimeError(f"{platform} 已占用此托管 Profile。")
        self.member = None
        self.provider = None

    @asynccontextmanager
    async def lifecycle(self, timeout=LIFECYCLE_TIMEOUT):
        deadline = monotonic() + timeout
        lock = self.store.try_lock("lifecycle")
        while lock is None:
            if monotonic() >= deadline:
                raise RuntimeError(f"{self.mode} Profile 正在协调启动或停止，等待超时。")
            await asyncio.sleep(0.05)
            lock = self.store.try_lock("lifecycle")
        try:
            yield deadline
        finally:
            lock.close()

    def has_members(self):
        for platform in get_supported_social_media():
            lock = self.store.try_lock("member-" + platform)
            if lock is None:
                return True
            lock.close()
        return False

    async def connection(self, provider: SharedBrowserProvider, headless: bool, deadline: float):
        record = self.store.read_record()
        resource = _digest(provider.resource_identity)
        if record is not None and record.get("resource") != resource:
            raise RuntimeError(f"{self.mode} Profile 的服务或文件夹与共享记录不符。")
        peers = self.has_members()
        if peers and (not record or record.get("phase") != "active"):
            raise RuntimeError("托管 Profile 的成员与共享记录不一致。")

        if record and record["phase"] in {"stopping", "stop_acknowledged"}:
            old_endpoint = record.get("endpoint") if record["phase"] == "stop_acknowledged" else None
            state = await _wait_for_stopped(provider, deadline, old_endpoint)
        else:
            await _provider_call(provider, "probe")
            state = await _provider_call(provider, "observe")
        if state.active:
            if not state.endpoint:
                raise RuntimeError(f"{self.mode} Profile 当前连接不可用。")
            endpoint = state.endpoint
            setting = state.headless
            same_instance = (record is not None and record["phase"] == "active"
                             and record.get("endpoint") == _digest(endpoint))
            if peers and not same_instance:
                raise RuntimeError(f"{self.mode} Profile 的当前连接与同行不符。")
            if same_instance and setting is None:
                setting = record.get("headless")
        else:
            if peers or (record and record["phase"] == "starting"):
                raise RuntimeError(f"{self.mode} Profile 上次启动或当前连接尚未确认。")
            self.store.write_record({"resource": resource, "phase": "starting"})
            try:
                endpoint = await _provider_call(provider, "start", headless)
            except (RateLimitedError, ProviderRequestRejected):
                self.store.clear_record()
                raise
            setting = headless
        if not isinstance(endpoint, str) or not endpoint:
            raise RuntimeError(f"{self.mode} Profile 当前连接不可用。")
        active_record = {"resource": resource, "phase": "active",
                         "endpoint": _digest(endpoint), "headless": setting}
        if not state.active or (record and record["phase"] == "starting"):
            # A Start response or a later authenticated Active can establish
            # completion before compatibility checks and the CDP connection.
            self.store.write_record(active_record)
        if state.active and self.explicit_headless is not None and setting is not self.explicit_headless:
            raise RuntimeError(f"{self.mode} Profile 的 headless 设置冲突或无法确认。")
        return endpoint, active_record

    @asynccontextmanager
    async def session(self, playwright, provider, headless, connect):
        if (provider.mode, provider.profile_id) != (self.mode, self.profile_id):
            raise RuntimeError("托管命令请求的 Profile 与平台资格不符。")
        browser = None
        try:
            async with self.lifecycle() as deadline:
                endpoint, record = await self.connection(provider, headless, deadline)
                try:
                    browser = await connect(playwright, provider, endpoint)
                    contexts = browser.contexts
                except Exception:
                    raise RuntimeError(f"{self.mode} 无法通过 CDP 连接当前 Profile。") from None
                if len(contexts) != 1:
                    raise RuntimeError(f"{self.mode} Profile 的浏览器上下文数量异常。")
                self.store.write_record(record)
                if self.member is None:
                    self.member = self.store.try_lock("member-" + self.platform)
                    if self.member is None:
                        raise RuntimeError("无法安全登记托管 Profile 成员。")
                self.provider = provider

            async with managed_pages(contexts[0]) as pages:
                yield browser, pages, record["headless"]
        finally:
            if browser is not None:
                try:
                    await browser.close()
                except Exception:
                    logger.warning("无法断开本命令的托管浏览器连接。")

    async def leave(self):
        try:
            if self.member is None:
                return
            async with self.lifecycle(timeout=DEPARTURE_TIMEOUT):
                self.member.close()
                self.member = None
                self.reservation.close()
                self.reservation = None
                if not self.has_members():
                    record = self.store.read_record()
                    if not record or record.get("phase") != "active":
                        raise RuntimeError("托管 Profile 的共享记录无效。")
                    # Python 3.10 cancels every Task on Ctrl-C. An executor
                    # Future survives shutdown cancellation and lets us retain
                    # the mutex until both the HTTP request and record update finish.
                    stop = asyncio.get_running_loop().run_in_executor(None, self.stop, record)
                    try:
                        await asyncio.shield(stop)
                    except asyncio.CancelledError:
                        await stop
                        raise
        except Exception:
            logger.warning("{} Profile 停止或清理失败，可能仍在运行。", self.mode)
        finally:
            if self.member is not None:
                self.member.close()
            if self.reservation is not None:
                self.reservation.close()

    def stop(self, record):
        self.store.write_record({**record, "phase": "stopping"})
        try:
            _provider_request(self.provider, "stop")
        except (RateLimitedError, ProviderRequestRejected):
            self.store.clear_record()
            raise
        if self.provider.asynchronous_stop:
            self.store.write_record({**record, "phase": "stop_acknowledged"})
            state = _provider_request(self.provider, "observe")
            if not _stop_finished(state, record["endpoint"]):
                return
        self.store.clear_record()


@asynccontextmanager
async def managed_command(platform, mode, profile_id, explicit_headless):
    command = ManagedCommand(platform, mode, profile_id, explicit_headless)
    token = _current.set(command)
    try:
        yield
    finally:
        _current.reset(token)
        # Cancellation cannot cancel a synchronous provider request. Keep its
        # lifecycle lock and finish recording the response before propagating it.
        departure = asyncio.create_task(command.leave())
        try:
            await asyncio.shield(departure)
        except asyncio.CancelledError:
            await departure
            raise
