# -*- coding: utf-8 -*-
"""The single browser lifecycle seam for local and managed modes.

Callers only ever acquire a browser through :func:`browser_session`.  Ownership
and teardown live here: the returned :class:`BrowserSession` intentionally has no
``owned`` flag and no ``stop()`` method, so callers cannot stop a profile twice
or stop it before the work is finished.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import (
    TYPE_CHECKING,
    Any,
    AsyncIterator,
    Awaitable,
    Callable,
    Iterable,
    Literal,
    Mapping,
)
from urllib.parse import urlsplit

from loguru import logger

from utils.base_social_media import set_init_script
from utils.errors import StartIncompleteError
from utils.managed_browser import ManagedBrowserProvider

if TYPE_CHECKING:  # pragma: no cover - typing only, keeps imports light
    from patchright.async_api import Browser, BrowserContext, Playwright

CONNECT_TIMEOUT_MS = 10_000
CONNECT_ATTEMPTS = 3
CONNECT_BACKOFF_SECONDS = (2, 4)

_PROVIDER_LABELS = {
    "multilogin": "Multilogin",
    "adspower": "AdsPower",
}

_CONNECTION_HINTS = {
    "multilogin": (
        "若你使用 Docker launcher，CDP 端口默认未映射到宿主机；"
        "v1 请改用 Multilogin 桌面应用。"
    ),
    "adspower": (
        "请确认 AdsPower 桌面应用与 CLI 运行在同一台机器；"
        "AdsPower 不支持容器化或跨机部署。"
    ),
}

#: Managed mode cannot apply the local launch/context options: the Profile owns
#: the fingerprint, UI language and timezone.  The message lists key names only.
MANAGED_IGNORED_WARNING = (
    "托管模式忽略本地浏览器参数：{keys}"
    "；Profile 负责指纹与界面语言，语言/UA/时区请在 Profile 内设置"
)

#: Options accepted by ``browser_session`` that a managed run silently drops.
_IGNORED_OPTION_NAMES = (
    "launch_kwargs",
    "context_kwargs",
    "init_script",
    "context_setup",
)


def provider_label(mode: str) -> str:
    """Return the product name shown to users for a session mode."""
    return _PROVIDER_LABELS.get(mode, mode)


def _ignored_option_names(
    *,
    launch_kwargs: Mapping[str, Any] | None,
    context_kwargs: Mapping[str, Any] | None,
    init_script: bool,
    context_setup: Callable[..., Any] | None,
    extra: Iterable[str] = (),
) -> tuple[str, ...]:
    """Return the non-empty local-only options a managed run would drop.

    Empty values (``False`` / ``{}`` / ``None``) are not dropped content, so
    they never appear in the warning or the startup log.  ``extra`` carries
    caller-known drops such as the CLI ``--account`` flag.
    """
    values = {
        "launch_kwargs": launch_kwargs,
        "context_kwargs": context_kwargs,
        "init_script": init_script,
        "context_setup": context_setup,
    }
    names = [name for name in _IGNORED_OPTION_NAMES if bool(values[name])]
    names.extend(name for name in extra if name)
    return tuple(names)


def _connection_hint(mode: str) -> str:
    return _CONNECTION_HINTS.get(mode, "")


def _startup_line(
    *,
    mode: str,
    headless: bool,
    identity: str,
    ignored: tuple[str, ...],
    extras: tuple[str, ...] = (),
) -> str:
    """Build the single "session is ready" line both modes log once per run."""
    fields = (
        f"mode={mode}",
        f"headless={'headless' if headless else 'headed'}",
        f"identity={identity}",
        f"ignored={', '.join(ignored) if ignored else '-'}",
        *extras,
    )
    return "browser session ready: " + ", ".join(fields)


def _endpoint_display(url: str) -> str:
    parts = urlsplit(url)
    host = parts.hostname or ""
    port = parts.port
    if host and port is not None:
        return f"{host}:{port}"
    if host:
        return host
    return url


def _port_display(url: str) -> str:
    """Return the port of a CDP URL as a string, or ``""`` when absent."""
    port = urlsplit(url).port
    return str(port) if port is not None else ""


def _mlx_folder_id(provider: ManagedBrowserProvider) -> str:
    """Read the MLX folder id shown in the managed startup line.

    The generic protocol only guarantees ``profile_id``; MLX's provider also
    exposes its target, and the startup line keeps reporting ``folder_id``.
    """
    target = getattr(provider, "target", None)
    value = getattr(target, "folder_id", "")
    return str(value) if value is not None else ""


def _managed_extras(
    provider: ManagedBrowserProvider, connect_url: str
) -> tuple[str, ...]:
    """Provider-specific startup fields: MLX keeps folder/port, others endpoint."""
    if provider.mode == "multilogin":
        return (
            f"folder_id={_mlx_folder_id(provider)}",
            f"port={_port_display(connect_url)}",
        )
    return (f"endpoint={_endpoint_display(connect_url)}",)


@dataclass(slots=True)
class BrowserSession:
    browser: "Browser"
    context: "BrowserContext"
    mode: Literal["local", "multilogin", "adspower"]

    @property
    def managed(self) -> bool:
        return self.mode != "local"


@asynccontextmanager
async def browser_session(
    playwright: "Playwright",
    *,
    headless: bool,
    account_file: str | Path | None = None,
    managed: ManagedBrowserProvider | None = None,
    launch_kwargs: Mapping[str, Any] | None = None,
    context_kwargs: Mapping[str, Any] | None = None,
    init_script: bool = False,
    context_setup: Callable[
        ["BrowserContext"], Awaitable["BrowserContext | None"]
    ]
    | None = None,
    extra_ignored: Iterable[str] = (),
) -> AsyncIterator[BrowserSession]:
    """Acquire a browser context for either local or managed browser mode.

    ``managed is None`` → existing local ``launch`` / ``new_context`` /
    ``storage_state`` behaviour.  Otherwise the provider starts its profile,
    the session attaches over CDP, and the profile is stopped on exit.

    Managed mode cannot apply ``launch_kwargs`` / ``context_kwargs`` /
    ``init_script`` / ``context_setup``; each non-empty one is reported once in
    a warning and in the startup line.  ``extra_ignored`` lets a caller report
    further keys it dropped itself (the CLI passes ``"account"``).
    """

    if managed is None:
        async with _local_session(
            playwright,
            headless=headless,
            account_file=account_file,
            launch_kwargs=launch_kwargs,
            context_kwargs=context_kwargs,
            init_script=init_script,
            context_setup=context_setup,
        ) as session:
            yield session
        return

    ignored = _ignored_option_names(
        launch_kwargs=launch_kwargs,
        context_kwargs=context_kwargs,
        init_script=init_script,
        context_setup=context_setup,
        extra=extra_ignored,
    )
    if ignored:
        logger.warning(MANAGED_IGNORED_WARNING.format(keys=", ".join(ignored)))

    async with _managed_session(
        playwright,
        headless=headless,
        provider=managed,
        ignored=ignored,
    ) as session:
        yield session


@asynccontextmanager
async def _local_session(
    playwright: "Playwright",
    *,
    headless: bool,
    account_file: str | Path | None,
    launch_kwargs: Mapping[str, Any] | None,
    context_kwargs: Mapping[str, Any] | None,
    init_script: bool,
    context_setup: Callable[
        ["BrowserContext"], Awaitable["BrowserContext | None"]
    ]
    | None,
) -> AsyncIterator[BrowserSession]:
    launch_options = dict(launch_kwargs or {})
    if "headless" in launch_options:
        raise ValueError(
            "launch_kwargs must not contain 'headless'; pass headless=... instead"
        )

    context_options = dict(context_kwargs or {})
    if "storage_state" in context_options:
        raise ValueError(
            "context_kwargs must not contain 'storage_state'; pass account_file=... instead"
        )

    browser = await playwright.chromium.launch(headless=headless, **launch_options)
    context = await browser.new_context(
        storage_state=account_file,
        **context_options,
    )

    if init_script:
        prepared = await set_init_script(context)
        if prepared is not None:
            context = prepared

    if context_setup is not None:
        prepared = await context_setup(context)
        if prepared is not None:
            context = prepared

    identity = (
        f"account_file:{account_file}" if account_file is not None else "account_file:-"
    )
    logger.info(
        _startup_line(mode="local", headless=headless, identity=identity, ignored=())
    )

    completed = False
    try:
        yield BrowserSession(browser=browser, context=context, mode="local")
        completed = True
    finally:
        # Cookie write-back only on a clean exit, matching the uploaders.
        if completed and account_file is not None:
            await context.storage_state(path=account_file)
        try:
            await context.close()
        finally:
            await browser.close()


@asynccontextmanager
async def _managed_session(
    playwright: "Playwright",
    *,
    headless: bool,
    provider: ManagedBrowserProvider,
    ignored: tuple[str, ...] = (),
) -> AsyncIterator[BrowserSession]:
    # Probe and Start happen before the try block on purpose: if Start fails the
    # profile may belong to somebody else, so we must never Stop it.  The one
    # exception is ``StartIncompleteError``: the server confirmed a 2xx but the
    # payload was unusable, so the profile was probably started and we do a
    # best-effort stop before re-raising.
    await asyncio.to_thread(provider.probe)
    try:
        connect_url = await asyncio.to_thread(provider.start, headless)
    except StartIncompleteError:
        await _stop_profile(provider)
        raise

    browser: "Browser | None" = None
    try:
        browser = await _connect_over_cdp(playwright, provider, connect_url)
        contexts = browser.contexts
        if len(contexts) != 1:
            if provider.mode == "multilogin":
                raise RuntimeError(
                    "Multilogin Profile 的浏览器上下文数量异常"
                    f"（期望 1，实际 {len(contexts)}）："
                    f"profile_id={provider.profile_id}"
                )
            raise RuntimeError(
                "托管浏览器上下文数量异常"
                f"（期望 1，实际 {len(contexts)}）："
                f"mode={provider.mode}，profile_id={provider.profile_id}"
            )
        logger.info(
            _startup_line(
                mode=provider.mode,
                headless=headless,
                identity=f"profile:{provider.profile_id}",
                ignored=ignored,
                extras=_managed_extras(provider, connect_url),
            )
        )
        yield BrowserSession(
            browser=browser,
            context=contexts[0],
            mode=provider.mode,
        )
    finally:
        try:
            if browser is not None:
                await _disconnect(browser, provider.mode)
        finally:
            await _stop_profile(provider)


async def _connect_over_cdp(
    playwright: "Playwright",
    provider: ManagedBrowserProvider,
    connect_url: str,
) -> "Browser":
    last_error: BaseException | None = None

    for attempt in range(CONNECT_ATTEMPTS):
        try:
            return await playwright.chromium.connect_over_cdp(
                connect_url,
                timeout=CONNECT_TIMEOUT_MS,
                no_defaults=True,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # connection refused / timeout / driver error
            last_error = exc
            if attempt < len(CONNECT_BACKOFF_SECONDS):
                await asyncio.sleep(CONNECT_BACKOFF_SECONDS[attempt])

    # Enrich the error once with the provider's last-known profile state.
    status_text = "未知"
    try:
        status_text = await asyncio.to_thread(provider.status)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        status_text = f"查询失败（{exc}）"

    if provider.mode == "multilogin":
        raise RuntimeError(
            "无法通过 CDP 连接 Multilogin Profile"
            f"（profile_id={provider.profile_id}，"
            f"port={_port_display(connect_url)}，"
            f"已尝试 {CONNECT_ATTEMPTS} 次）：{last_error}；"
            f"Profile 状态：{status_text}。{_connection_hint(provider.mode)}"
        )

    label = provider_label(provider.mode)
    raise RuntimeError(
        f"无法通过 CDP 连接 {label} Profile"
        f"（mode={provider.mode}，profile_id={provider.profile_id}，"
        f"endpoint={_endpoint_display(connect_url)}，"
        f"已尝试 {CONNECT_ATTEMPTS} 次）：{last_error}；"
        f"Profile 状态：{status_text}。{_connection_hint(provider.mode)}"
    )


async def _disconnect(browser: "Browser", mode: str) -> None:
    try:
        await browser.close()
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        if mode == "multilogin":
            logger.warning(
                "断开 Multilogin 浏览器连接失败：{}；已上传结果不受影响。",
                exc,
            )
        else:
            logger.warning(
                "断开 {} 浏览器连接失败：{}；已上传结果不受影响。",
                provider_label(mode),
                exc,
            )


async def _stop_profile(provider: ManagedBrowserProvider) -> None:
    if provider.mode == "multilogin":
        logger.info(
            "正在停止 Multilogin Profile：profile_id={}",
            provider.profile_id,
        )
    else:
        logger.info(
            "正在停止 {} Profile：profile_id={}",
            provider_label(provider.mode),
            provider.profile_id,
        )
    try:
        # Shield the stop request so cancellation still sends it.  Providers are
        # synchronous (HTTP clients), so run them in a worker thread.
        await asyncio.shield(asyncio.to_thread(provider.stop))
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        if provider.mode == "multilogin":
            logger.warning(
                "停止 Multilogin Profile 失败（profile_id={}）：{}；"
                "Profile 可能仍在运行，需调度侧清理。",
                provider.profile_id,
                exc,
            )
        else:
            logger.warning(
                "停止 {} Profile 失败（profile_id={}）：{}；"
                "Profile 可能仍在运行，需调度侧清理。",
                provider_label(provider.mode),
                provider.profile_id,
                exc,
            )


__all__ = ["BrowserSession", "browser_session", "provider_label"]
