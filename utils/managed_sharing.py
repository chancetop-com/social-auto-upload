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
    ProfileConnectionUnavailableError, ProfileStartingError, ProviderDiagnosticError,
    ProviderRequestRejected, RateLimitedError,
)
from utils.managed_browser import ProviderHints, SharedBrowserProvider
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


def _provider_hints(provider) -> ProviderHints:
    """Return the provider's wording, or neutral defaults for older providers."""
    hints = getattr(provider, "hints", None)
    return hints if isinstance(hints, ProviderHints) else ProviderHints()


def _stop_settle_seconds(provider) -> float:
    """Return the provider's required quiet period after a stop ACK."""
    value = getattr(provider, "stop_settle_seconds", 0.0)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        return 0.0
    return float(value)


def _stop_timeout_message(provider, reason):
    if _stop_settle_seconds(provider) <= 0:
        return f"{provider.mode} Profile 上次停止尚未确认，等待超时。"
    hints = _provider_hints(provider)
    if reason == "process-alive":
        return (
            f"{provider.mode} Profile 上次停止未完成：关闭请求已获回应，"
            "但旧窗口进程仍在运行，等待超时；"
            f"{hints.stop_settle_hint}"
        )
    if reason == "settle":
        return (
            f"{provider.mode} Profile 上次停止未完成：关闭请求已获回应，"
            f"但关闭后尚未满 {_stop_settle_seconds(provider):g} 秒，等待超时；"
            "请稍后重试。"
        )
    return (
        f"{provider.mode} Profile 上次停止尚未确认：关闭请求已获回应，"
        "但无法确认旧窗口进程已退出，等待超时；"
        f"{hints.stop_unconfirmed_hint}"
    )


def _provider_request(provider, operation, *args):
    """Provider errors can carry authorization headers and complete CDP URLs."""
    try:
        return getattr(provider, operation)(*args)
    except RateLimitedError:
        raise RateLimitedError(f"{provider.mode} {operation} 请求过于频繁（HTTP 429）。") from None
    except ProviderDiagnosticError:
        # Already redacted and actionable; the generic replacements below would
        # hide which operation/status failed and how to fix it.
        raise
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


def _newer_launch(state, record):
    previous = record.get("launched_at_ns")
    return previous is not None and state.launched_at_ns is not None and state.launched_at_ns > previous


def _stop_finished(state, acknowledged_record):
    # A changed port or browser UUID alone can point at an unrelated browser.
    # A later MLX launch after an acknowledged Stop establishes a replacement.
    return not state.active or (
        acknowledged_record is not None and bool(state.endpoint)
        and _digest(state.endpoint) != acknowledged_record["endpoint"]
        and _newer_launch(state, acknowledged_record)
    )


