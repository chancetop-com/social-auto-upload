# -*- coding: utf-8 -*-
"""Canonical CLI helpers for managed browser mode.

This module never talks to a desktop app and never stores an API token.  The
environment only decides which provider (if any) is active; the provider itself
is constructed here and owns the credential for its lifetime.

Both managed providers (Multilogin X and AdsPower) are selected here by
environment variable alone; platform modules only ever receive a provider and
never branch on the product name.
"""

from __future__ import annotations

import argparse
import os
from urllib.parse import urlsplit

from utils.adspower import AdspowerClient, AdspowerProvider, AdspowerTarget
from utils.errors import LoginRequiredError, UsageError
from utils.managed_browser import ManagedBrowserProvider, ProviderMode
from utils.multilogin import MultiloginClient, MultiloginProvider, MultiloginTarget

MLX_TOKEN_ENV = "MLX_API_TOKEN"
ADSPOWER_KEY_ENV = "ADSPOWER_API_KEY"
ADSPOWER_BASE_ENV = "ADSPOWER_API_BASE"

DEFAULT_ADSPOWER_BASE = "http://127.0.0.1:50325"

DUAL_CREDENTIALS_MESSAGE = (
    "MLX_API_TOKEN 与 ADSPOWER_API_KEY 不能同时设置；请只保留一个。"
)
MISSING_MLX_TARGET_MESSAGE = (
    "Multilogin 模式需要同时提供 --folder-id 与 --profile-id。"
)
MISSING_MLX_TOKEN_MESSAGE = "未设置 MLX_API_TOKEN，无法使用 Multilogin 模式。"
MISSING_ADSPOWER_PROFILE_MESSAGE = "AdsPower 模式需要提供 --profile-id。"
INVALID_ADSPOWER_BASE_MESSAGE = (
    "ADSPOWER_API_BASE 不合法：{base}。"
    "仅支持 http/https、主机名与可选端口，"
    "且不得包含用户信息、路径、查询或片段。"
)
MISSING_ACCOUNT_MESSAGE = "本地模式需要 --account。"

_LOGIN_REJECTED_TEMPLATES = {
    "multilogin": (
        "Multilogin 模式不支持 CLI 登录；"
        "请在 Multilogin 应用中登录 {profile} 后重试。"
    ),
    "adspower": (
        "AdsPower 模式不支持 CLI 登录；"
        "请在 AdsPower 中登录 {profile} 后重试。"
    ),
}

_PLATFORM_REJECTED_TEMPLATES = {
    "multilogin": (
        "Multilogin 模式不支持 {platform}；"
        "请在本地模式（不设置 MLX_API_TOKEN）下重试。"
    ),
    "adspower": (
        "AdsPower 模式不支持 {platform}；"
        "请在本地模式（不设置 ADSPOWER_API_KEY）下重试。"
    ),
}

_APP_LABELS = {
    "multilogin": "Multilogin",
    "adspower": "AdsPower",
}


def _mlx_token() -> str:
    return os.environ.get(MLX_TOKEN_ENV, "").strip()


def _adspower_key() -> str:
    return os.environ.get(ADSPOWER_KEY_ENV, "").strip()


def active_mode() -> ProviderMode | None:
    """Return the active managed provider mode, or ``None`` for local mode.

    Only the credential environment variables participate: a non-empty
    ``MLX_API_TOKEN`` activates Multilogin, otherwise a non-empty
    ``ADSPOWER_API_KEY`` activates AdsPower.  ``ADSPOWER_API_BASE`` never
    activates anything and is only validated once AdsPower is active.
    """
    if _mlx_token():
        return "multilogin"
    if _adspower_key():
        return "adspower"
    return None


def credentials_conflict() -> bool:
    """Return ``True`` when both managed credentials are set.

    ``sau_cli.main`` turns this into a runtime error (exit code 1) after
    argument parsing and before dispatch, so argparse semantics for ``--help``
    and unknown subcommands are preserved.
    """
    return bool(_mlx_token() and _adspower_key())


def managed_enabled() -> bool:
    """Return ``True`` when any managed browser provider is active."""
    return active_mode() is not None


def multilogin_enabled() -> bool:
    """Legacy MLX-only activation predicate retained by the shim."""
    return _mlx_token() != ""


