# -*- coding: utf-8 -*-
"""Pure CLI helpers for the optional Multilogin X browser mode.

This module never talks to the Launcher and never stores the API token.  The
token only decides whether the CLI runs in Multilogin mode; it is read again by
``utils.browser_session`` when a session is actually started.
"""

from __future__ import annotations

import argparse
import os

from utils.errors import LoginRequiredError, UsageError
from utils.multilogin import MultiloginTarget

LOGIN_REJECTED_TEMPLATE = (
    "Multilogin 模式不支持 CLI 登录；请在 Multilogin 应用中登录 {profile} 后重试。"
)
PLATFORM_REJECTED_TEMPLATE = (
    "Multilogin 模式不支持 {platform}；请在本地模式（不设置 MLX_API_TOKEN）下重试。"
)
MISSING_TARGET_MESSAGE = "Multilogin 模式需要同时提供 --folder-id 与 --profile-id。"
MISSING_ACCOUNT_MESSAGE = "本地模式需要 --account。"


def multilogin_enabled() -> bool:
    """Return ``True`` only for a non-empty, non-whitespace token."""
    return os.environ.get("MLX_API_TOKEN", "").strip() != ""


def add_multilogin_flags(parser: argparse.ArgumentParser) -> None:
    """Register the Multilogin Profile flags on a runnable action parser."""
    parser.add_argument(
        "--folder-id",
        default=None,
        help="Multilogin Folder ID（MLX 模式必填）",
    )
    parser.add_argument(
        "--profile-id",
        default=None,
        help="Multilogin Profile ID（MLX 模式必填）",
    )


def resolve_multilogin_target(args: argparse.Namespace) -> MultiloginTarget | None:
    """Return the MLX target, or ``None`` in local mode.

    Local mode silently ignores both flags, matching the activation contract.
    """
    if not multilogin_enabled():
        return None

    folder_id = str(getattr(args, "folder_id", None) or "").strip()
    profile_id = str(getattr(args, "profile_id", None) or "").strip()
    if not folder_id or not profile_id:
        raise UsageError(MISSING_TARGET_MESSAGE)
    return MultiloginTarget(folder_id=folder_id, profile_id=profile_id)


def resolve_account_label(args: argparse.Namespace) -> str | None:
    """Return the log/output account label.

    Multilogin mode defaults the label to ``profile_id``; local mode keeps the
    user-supplied ``--account``.  The label never participates in identity
    checks and never becomes a cookie path in Multilogin mode.
    """
    if multilogin_enabled():
        account = getattr(args, "account", None)
        return account or getattr(args, "profile_id", None)
    return getattr(args, "account", None)


def require_local_account(args: argparse.Namespace) -> None:
    """Raise :class:`UsageError` when local mode is missing ``--account``."""
    if multilogin_enabled():
        return
    require_account(args)


def require_account(args: argparse.Namespace) -> None:
    """Raise :class:`UsageError` unless ``--account`` is non-empty.

    Local-only actions (``verify`` / ``delete``) keep running in local mode even
    when ``MLX_API_TOKEN`` is set, so they must still resolve a cookie file and
    therefore always need ``--account``.
    """
    account = getattr(args, "account", None)
    if account is None or not str(account).strip():
        raise UsageError(MISSING_ACCOUNT_MESSAGE)


def login_required_error(platform_label: str, profile_id: str) -> LoginRequiredError:
    """Build the command-level login-required error for a platform."""
    return LoginRequiredError(
        f"{platform_label}登录态无效：profile_id={profile_id}。"
        "请在 Multilogin 应用中登录 Profile 后重试。"
    )


def reject_multilogin_login(platform: str, args: argparse.Namespace) -> None:
    """Refuse ``login`` in Multilogin mode with exit code 1 semantics."""
    if not multilogin_enabled():
        return
    profile_id = getattr(args, "profile_id", None)
    target = f"Profile {profile_id}" if profile_id else "指定 Profile"
    raise RuntimeError(LOGIN_REJECTED_TEMPLATE.format(profile=target))


def reject_multilogin_platform(platform: str, args: argparse.Namespace) -> None:
    """Refuse a platform that cannot run through the browser session seam."""
    if not multilogin_enabled():
        return
    raise RuntimeError(PLATFORM_REJECTED_TEMPLATE.format(platform=platform))


__all__ = [
    "add_multilogin_flags",
    "login_required_error",
    "multilogin_enabled",
    "reject_multilogin_login",
    "reject_multilogin_platform",
    "require_account",
    "require_local_account",
    "resolve_account_label",
    "resolve_multilogin_target",
]