async def _wait_for_stopped(
    provider, deadline, acknowledged_record=None, *, confirmed=False, settle_until=None,
):
    # Only read operations may outlive the deadline. asyncio.run joins its
    # default executor on exit, so a stalled HTTP read needs a daemon thread.
    outcome = Future()
    outcome.set_running_or_notify_cancel()
    failure = {"reason": "unconfirmed"}

    def observe():
        try:
            _provider_request(provider, "probe")
            while monotonic() < deadline:
                try:
                    state = _provider_request(provider, "observe")
                except ProfileConnectionUnavailableError:
                    # A missing port/CDP endpoint is not proof the process
                    # exited; keep polling until the admission deadline.
                    failure["reason"] = "unconfirmed"
                else:
                    if confirmed or _stop_finished(state, acknowledged_record):
                        now = monotonic()
                        if state.active or settle_until is None or now >= settle_until:
                            outcome.set_result(state)
                            return
                        failure["reason"] = "settle"
                        sleep(min(0.5, max(0.0, min(settle_until - now,
                                                        deadline - now))))
                        continue
                    if state.active:
                        failure["reason"] = "process-alive"
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
    raise RuntimeError(_stop_timeout_message(provider, failure["reason"]))


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

    async def observe_after_stop(self, provider, record, deadline):
        state = None
        if record["phase"] != "stopped":
            acknowledged = record if record["phase"] == "stop_acknowledged" else None
            state = await _wait_for_stopped(provider, deadline, acknowledged)
            if _stop_settle_seconds(provider) == 0 or state.active:
                return state
            record = {**record, "phase": "stopped", "exit_observed_at": monotonic()}
            self.store.write_record(record)

        # A stop without an ACK owes a full interval from the first confirmed
        # exit. A timestamp from a previous boot may exceed current uptime.
        now = monotonic()
        since = record.get("stop_acknowledged_at", record["exit_observed_at"])
        settle_until = min(since, now) + _stop_settle_seconds(provider)
        if state is not None and now >= settle_until:
            return state
        # Exit was confirmed under the lifecycle lock. A live observation now
        # describes a new desktop run. Only cold starts owe the quiet period.
        return await _wait_for_stopped(
            provider, deadline, confirmed=True, settle_until=settle_until,
        )

    async def connection(self, provider: SharedBrowserProvider, headless: bool, deadline: float):
        record = self.store.read_record()
        resource = _digest(provider.resource_identity)
        if record is not None and record["phase"] != "stopped" and record.get("resource") != resource:
            raise RuntimeError(f"{self.mode} Profile 的服务或文件夹与共享记录不符。")
        peers = self.has_members()
        if peers and (not record or record.get("phase") != "active"):
            raise RuntimeError("托管 Profile 的成员与共享记录不一致。")

        if record and record["phase"] in {"stopping", "stop_acknowledged", "stopped"}:
            state = await self.observe_after_stop(provider, record, deadline)
        else:
            await _provider_call(provider, "probe")
            try:
                state = await _provider_call(provider, "observe")
            except (ProfileConnectionUnavailableError, ProviderDiagnosticError) as exc:
                hint = _provider_hints(provider).start_unconfirmed_hint
                if hint is not None and record and record.get("phase") == "starting":
                    # The previous start reply was lost and the current
                    # port/CDP state cannot prove that it finished.  Keep the
                    # starting record and scene; never retry open or close.
                    raise RuntimeError(
                        f"{self.mode} Profile {hint}：{exc}"
                    ) from None
                raise
        launch_time = state.launched_at_ns
        if state.active:
            if not state.endpoint:
                raise RuntimeError(f"{self.mode} Profile 当前连接不可用。")
            endpoint = state.endpoint
            setting = state.headless
            same_instance = (record is not None and record["phase"] == "active"
                             and record.get("endpoint") == _digest(endpoint))
            if peers and not same_instance:
                raise RuntimeError(f"{self.mode} Profile 的当前连接与同行不符。")
            if record is not None and record["phase"] == "active" and self.mode == "multilogin":
                previous_launch = record.get("launched_at_ns")
                if same_instance:
                    if previous_launch is not None and launch_time not in (None, previous_launch):
                        raise RuntimeError("Multilogin Profile 的启动时间与浏览器实例不符。")
                    launch_time = previous_launch if launch_time is None else launch_time
                elif not _newer_launch(state, record):
                    raise RuntimeError("无法确认 Multilogin Profile 已重新启动。")
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
        if launch_time is not None:
            active_record["launched_at_ns"] = launch_time
        if not state.active or (record and record["phase"] == "starting"):
            # A Start response or a later authenticated Active can establish
            # completion before compatibility checks and the CDP connection.
            self.store.write_record(active_record)
        if not state.active and self.mode == "multilogin":
            # Start supplies a port. Capture the scoped running observation for
            # this exact browser before a later process has to recover it.
            started = await _provider_call(provider, "observe")
            if not started.active or started.endpoint != endpoint:
                raise RuntimeError("无法确认 Multilogin Profile 已启动的浏览器实例。")
            if started.launched_at_ns is not None:
                active_record["launched_at_ns"] = started.launched_at_ns
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
                    hint = _provider_hints(provider).cdp_connect_hint
                    raise RuntimeError(
                        f"{self.mode} 无法通过 CDP 连接当前 Profile。{hint}"
                    ) from None
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
        settle = _stop_settle_seconds(self.provider)
        stopping = {**record, "phase": "stopping"}
        if settle > 0:
            stopping["stop_requested_at"] = monotonic()
        self.store.write_record(stopping)
        try:
            _provider_request(self.provider, "stop")
        except (RateLimitedError, ProviderRequestRejected):
            self.store.clear_record()
            raise
        if self.provider.asynchronous_stop:
            acknowledged = {**stopping, "phase": "stop_acknowledged"}
            if settle > 0:
                acknowledged["stop_acknowledged_at"] = monotonic()
            self.store.write_record(acknowledged)
            state = _provider_request(self.provider, "observe")
            if not _stop_finished(state, record):
                return
            if settle > 0 and not state.active:
                self.store.write_record({**acknowledged, "phase": "stopped", "exit_observed_at": monotonic()})
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