def add_browser_flags(parser: argparse.ArgumentParser) -> None:
    """Register the shared Profile flags on a runnable action parser."""
    parser.add_argument(
        "--folder-id",
        default=None,
        help="MLX 模式必填；AdsPower 模式忽略",
    )
    parser.add_argument(
        "--profile-id",
        default=None,
        help="MLX / AdsPower 模式必填",
    )


def add_multilogin_flags(parser: argparse.ArgumentParser) -> None:
    """Backwards-compatible name for :func:`add_browser_flags`."""
    add_browser_flags(parser)


def _resolve_mlx_target(args: argparse.Namespace) -> MultiloginTarget:
    folder_id = str(getattr(args, "folder_id", None) or "").strip()
    profile_id = str(getattr(args, "profile_id", None) or "").strip()
    if not folder_id or not profile_id:
        raise UsageError(MISSING_MLX_TARGET_MESSAGE)
    return MultiloginTarget(folder_id=folder_id, profile_id=profile_id)


def resolve_multilogin_target(
    args: argparse.Namespace,
) -> MultiloginTarget | None:
    """Legacy MLX-only target resolver retained for the shim and tests."""
    if not multilogin_enabled():
        return None
    return _resolve_mlx_target(args)


def _resolve_adspower_base() -> str:
    """Validate and normalise ``ADSPOWER_API_BASE`` for the active AdsPower mode.

    Called only from the AdsPower provider branch, so an invalid value never
    affects local or Multilogin runs and never issues an HTTP request.
    """
    raw = os.environ.get(ADSPOWER_BASE_ENV, "").strip()
    if not raw:
        return DEFAULT_ADSPOWER_BASE

    try:
        parts = urlsplit(raw)
        # Accessing ``port`` raises ValueError for non-numeric / out-of-range
        # ports; that is exactly the rejection we want.
        parts.port
    except ValueError:
        raise UsageError(INVALID_ADSPOWER_BASE_MESSAGE.format(base=raw)) from None

    invalid = (
        parts.scheme not in ("http", "https")
        or not parts.hostname
        or parts.username is not None
        or parts.password is not None
        or parts.path not in ("", "/")
        or bool(parts.query)
        or bool(parts.fragment)
        or parts.netloc.endswith(":")
    )
    if invalid:
        raise UsageError(INVALID_ADSPOWER_BASE_MESSAGE.format(base=raw))

    # Rebuild from the validated pieces so a single trailing ``/`` is dropped
    # without touching the host or port spelling.
    return f"{parts.scheme}://{parts.netloc}"


def _resolve_adspower_target(args: argparse.Namespace) -> AdspowerTarget:
    profile_id = str(getattr(args, "profile_id", None) or "").strip()
    if not profile_id:
        raise UsageError(MISSING_ADSPOWER_PROFILE_MESSAGE)
    return AdspowerTarget(profile_id=profile_id)


def resolve_managed_provider(
    args: argparse.Namespace,
) -> ManagedBrowserProvider | None:
    """Build the active provider (``None`` in local mode).

    The token/key is read here rather than in ``browser_session`` so a missing
    credential fails before any profile is started.
    """
    mode = active_mode()
    if mode is None:
        return None

    if mode == "multilogin":
        token = _mlx_token()
        if not token:
            raise RuntimeError(MISSING_MLX_TOKEN_MESSAGE)
        target = _resolve_mlx_target(args)
        return MultiloginProvider(target, MultiloginClient(token))

    if mode == "adspower":
        key = _adspower_key()
        if not key:
            raise RuntimeError("未设置 ADSPOWER_API_KEY，无法使用 AdsPower 模式。")
        target = _resolve_adspower_target(args)
        base = _resolve_adspower_base()
        return AdspowerProvider(target, AdspowerClient(key, base))

    raise RuntimeError(f"Unsupported managed browser provider: {mode}")


def resolve_account_label(args: argparse.Namespace) -> str | None:
    """Return the log/output account label.

    Managed mode defaults the label to ``profile_id``; local mode keeps the
    user-supplied ``--account``.  The label never participates in identity
    checks and never becomes a cookie path in managed mode.
    """
    if managed_enabled():
        account = getattr(args, "account", None)
        return account or getattr(args, "profile_id", None)
    return getattr(args, "account", None)


