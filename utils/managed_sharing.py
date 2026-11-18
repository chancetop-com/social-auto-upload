"""Command-wide admission and last-user teardown for a local managed profile."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from contextvars import ContextVar
from hashlib import sha256
from time import monotonic

from loguru import logger

from utils.base_social_media import get_supported_social_media
from utils.errors import RateLimitedError
from utils.managed_browser import SharedBrowserProvider
from utils.managed_pages import managed_pages
from utils.profile_store import ProfileStore

LIFECYCLE_TIMEOUT = 10.0
_current = ContextVar("managed_command", default=None)


def current_command():
    return _current.get()


def _digest(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


async def _provider_call(provider, operation, *args):
    """Provider errors can carry authorization headers and complete CDP URLs."""
    try:
        return await asyncio.to_thread(getattr(provider, operation), *args)
    except RateLimitedError:
        raise RateLimitedError(f"{provider.mode} {operation} 请求过于频繁（HTTP 429）。") from None
    except Exception:
        raise RuntimeError(f"{provider.mode} {operation} 失败，无法确认 Profile 当前状态或连接。") from None


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
    async def lifecycle(self):
        deadline = monotonic() + LIFECYCLE_TIMEOUT
        lock = self.store.try_lock("lifecycle")
        while lock is None:
            if monotonic() >= deadline:
                raise RuntimeError(f"{self.mode} Profile 正在协调启动或停止，等待超时。")
            await asyncio.sleep(0.05)
            lock = self.store.try_lock("lifecycle")
        try:
            yield
        finally:
            lock.close()

    def has_members(self):
        for platform in get_supported_social_media():
            lock = self.store.try_lock("member-" + platform)
            if lock is None:
                return True
            lock.close()
        return False

    async def connection(self, provider: SharedBrowserProvider, headless: bool):
        record = self.store.read_record()
        resource = _digest(provider.resource_identity)
        if record is not None and record.get("resource") != resource:
            raise RuntimeError(f"{self.mode} Profile 的服务或文件夹与共享记录不符。")
        peers = self.has_members()
        if peers and (not record or record.get("phase") != "active"):
            raise RuntimeError("托管 Profile 的成员与共享记录不一致。")
        if record and record.get("phase") not in {"active", "starting", "stopping"}:
            raise RuntimeError("托管 Profile 的共享记录无效。")

        await _provider_call(provider, "probe")
        state = await _provider_call(provider, "observe")
        if record and record["phase"] == "stopping" and state.active:
            raise RuntimeError(f"{self.mode} Profile 上次停止尚未确认。")
        if state.active:
            if not state.endpoint:
                raise RuntimeError(f"{self.mode} Profile 当前连接不可用。")
            endpoint = state.endpoint
            setting = state.headless
            if peers:
                if record.get("endpoint") != _digest(endpoint):
                    raise RuntimeError(f"{self.mode} Profile 的当前连接与同行不符。")
                if setting is None:
                    setting = record.get("headless")
            if self.explicit_headless is not None and setting is not self.explicit_headless:
                raise RuntimeError(f"{self.mode} Profile 的 headless 设置冲突或无法确认。")
        else:
            if peers or (record and record["phase"] == "starting"):
                raise RuntimeError(f"{self.mode} Profile 上次启动或当前连接尚未确认。")
            self.store.write_record({"resource": resource, "phase": "starting"})
            try:
                endpoint = await _provider_call(provider, "start", headless)
            except RateLimitedError:
                self.store.clear_record()
                raise
            setting = headless
        if not isinstance(endpoint, str) or not endpoint:
            raise RuntimeError(f"{self.mode} Profile 当前连接不可用。")
        return endpoint, {"resource": resource, "phase": "active",
                          "endpoint": _digest(endpoint), "headless": setting}

    @asynccontextmanager
    async def session(self, playwright, provider, headless, connect):
        if (provider.mode, provider.profile_id) != (self.mode, self.profile_id):
            raise RuntimeError("托管命令请求的 Profile 与平台资格不符。")
        browser = None
        try:
            async with self.lifecycle():
                endpoint, record = await self.connection(provider, headless)
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

            logger.info("托管 Profile 已连接：mode={}，platform={}", self.mode, self.platform)
            async with managed_pages(contexts[0]) as pages:
                yield browser, pages
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
            async with self.lifecycle():
                self.member.close()
                self.member = None
                self.reservation.close()
                self.reservation = None
                if not self.has_members():
                    record = self.store.read_record()
                    if not record or record.get("phase") != "active":
                        raise RuntimeError("托管 Profile 的共享记录无效。")
                    self.store.write_record({**record, "phase": "stopping"})
                    try:
                        await _provider_call(self.provider, "stop")
                    except RateLimitedError:
                        # The provider rejected this operation before dispatch.
                        self.store.clear_record()
                        raise
                    self.store.clear_record()
        except Exception:
            logger.warning("{} Profile 停止或清理失败，可能仍在运行。", self.mode)
        finally:
            if self.member is not None:
                self.member.close()
            if self.reservation is not None:
                self.reservation.close()


@asynccontextmanager
async def managed_command(platform, mode, profile_id, explicit_headless):
    command = ManagedCommand(platform, mode, profile_id, explicit_headless)
    token = _current.set(command)
    try:
        yield
    finally:
        _current.reset(token)
        await command.leave()