def require_local_account(args: argparse.Namespace) -> None:
    """Raise :class:`UsageError` when local mode is missing ``--account``."""
    if managed_enabled():
        return
    require_account(args)


def require_account(args: argparse.Namespace) -> None:
    """Raise :class:`UsageError` unless ``--account`` is non-empty.

    Local-only actions (``verify`` / ``delete``) keep running in local mode even
    when a managed provider is active, so they must still resolve a cookie file
    and therefore always need ``--account``.
    """
    account = getattr(args, "account", None)
    if account is None or not str(account).strip():
        raise UsageError(MISSING_ACCOUNT_MESSAGE)


def managed_app_label(mode: ProviderMode | None = None) -> str:
    """Return the product name used in user-facing managed-mode wording."""
    resolved = mode or active_mode() or "multilogin"
    return _APP_LABELS.get(resolved, resolved)


def login_required_error(
    platform_label: str,
    profile_id: str,
    *,
    mode: ProviderMode | None = None,
) -> LoginRequiredError:
    """Build the command-level login-required error for a platform."""
    app = managed_app_label(mode)
    return LoginRequiredError(
        f"{platform_label}登录态无效：profile_id={profile_id}。"
        f"请在 {app} 应用中登录 Profile 后重试。"
    )


def identity_unverified_format(
    *,
    mode: ProviderMode | None = None,
    detailed: bool = False,
) -> str:
    """Return a loguru format string with one ``{}`` placeholder for profile_id."""
    app = managed_app_label(mode)
    message = f"账号一致性未校验：以 {app} Profile 为身份（profile_id={{}}）"
    if detailed:
        message += "，请调度侧确保 profile_id 与目标账号匹配。"
    return message


def managed_timezone_hint(mode: ProviderMode | None = None) -> str:
    """Return the managed-mode timezone hint shown after identity logging."""
    return (
        f"{managed_app_label(mode)} 模式不写入时区；"
        "建议在 Profile 设置中将时区设为 Asia/Shanghai"
    )


def _profile_placeholder(args: argparse.Namespace) -> str:
    profile_id = getattr(args, "profile_id", None)
    return f"Profile {profile_id}" if profile_id else "指定 Profile"


def reject_managed_login(platform: str, args: argparse.Namespace) -> None:
    """Refuse ``login`` in managed mode with exit code 1 semantics."""
    mode = active_mode()
    if mode is None:
        return
    raise RuntimeError(
        _LOGIN_REJECTED_TEMPLATES[mode].format(profile=_profile_placeholder(args))
    )


def reject_managed_platform(platform: str, args: argparse.Namespace) -> None:
    """Refuse a platform that cannot run through the browser session seam."""
    mode = active_mode()
    if mode is None:
        return
    raise RuntimeError(
        _PLATFORM_REJECTED_TEMPLATES[mode].format(platform=platform)
    )


def reject_multilogin_login(platform: str, args: argparse.Namespace) -> None:
    """Legacy MLX-only login rejection retained by the shim."""
    if not multilogin_enabled():
        return
    raise RuntimeError(
        _LOGIN_REJECTED_TEMPLATES["multilogin"].format(
            profile=_profile_placeholder(args)
        )
    )


def reject_multilogin_platform(platform: str, args: argparse.Namespace) -> None:
    """Legacy MLX-only platform rejection retained by the shim."""
    if not multilogin_enabled():
        return
    raise RuntimeError(
        _PLATFORM_REJECTED_TEMPLATES["multilogin"].format(platform=platform)
    )


__all__ = [
    "add_browser_flags",
    "add_multilogin_flags",
    "active_mode",
    "credentials_conflict",
    "identity_unverified_format",
    "login_required_error",
    "managed_app_label",
    "managed_enabled",
    "managed_timezone_hint",
    "multilogin_enabled",
    "reject_managed_login",
    "reject_managed_platform",
    "reject_multilogin_login",
    "reject_multilogin_platform",
    "require_account",
    "require_local_account",
    "resolve_account_label",
    "resolve_managed_provider",
    "resolve_multilogin_target",
]
